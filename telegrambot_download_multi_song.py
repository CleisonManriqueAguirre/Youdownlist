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
try:
    # local import; if python-dotenv isn't installed this will silently pass
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# Read the token from the TELEGRAM_TOKEN environment variable
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


async def download_audio_mp3(url: str, progress_msg: Optional[object] = None, loop: Optional[asyncio.AbstractEventLoop] = None) -> str:
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


async def download_playlist_mp3(url: str, progress_msg: Optional[object] = None, loop: Optional[asyncio.AbstractEventLoop] = None, max_items: int = 50) -> tuple[list, str]:
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
            paths, playlist_tmpdir = await download_playlist_mp3(url, progress_msg=msg, loop=loop)
            mp3_paths = paths
        else:
            # Pass the message object so the downloader can update progress
            mp3_path = await download_audio_mp3(url, progress_msg=msg, loop=loop)
            mp3_paths = [mp3_path] if mp3_path else []
    except Exception as e:
        await msg.edit_text(f"Download failed: {e}")
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
        print("TELEGRAM_TOKEN environment variable is not set. Exiting.")
        raise SystemExit(1)

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("yt", yt_command))
    # Text handler to capture the URL after prompting the user
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

    print("Bot is running...")
    app.run_polling()