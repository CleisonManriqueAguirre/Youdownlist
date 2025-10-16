""" from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = "8261552939:AAEaULq4-bAWT-CBWis7EJifhyIU4OwChM0"

# Command: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello Cleison! I’m your new Telegram bot!")

# Command: /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Type /start to begin or /help to see this again.")

# Main entry
if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    print("Bot is running...")
    app.run_polling()
 """


import os
import tempfile
import asyncio
import shutil
import time
from typing import Optional
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
TOKEN = "8261552939:AAEaULq4-bAWT-CBWis7EJifhyIU4OwChM0"

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
        # Pass the message object so the downloader can update progress
        mp3_path = await download_audio_mp3(url, progress_msg=msg, loop=loop)
    except Exception as e:
        await msg.edit_text(f"Download failed: {e}")
        return

    # Verify the file exists and is readable
    if not mp3_path or not os.path.isfile(mp3_path):
        await msg.edit_text(f"Download finished but MP3 file not found. Path: {mp3_path}")
        # Attempt to cleanup any temp dir if present
        if mp3_path:
            try:
                tmpdir = os.path.dirname(mp3_path)
                if os.path.exists(tmpdir):
                    shutil.rmtree(tmpdir)
            except Exception:
                pass
        return

    try:
        # Use telegram InputFile for robust upload
        from telegram import InputFile

        with open(mp3_path, "rb") as f:
            input_file = InputFile(f, filename=os.path.basename(mp3_path))
            await update.message.reply_audio(audio=input_file)
        await msg.delete()
    except Exception as e:
        # Provide detailed diagnostics to the user and try a document fallback
        import traceback as _tb
        tb = _tb.format_exc()
        try:
            size = os.path.getsize(mp3_path)
        except Exception:
            size = None

        diag = f"Failed to send audio file: {e}\nFile size: {size}\nTraceback:\n{tb[:1500]}"
        # Trim message length if too long
        try:
            await msg.edit_text(diag)
        except Exception:
            # If editing fails, send a new message
            try:
                await update.message.reply_text(diag)
            except Exception:
                pass

        # Try sending as a generic document (fallback)
        try:
            from telegram import InputFile
            with open(mp3_path, "rb") as f2:
                input_file = InputFile(f2, filename=os.path.basename(mp3_path))
                await update.message.reply_document(document=input_file, filename=os.path.basename(mp3_path), caption="MP3 file (fallback)")
            try:
                await msg.delete()
            except Exception:
                pass
        except Exception as e2:
            # Report the secondary failure
            try:
                await update.message.reply_text(f"Also failed to send as document: {e2}")
            except Exception:
                pass
    finally:
        # Cleanup the temporary directory containing the mp3
        try:
            tmpdir = os.path.dirname(mp3_path)
            if tmpdir and os.path.exists(tmpdir):
                shutil.rmtree(tmpdir)
        except Exception:
            # Non-fatal cleanup failure
            pass


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