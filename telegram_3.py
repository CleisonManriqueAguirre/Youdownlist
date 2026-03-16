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


def validate_cookie_file(path: str) -> tuple[bool, str]:
    """Validate that `path` points to a Netscape/Mozilla cookies.txt file.

    Returns (True, "") if valid. Otherwise (False, reason).
    The function also normalizes line endings to LF in-place when possible.
    """
    try:
        if not os.path.exists(path):
            return False, "file does not exist"
        # Read raw bytes and normalize newlines
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            text = data.decode("utf8")
        except Exception:
            try:
                text = data.decode("latin-1")
            except Exception:
                return False, "unable to decode file as text"
        # normalize CRLF and CR to LF
        norm = text.replace('\r\n', '\n').replace('\r', '\n')
        # write back normalized content
        try:
            with open(path, "w", encoding="utf8", newline='\n') as fh:
                fh.write(norm)
        except Exception:
            # non-fatal, continue validation with normalized string
            pass

        # examine first non-empty line
        for line in norm.split('\n'):
            s = line.strip()
            if not s:
                continue
            first = s
            break
        else:
            return False, "file is empty"

        if not (first.startswith("# HTTP Cookie File") or first.startswith("# Netscape HTTP Cookie File") or first.startswith("# Netscape")):
            # Not having the header is not always fatal: check for tab-separated lines
            sample_lines = [l for l in norm.split('\n') if l.strip() and not l.strip().startswith('#')][:10]
            if not sample_lines:
                return False, "no cookie entries found"
            good = False
            for ln in sample_lines:
                parts = ln.split('\t')
                if len(parts) >= 6:
                    good = True
                    break
            if not good:
                return False, "file doesn't look like Netscape cookies.txt format (no tab-separated cookie lines)"

        # quick sanity: at least one non-comment tab-separated line
        found = False
        for ln in norm.split('\n'):
            ln = ln.strip()
            if not ln or ln.startswith('#'):
                continue
            if '\t' in ln:
                found = True
                break
        if not found:
            return False, "no cookie lines found"

        return True, ""
    except Exception as e:
        return False, f"validation error: {e}"


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
        # Try to bypass geo-blocking and 403s
        "geo_bypass": True,
        # Browser-like headers to avoid some blocks
        "http_headers": {
            "User-Agent": os.environ.get("YTDLP_USER_AGENT", 
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-us,en;q=0.5",
            "Sec-Fetch-Mode": "navigate",
        },
        # Use extractor args to request a different YouTube player client which can bypass some 403/player issues
        "extractor_args": {"youtube": {"player-client": "web_embedded,web,tv"}},
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
        # Try to bypass geo-blocking and 403s
        "geo_bypass": True,
        # Browser-like headers to avoid some blocks
        "http_headers": {
            "User-Agent": os.environ.get("YTDLP_USER_AGENT", 
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-us,en;q=0.5",
            "Sec-Fetch-Mode": "navigate",
        },
        # Use extractor args to request a different YouTube player client which can bypass some 403/player issues
        "extractor_args": {"youtube": {"player-client": "web_embedded,web,tv"}},
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
    if not update.effective_message:
        return

    # If user provided the URL as argument, use it directly
    if context.args:
        url = context.args[0]
        await update.effective_message.reply_text(f"Downloading audio from: {url} (this may take a while)...")
        await handle_download_and_send(update, context, url)
        return

    # Otherwise prompt the user to send the URL
    await update.effective_message.reply_text("Please send the YouTube URL for the song you want to download as MP3.")
    # Set a flag in user_data so the next text message is treated as the URL
    context.user_data["awaiting_yt_url"] = True


async def setcookies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Instructional command asking user to upload a cookies.txt file or paste cookies as a message."""
    if not update.effective_message:
        return
    await update.effective_message.reply_text(
        "To set cookies, upload a cookies.txt file exported from your browser (File -> Send as document), or paste the cookie contents as a message after running /setcookies_paste.\n"
        "This will be stored only for this chat. To remove, use /cleancookies."
    )


async def setcookies_paste_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a state where the next message text will be treated as raw cookie contents."""
    if not update.effective_message:
        return
    context.user_data["awaiting_cookies_paste"] = True
    await update.effective_message.reply_text("Please paste your cookies.txt contents in the next message. The data will be stored temporarily for this chat.")


async def cleancookies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove stored cookie file for this chat."""
    if not update.effective_message:
        return
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
        await update.effective_message.reply_text("Cookies removed for this chat.")
    else:
        await update.effective_message.reply_text("No cookies were stored for this chat.")


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded document; if it's named like cookies.txt store it for the chat."""
    if not update.effective_message or not update.message or not update.message.document:
        return
    doc = update.message.document
    fname = doc.file_name or ""
    # Only accept likely cookie files to avoid storing arbitrary uploads
    if "cookie" not in fname.lower() and "cookies" not in fname.lower():
        await update.effective_message.reply_text("Uploaded file doesn't look like a cookies file. If you want to set cookies, upload your exported cookies.txt file from the browser.")
        return

    try:
        f = await doc.get_file()
        tmp_cf = os.path.join(tempfile.gettempdir(), f"ytdlp_cookies_chat_{update.effective_chat.id}.txt")
        await f.download_to_drive(tmp_cf)
        # validate and normalize the saved cookie file
        try:
            ok, reason = validate_cookie_file(tmp_cf)
        except Exception:
            ok, reason = False, "validation failed"
        if ok:
            context.chat_data["cookiefile"] = tmp_cf
            await update.effective_message.reply_text("Cookie file saved for this chat and looks valid. It will be used for future downloads in this chat.")
        else:
            # keep the file for inspection but warn the user
            context.chat_data["cookiefile"] = tmp_cf
            await update.effective_message.reply_text(f"Cookie file saved but may be invalid: {reason}\nIf this file was exported from your browser, make sure it is in Netscape/Mozilla cookies.txt format.")
    except Exception as e:
        await update.effective_message.reply_text(f"Failed to save cookie file: {e}")


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain text messages. If we previously asked for a URL or cookie paste, treat accordingly."""
    if not update.effective_message or not update.message or not update.message.text:
        return

    # Handle pasted cookie contents
    if context.user_data.pop("awaiting_cookies_paste", False):
        contents = update.message.text
        try:
            tmp_cf = os.path.join(tempfile.gettempdir(), f"ytdlp_cookies_chat_{update.effective_chat.id}.txt")
            # normalize newlines to LF and write
            norm = contents.replace('\r\n', '\n').replace('\r', '\n')
            with open(tmp_cf, "w", encoding="utf8", newline='\n') as _cf:
                _cf.write(norm)
            # validate file
            try:
                ok, reason = validate_cookie_file(tmp_cf)
            except Exception:
                ok, reason = False, "validation failed"
            context.chat_data["cookiefile"] = tmp_cf
            context.chat_data["cookie_contents"] = contents
            if ok:
                await update.effective_message.reply_text("Cookies stored for this chat and look valid. They will be used for future downloads.")
            else:
                await update.effective_message.reply_text(f"Cookies stored but may be invalid: {reason}\nMake sure the file is Netscape format (first line '# Netscape HTTP Cookie File').")
        except Exception as e:
            await update.effective_message.reply_text(f"Failed to store cookies: {e}")
        return

    if context.user_data.pop("awaiting_yt_url", False):
        url = update.message.text.strip()
        await update.effective_message.reply_text(f"Received URL: {url}\nStarting download...")
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
    if not update.effective_message:
        return
    msg = await update.effective_message.reply_text("Preparing download...")
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
        err_text = str(e)
        try:
            # Common error patterns and their help messages
            if "HTTP Error 403" in err_text:
                help_msg = (
                    "Download failed with HTTP 403 (Forbidden). This usually means:\n"
                    "1. The video requires login/cookies, or\n"
                    "2. YouTube is blocking our requests\n\n"
                    "Try these fixes:\n"
                    "1. Set cookies:\n"
                    "   • /setcookies - upload your cookies.txt file\n"
                    "   • /setcookies_paste - paste cookie contents\n"
                    "2. Export cookies from Chrome/Firefox:\n"
                    "   See: https://github.com/yt-dlp/yt-dlp#how-do-i-pass-cookies-to-yt-dlp\n"
                    "3. Try setting a custom User-Agent:\n"
                    "   • PowerShell: $env:YTDLP_USER_AGENT='your-chrome-ua-here'\n\n"
                    "For private/age-restricted videos, cookies are required."
                )
                await msg.edit_text(help_msg)
                return
            elif "Sign in to confirm you\u2019re not a bot" in err_text or "--cookies-from-browser" in err_text or "--cookies" in err_text:
                help_msg = (
                    "This video requires you to be signed in.\n\n"
                    "Quick fix: Use /setcookies to upload your cookies.txt file.\n\n"
                    "How to get cookies:\n"
                    "1. Install the 'Get cookies.txt' extension in Chrome\n"
                    "2. Go to YouTube and ensure you're logged in\n"
                    "3. Click the extension icon → Export\n"
                    "4. Send the cookies.txt file here using /setcookies\n\n"
                    "For privacy: Use /setcookies_paste in private chats only."
                )
                await msg.edit_text(help_msg)
                return
            else:
                await msg.edit_text(f"Download failed: {e}")
                return
        except Exception:
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


def _make_diag_logger():
    buf = []
    class Logger:
        def debug(self, msg):
            try:
                buf.append("DEBUG: " + str(msg))
            except Exception:
                pass
        def info(self, msg):
            try:
                buf.append("INFO: " + str(msg))
            except Exception:
                pass
        def warning(self, msg):
            try:
                buf.append("WARN: " + str(msg))
            except Exception:
                pass
        def error(self, msg):
            try:
                buf.append("ERROR: " + str(msg))
            except Exception:
                pass
    return buf, Logger()


def run_yt_dlp_diagnostic(url: str, cookie_cfg: Optional[str] = None) -> str:
    """Run a quick yt-dlp diagnostic (no file download) and return captured logs and error.

    This runs synchronously and is safe to call via run_in_executor.
    """
    buf, logger = _make_diag_logger()
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": False,
        "logger": logger,
        "geo_bypass": True,
        "http_headers": {
            "User-Agent": os.environ.get("YTDLP_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
            "Referer": "https://www.youtube.com/",
        },
        "extractor_args": {"youtube": {"player-client": "web_embedded,web,tv"}},
    }
    if cookie_cfg and os.path.exists(cookie_cfg):
        ydl_opts["cookiefile"] = cookie_cfg
    # env cookie contents (raw) support
    if cookie_cfg and not os.path.exists(cookie_cfg) and cookie_cfg.strip():
        # write temp cookie file
        try:
            tmp_cf = os.path.join(tempfile.gettempdir(), "ytdlp_diag_cookies.txt")
            with open(tmp_cf, "w", encoding="utf8", newline='\n') as fh:
                fh.write(cookie_cfg)
            ydl_opts["cookiefile"] = tmp_cf
        except Exception:
            pass

    proxy = os.environ.get("YTDLP_PROXY")
    if proxy:
        ydl_opts["proxy"] = proxy

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # extract without downloading to reproduce auth/player errors
            info = ydl.extract_info(url, download=False)
            buf.append("SUCCESS: extracted info for id=" + str(info.get("id")))
    except Exception as e:
        buf.append("EXCEPTION: " + str(e))

    # return joined log (truncate later by caller)
    return "\n".join(buf)


async def yt_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run a quick diagnostic using yt-dlp with the same options the bot uses.

    Usage: /yt_test <url>
    """
    if not update.effective_message:
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /yt_test <url>")
        return
    url = context.args[0]
    await update.effective_message.reply_text("Running yt-dlp diagnostic (no download). This may take a few seconds...")
    # prefer per-chat cookie file if present
    cookie_file = context.chat_data.get("cookiefile") or os.environ.get("YTDLP_COOKIES_FILE") or os.environ.get("YTDLP_COOKIES")
    loop = asyncio.get_event_loop()
    try:
        out = await loop.run_in_executor(None, run_yt_dlp_diagnostic, url, cookie_file)
    except Exception as e:
        out = "diagnostic failed: " + str(e)
    # Telegram messages have size limits; truncate to reasonable length
    max_len = 3800
    if len(out) > max_len:
        out = out[:max_len] + "\n...[truncated]"
    try:
        await update.effective_message.reply_text(f"Diagnostic output:\n\n{out}")
    except Exception:
        pass
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
    # Text handler to capture the URL after prompting the user
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    # Document handler for cookie files (cookies.txt)
    app.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, document_handler))

    print("Starting bot in polling mode... Press Ctrl+C to stop.")
    app.run_polling()