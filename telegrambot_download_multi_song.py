import os
import tempfile
import asyncio
import shutil
import time
import glob
import urllib.parse
from typing import Optional, List
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
import yt_dlp
import datetime

# Read tokens from environment variables for safety
# Optionally load a local .env file during development (requires python-dotenv)
from pathlib import Path
_DOTENV_PATH = Path(__file__).with_name('.env')
try:
    # local import; if python-dotenv isn't installed this will silently pass
    from dotenv import load_dotenv  # type: ignore
    # Prefer a .env next to this script (works even when running from other CWDs)
    if _DOTENV_PATH.exists():
        load_dotenv(dotenv_path=str(_DOTENV_PATH))
    else:
        # fallback to default behavior (searches CWD)
        load_dotenv()
except Exception:
    pass

# Read the token from the TELEGRAM_TOKEN environment variable
TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Cookie TTL in days (0 disables expiry). Defaults to 7 days.
COOKIE_TTL_DAYS = int(os.environ.get("YTDLP_COOKIE_TTL_DAYS", "7"))

# Optional owner id for admin commands (list all cookies)
try:
    BOT_OWNER_ID = int(os.environ.get("BOT_OWNER_ID")) if os.environ.get("BOT_OWNER_ID") else None
except Exception:
    BOT_OWNER_ID = None

# If token still missing, attempt a minimal .env parse as a fallback (no extra dependency)
if not TOKEN:
    try:
        env_path = Path(__file__).with_name('.env')
        if env_path.exists():
            for line in env_path.read_text(encoding='utf8').splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' not in line:
                    continue
                key, val = line.split('=', 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                # Only set variables that aren't already present
                if key and key not in os.environ:
                    os.environ[key] = val
            TOKEN = os.environ.get("TELEGRAM_TOKEN")
    except Exception:
        # never crash on fallback
        TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Command: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hello! Use /yt <youtube_url> or send /yt and then reply with the YouTube URL to download the audio as MP3."
    )


# Command: /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Usage:\n/yt <youtube_url> - download audio as MP3\nOr: send /yt and then paste the YouTube URL as the next message."
    )


# We no longer use the YouTube Data API. The bot asks the user for the YouTube URL directly.


async def download_audio_mp3(url: str, progress_msg: Optional[object] = None, loop: Optional[asyncio.AbstractEventLoop] = None, cookie_file: Optional[str] = None) -> str:
    """Download audio from url using yt_dlp and return path to the MP3 file.

    If progress_msg is provided (a telegram.Message), the function will update that
    message with download progress. `loop` should be the asyncio event loop to use
    for scheduling message edits (usually asyncio.get_event_loop()).
    """
    # Use a temporary directory to store the downloaded file
    tmpdir = tempfile.mkdtemp(prefix="ytmp_")
    outtmpl = os.path.join(tmpdir, "%(title)s.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        # Avoid downloading full playlists; only download the single video
        "noplaylist": True,
        "playlist_items": "1",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        # Avoid console output clutter
        "quiet": True,
        "no_warnings": True,
    }
    # If a cookie_file param was not passed, fall back to environment variables
    cookie_cfg = cookie_file or os.environ.get("YTDLP_COOKIES_FILE") or os.environ.get("YTDLP_COOKIES")
    # If cookie_cfg contains cookie contents (not a path), write to a temp file
    if cookie_cfg and not os.path.exists(cookie_cfg):
        try:
            tmp_cf = os.path.join(tempfile.gettempdir(), "ytdlp_cookies.txt")
            with open(tmp_cf, "w", encoding="utf8") as _cf:
                _cf.write(cookie_cfg)
            cookie_cfg = tmp_cf
        except Exception:
            cookie_cfg = None

    if cookie_cfg:
        # If TTL configured, check expiry
        try:
            if COOKIE_TTL_DAYS > 0:
                mtime = os.path.getmtime(cookie_cfg)
                age_days = (time.time() - mtime) / 86400.0
                if age_days > COOKIE_TTL_DAYS:
                    # expired: remove file and ignore cookie
                    try:
                        os.remove(cookie_cfg)
                    except Exception:
                        pass
                    cookie_cfg = None
        except Exception:
            # if we cannot stat the file, just ignore expiry
            pass
        if cookie_cfg:
            ydl_opts["cookiefile"] = cookie_cfg

    # Determine which loop to use for scheduling coroutine edits from the hook
    if loop is None:
        loop = asyncio.get_event_loop()

    last_update_time = 0.0

    def sizeof_fmt(num, suffix="B"):
        for unit in ["", "K", "M", "G", "T"]:
            if abs(num) < 1024.0:
                return f"{num:3.1f}{unit}{suffix}"
            num /= 1024.0
        return f"{num:.1f}P{suffix}"

    def make_progress_hook():
        # Create a closure so we can keep last_update_time per-download
        last_time = {"t": 0.0}
        state = {"finished": False, "entry_id": None}

        def progress_hook(d):
            # d is a dict provided by yt-dlp with keys like status, downloaded_bytes, total_bytes, speed, eta
            try:
                status = d.get("status")
                # Identify the entry/video being processed
                info_dict = d.get("info_dict") or {}
                entry_id = info_dict.get("id") or d.get("filename") or None

                # If we've already finished this entry, ignore further 'downloading' events
                if state["finished"] and entry_id is not None and state["entry_id"] == entry_id and status == "downloading":
                    return
                now = time.time()
                # Throttle updates to roughly once per second
                if now - last_time["t"] < 1.0 and status == "downloading":
                    return
                last_time["t"] = now

                if status == "downloading":
                    downloaded = d.get("downloaded_bytes") or 0
                    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    speed = d.get("speed") or 0
                    eta = d.get("eta")
                    if total:
                        percent = downloaded / total * 100
                        pct_text = f"{percent:3.1f}%"
                    else:
                        pct_text = "?%"

                    speed_text = sizeof_fmt(speed) + "/s" if speed else "-"
                    eta_text = f"{int(eta)}s" if eta else "-"
                    message = f"Downloading: {pct_text} • {speed_text} • ETA {eta_text}"
                elif status == "finished":
                    # Mark finished for this entry to avoid duplicate re-download events
                    state["finished"] = True
                    if entry_id is not None:
                        state["entry_id"] = entry_id
                    message = "Download finished, converting to MP3..."
                else:
                    message = f"Status: {status}"

                # If a progress message was provided, schedule an edit on the main loop
                if progress_msg is not None:
                    async def do_edit():
                        try:
                            await progress_msg.edit_text(message)
                        except Exception:
                            # ignore failures to edit (e.g., message deleted)
                            pass

                    try:
                        asyncio.run_coroutine_threadsafe(do_edit(), loop)
                    except Exception:
                        pass
            except Exception:
                # Ensure hook never crashes
                pass

        return progress_hook

    ydl_opts["progress_hooks"] = [make_progress_hook()]

    def run_ydl():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # After postprocessing, the filename can be obtained
            filename = ydl.prepare_filename(info)
            # replace extension with mp3
            base, _ = os.path.splitext(filename)
            return base + ".mp3"

    mp3_path = await loop.run_in_executor(None, run_ydl)
    return mp3_path


def is_playlist_url(url: str) -> bool:
    """Return True if the URL is a playlist URL (playlist path or list param without v param)."""
    try:
        p = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(p.query)
        has_list = "list" in qs
        has_v = "v" in qs
        is_playlist_path = "playlist" in p.path
        return (has_list and not has_v) or is_playlist_path
    except Exception:
        return False


async def download_playlist_mp3(url: str, progress_msg: Optional[object] = None, loop: Optional[asyncio.AbstractEventLoop] = None, max_items: int = 50, cookie_file: Optional[str] = None) -> tuple[list, str]:
    """Download a playlist and return (list of MP3 file paths, tempdir). Caps at max_items.

    Returns a tuple (mp3_paths, tmpdir) so the caller can cleanup tmpdir after sending.
    """
    tmpdir = tempfile.mkdtemp(prefix="ytplaylist_")
    outtmpl = os.path.join(tmpdir, "%(playlist_index)s - %(title)s.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        # allow playlists
        "noplaylist": False,
        # continue on individual download errors (skip unavailable/private videos)
        "ignoreerrors": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
    }
    # support cookies for playlist downloads too (prefer explicit param)
    cookie_cfg = cookie_file or os.environ.get("YTDLP_COOKIES_FILE") or os.environ.get("YTDLP_COOKIES")
    if cookie_cfg and not os.path.exists(cookie_cfg):
        try:
            tmp_cf = os.path.join(tempfile.gettempdir(), "ytdlp_cookies.txt")
            with open(tmp_cf, "w", encoding="utf8") as _cf:
                _cf.write(cookie_cfg)
            cookie_cfg = tmp_cf
        except Exception:
            cookie_cfg = None

    if cookie_cfg:
        try:
            if COOKIE_TTL_DAYS > 0:
                mtime = os.path.getmtime(cookie_cfg)
                age_days = (time.time() - mtime) / 86400.0
                if age_days > COOKIE_TTL_DAYS:
                    try:
                        os.remove(cookie_cfg)
                    except Exception:
                        pass
                    cookie_cfg = None
        except Exception:
            pass
        if cookie_cfg:
            ydl_opts["cookiefile"] = cookie_cfg

    if loop is None:
        loop = asyncio.get_event_loop()

    def make_progress_hook():
        last_time = {"t": 0.0}

        def progress_hook(d):
            try:
                status = d.get("status")
                now = time.time()
                if now - last_time["t"] < 1.0 and status == "downloading":
                    return
                last_time["t"] = now
                # Try to get playlist position info if available
                info = d.get("info_dict") or {}
                p_index = info.get("playlist_index") or d.get("playlist_index") or None
                p_count = info.get("playlist_count") or d.get("playlist_count") or None

                if status == "downloading":
                    downloaded = d.get("downloaded_bytes") or 0
                    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    speed = d.get("speed") or 0
                    eta = d.get("eta")
                    if total:
                        percent = downloaded / total * 100
                        pct_text = f"{percent:3.1f}%"
                    else:
                        pct_text = "?%"
                    speed_text = f"{speed and (speed/1024):.1f}KB/s" if speed else "-"
                    eta_text = f"{int(eta)}s" if eta else "-"
                    prefix = f"[{p_index}/{p_count}] " if p_index and p_count else ""
                    message = f"{prefix}Downloading: {pct_text} • {speed_text} • ETA {eta_text}"
                elif status == "finished":
                    prefix = f"[{p_index}/{p_count}] " if p_index and p_count else ""
                    message = f"{prefix}Downloaded item; converting to MP3..."
                else:
                    message = f"Status: {status}"

                if progress_msg is not None:
                    async def do_edit():
                        try:
                            await progress_msg.edit_text(message)
                        except Exception:
                            pass
                    try:
                        asyncio.run_coroutine_threadsafe(do_edit(), loop)
                    except Exception:
                        pass
            except Exception:
                pass

        return progress_hook

    ydl_opts["progress_hooks"] = [make_progress_hook()]

    def run_ydl():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return info

    info = await loop.run_in_executor(None, run_ydl)

    # After download, scan the tempdir for produced mp3 files
    mp3_files = glob.glob(os.path.join(tmpdir, "*.mp3"))
    # Sort by playlist_index prefix if present (filename starts with "<index> - ")
    def sort_key(name):
        base = os.path.basename(name)
        try:
            prefix = base.split(" - ")[0]
            return int(prefix)
        except Exception:
            return 10**9

    mp3_files.sort(key=sort_key)

    # Enforce max_items
    if len(mp3_files) > max_items:
        # cleanup and raise
        raise RuntimeError(f"Playlist produced {len(mp3_files)} mp3 files, limit is {max_items}")

    # Ensure files are fully written: wait briefly for sizes to stabilize
    stable = []
    for f in mp3_files:
        last_size = -1
        for _ in range(6):  # up to ~3 seconds
            try:
                cur = os.path.getsize(f)
            except Exception:
                cur = -1
            if cur > 0 and cur == last_size:
                stable.append(f)
                break
            last_size = cur
            # small sleep
            time.sleep(0.5)
        else:
            # if not stable but file exists with size>0, include it
            if os.path.exists(f) and os.path.getsize(f) > 0:
                stable.append(f)

    # Keep only stable files, sorted
    mp3_files = [f for f in mp3_files if f in stable]

    mp3_files.sort(key=lambda p: int(os.path.basename(p).split(" - ")[0]) if os.path.basename(p).split(" - ")[0].isdigit() else 10**9)

    return mp3_files, tmpdir


async def yt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /yt command.

    Usage:
    - /yt <youtube_url>  -> directly download that URL
    - /yt                -> bot asks for the URL and the next text message will be used
    """
    # If user provided the URL as argument, use it directly
    if context.args:
        url = context.args[0]
        await update.message.reply_text(f"Downloading audio from: {url} (this may take a while)...")
        await handle_download_and_send(update, context, url)
        return

    # Otherwise prompt the user to send the URL
    await update.message.reply_text("Please send the YouTube URL for the song you want to download as MP3.")
    # Set a flag in user_data so the next text message is treated as the URL
    context.user_data["awaiting_yt_url"] = True


async def setcookies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Instructional command asking user to upload a cookies.txt file or paste cookies as a message."""
    await update.message.reply_text(
        "To set cookies, upload a cookies.txt file exported from your browser (File -> Send as document), or paste the cookie contents as a message after running /setcookies_paste.\n"
        "This will be stored only for this chat. To remove, use /cleancookies."
    )


async def setcookies_paste_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a state where the next message text will be treated as raw cookie contents."""
    context.user_data["awaiting_cookies_paste"] = True
    await update.message.reply_text("Please paste your cookies.txt contents in the next message. The data will be stored temporarily for this chat.")


async def cleancookies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove stored cookie file for this chat."""
    cd = context.chat_data
    removed = False
    if cd.get("cookiefile"):
        try:
            path = cd.pop("cookiefile")
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        removed = True
    if cd.get("cookie_contents"):
        cd.pop("cookie_contents", None)
        removed = True
    if removed:
        await update.message.reply_text("Cookies removed for this chat.")
    else:
        await update.message.reply_text("No cookies were stored for this chat.")


async def listcookies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List whether this chat has stored cookies and their age."""
    cd = context.chat_data
    if cd.get("cookiefile") and os.path.exists(cd.get("cookiefile")):
        p = cd.get("cookiefile")
        try:
            mtime = os.path.getmtime(p)
            age = datetime.timedelta(seconds=(time.time() - mtime))
            await update.message.reply_text(f"Cookie file stored for this chat: {os.path.basename(p)} (age: {age})")
        except Exception:
            await update.message.reply_text(f"Cookie file stored for this chat: {os.path.basename(p)}")
    elif cd.get("cookie_contents"):
        await update.message.reply_text("Cookies stored as pasted contents for this chat (no file on disk).")
    else:
        await update.message.reply_text("No cookies stored for this chat.")


async def listallcookies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: list all cookie files present in temp dir matching our naming."""
    user = update.effective_user
    if BOT_OWNER_ID and user and user.id != BOT_OWNER_ID:
        await update.message.reply_text("Not authorized.")
        return
    tmp = tempfile.gettempdir()
    pattern = os.path.join(tmp, "ytdlp_cookies_chat_*.txt")
    files = glob.glob(pattern)
    if not files:
        await update.message.reply_text("No per-chat cookie files found.")
        return
    lines = []
    for f in files:
        try:
            mtime = os.path.getmtime(f)
            age = datetime.timedelta(seconds=(time.time() - mtime))
            lines.append(f"{os.path.basename(f)} (age: {age})")
        except Exception:
            lines.append(os.path.basename(f))
    # split into multiple messages if too long
    msg = "\n".join(lines)
    await update.message.reply_text(msg)


def startup_cleanup_cookie_files():
    """Remove stale cookie files in temp dir that match our naming and exceed TTL."""
    if COOKIE_TTL_DAYS <= 0:
        return
    tmp = tempfile.gettempdir()
    pattern = os.path.join(tmp, "ytdlp_cookies_chat_*.txt")
    for f in glob.glob(pattern):
        try:
            mtime = os.path.getmtime(f)
            age_days = (time.time() - mtime) / 86400.0
            if age_days > COOKIE_TTL_DAYS:
                try:
                    os.remove(f)
                except Exception:
                    pass
        except Exception:
            pass


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded document; if it's named like cookies.txt store it for the chat."""
    if not update.message or not update.message.document:
        return
    doc = update.message.document
    fname = doc.file_name or ""
    # Only accept likely cookie files to avoid storing arbitrary uploads
    if "cookie" not in fname.lower() and "cookies" not in fname.lower():
        await update.message.reply_text("Uploaded file doesn't look like a cookies file. If you want to set cookies, upload your exported cookies.txt file from the browser.")
        return

    try:
        f = await doc.get_file()
        tmp_cf = os.path.join(tempfile.gettempdir(), f"ytdlp_cookies_chat_{update.effective_chat.id}.txt")
        await f.download_to_drive(tmp_cf)
        context.chat_data["cookiefile"] = tmp_cf
        await update.message.reply_text("Cookie file saved for this chat. It will be used for future downloads in this chat.")
    except Exception as e:
        await update.message.reply_text(f"Failed to save cookie file: {e}")


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain text messages. If we previously asked for a URL or cookie paste, treat accordingly."""
    if not update.message or not update.message.text:
        return

    # Handle pasted cookie contents
    if context.user_data.pop("awaiting_cookies_paste", False):
        contents = update.message.text
        try:
            tmp_cf = os.path.join(tempfile.gettempdir(), f"ytdlp_cookies_chat_{update.effective_chat.id}.txt")
            with open(tmp_cf, "w", encoding="utf8") as _cf:
                _cf.write(contents)
            context.chat_data["cookiefile"] = tmp_cf
            # Also keep raw contents (in case env var style is needed)
            context.chat_data["cookie_contents"] = contents
            await update.message.reply_text("Cookies stored for this chat. They will be used for future downloads.")
        except Exception as e:
            await update.message.reply_text(f"Failed to store cookies: {e}")
        return

    if context.user_data.pop("awaiting_yt_url", False):
        url = update.message.text.strip()
        await update.message.reply_text(f"Received URL: {url}\nStarting download...")
        await handle_download_and_send(update, context, url)


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain text messages. If we previously asked for a URL, treat this as the URL."""
    if not update.message or not update.message.text:
        return

    if context.user_data.pop("awaiting_yt_url", False):
        url = update.message.text.strip()
        await update.message.reply_text(f"Received URL: {url}\nStarting download...")
        await handle_download_and_send(update, context, url)


async def handle_download_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Download the given URL as MP3 and send it back to the user. Cleans up temp files."""
    msg = await update.message.reply_text("Preparing download...")
    mp3_path = None
    try:
        loop = asyncio.get_event_loop()
        # If the URL is a playlist, download the playlist
        if is_playlist_url(url):
            await msg.edit_text("Detected playlist URL — downloading all items...")
            # prefer per-chat cookie file if present
            cookie_file = context.chat_data.get("cookiefile")
            paths, playlist_tmpdir = await download_playlist_mp3(url, progress_msg=msg, loop=loop, cookie_file=cookie_file)
            mp3_paths = paths
        else:
            # Pass the message object so the downloader can update progress
            cookie_file = context.chat_data.get("cookiefile")
            mp3_path = await download_audio_mp3(url, progress_msg=msg, loop=loop, cookie_file=cookie_file)
            mp3_paths = [mp3_path] if mp3_path else []
    except Exception as e:
        # Try to provide actionable guidance for yt-dlp cookie auth failures
        err_text = str(e)
        if "Sign in to confirm you\u2019re not a bot" in err_text or "--cookies-from-browser" in err_text or "--cookies" in err_text:
            help_msg = (
                "yt-dlp reported that the video requires signing in.\n"
                "You can set cookies for this chat in one of these ways:\n"
                "1) Send /setcookies and upload your exported cookies.txt file as a document for this chat.\n"
                "2) Send /setcookies_paste and paste the cookies.txt contents (not recommended for public chats).\n"
                "3) Set YTDLP_COOKIES_FILE or YTDLP_COOKIES environment variable on the host (useful for server deployments).\n"
                "See: https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp for more info."
            )
            await msg.edit_text(help_msg)
            return
        else:
            await msg.edit_text(f"Download failed: {e}")
            return
        return
    # Verify produced files
    if not mp3_paths:
        await msg.edit_text("No MP3 files were produced.")
        return

    # If only one file, send it as audio
    if len(mp3_paths) == 1:
        mp3_path = mp3_paths[0]
        if not os.path.isfile(mp3_path):
            await msg.edit_text(f"MP3 file not found: {mp3_path}")
            return
        try:
            from telegram import InputFile

            with open(mp3_path, "rb") as f:
                input_file = InputFile(f, filename=os.path.basename(mp3_path))
                await update.message.reply_audio(audio=input_file)
            await msg.delete()
        except Exception as e:
            await msg.edit_text(f"Failed to send audio file: {e}")
        finally:
            try:
                tmpdir = os.path.dirname(mp3_path)
                if tmpdir and os.path.exists(tmpdir):
                    shutil.rmtree(tmpdir)
            except Exception:
                pass
        return

    # Multiple files: send each MP3 individually
    try:
        from telegram import InputFile
        for idx, p in enumerate(mp3_paths, start=1):
            if not p or not os.path.isfile(p):
                try:
                    await update.message.reply_text(f"[{idx}/{len(mp3_paths)}] File missing or skipped: {p}")
                except Exception:
                    pass
                continue

            try:
                await update.message.reply_text(f"Sending [{idx}/{len(mp3_paths)}]: {os.path.basename(p)}")
                with open(p, "rb") as f:
                    await update.message.reply_audio(audio=InputFile(f, filename=os.path.basename(p)))
            except Exception:
                # fallback to document
                try:
                    with open(p, "rb") as f:
                        await update.message.reply_document(document=InputFile(f, filename=os.path.basename(p)), caption=f"{os.path.basename(p)}")
                except Exception:
                    pass
                    # try:
                    #     await update.message.reply_text(f"Failed to send file: {os.path.basename(p)}")
                    # except Exception:
                    #     pass

            # Small delay to avoid hitting rate limits
            try:
                await asyncio.sleep(0.5)
            except Exception:
                pass

            # do not cleanup here; we'll remove the playlist tempdir after sending all files
            pass

        try:
            await msg.delete()
        except Exception:
            pass

        # cleanup playlist tempdir if available
        try:
            if "playlist_tmpdir" in locals() and playlist_tmpdir and os.path.exists(playlist_tmpdir):
                shutil.rmtree(playlist_tmpdir)
        except Exception:
            pass

    except Exception as e:
        await msg.edit_text(f"Failed to send playlist files: {e}")


# Main entry
if __name__ == '__main__':
    if not TOKEN:
        # helpful diagnostics without revealing the token
        dotenv_path = Path(__file__).with_name('.env')
        print("TELEGRAM_TOKEN environment variable is not set. Exiting.")
        print("Hints:")
        print(f" - Set TELEGRAM_TOKEN in the environment before starting the bot.")
        print(f" - Or create a .env file at: {dotenv_path} with the line: TELEGRAM_TOKEN=your_token_here")
        print(f" - .env present: {dotenv_path.exists()}")
        raise SystemExit(1)

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("yt", yt_command))
    app.add_handler(CommandHandler("setcookies", setcookies_command))
    app.add_handler(CommandHandler("setcookies_paste", setcookies_paste_command))
    app.add_handler(CommandHandler("cleancookies", cleancookies_command))
    app.add_handler(CommandHandler("listcookies", listcookies_command))
    app.add_handler(CommandHandler("listallcookies", listallcookies_command))
    # Text handler to capture the URL after prompting the user
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    # Document handler for cookie files (cookies.txt)
    app.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, document_handler))

    # Webhook mode for Render (expects TELEGRAM_WEBHOOK_BASE and PORT)
    webhook_base = os.environ.get("TELEGRAM_WEBHOOK_BASE")
    port = int(os.environ.get("PORT", "8000"))
    if not webhook_base:
        print("TELEGRAM_WEBHOOK_BASE not set. Set it to https://<your-service>.onrender.com")
        raise SystemExit(1)

    # Use a secret path derived from token to avoid exposing token in URL
    import hashlib
    secret_path = hashlib.sha256(TOKEN.encode('utf8')).hexdigest()[:40]
    webhook_path = f"/{secret_path}"
    webhook_url = webhook_base.rstrip('/') + webhook_path

    print(f"Starting webhook on 0.0.0.0:{port}, webhook_url={webhook_url}")
    # cleanup expired cookie files at startup
    try:
        startup_cleanup_cookie_files()
    except Exception:
        pass
    # run_webhook will set the webhook with Telegram
    app.run_webhook(listen='0.0.0.0', port=port, url_path=webhook_path, webhook_url=webhook_url)