import os
import tempfile
import asyncio
import shutil
import subprocess
import json
from typing import Optional
from pathlib import Path
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TOKEN:
    print("ERROR: TELEGRAM_TOKEN environment variable not set!")
    exit(1)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎵 **YouTube to MP3 Bot (Shell Version)**\n\n"
        "Use /yt <youtube_url> to download audio as MP3.\n"
        "This version uses shell commands for maximum compatibility."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "**Commands:**\n"
        "• `/yt <url>` - Download audio from YouTube URL\n"
        "• `/yt` - Bot will ask for URL\n\n"
        "**Features:**\n"
        "• Works with single videos and playlists\n"
        "• Uses shell yt-dlp commands for reliability\n"
        "• Supports age-restricted content with cookies"
    )

async def download_with_shell(url: str, progress_msg: Optional[object] = None, is_playlist: bool = False) -> tuple[list, str]:
    """Download using shell yt-dlp commands for maximum compatibility."""
    tmpdir = tempfile.mkdtemp(prefix="yt_shell_")

    # Determine output template based on type
    if is_playlist:
        outtmpl = os.path.join(tmpdir, "%(playlist_index)s - %(title)s.%(ext)s")
        playlist_args = []
    else:
        outtmpl = os.path.join(tmpdir, "%(title)s.%(ext)s")
        playlist_args = ["--no-playlist"]

    # Build yt-dlp command
    cmd = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "192",
        "--output", outtmpl,
        "--no-warnings",
        "--ignore-errors",  # Continue on errors for playlists
    ] + playlist_args + [
        # JavaScript runtime options
        "--js-runtimes", "node:deno:phantomjs",
        url
    ]

    # Check for cookies in environment
    cookie_file = os.environ.get("YTDLP_COOKIES_FILE")
    if cookie_file and os.path.exists(cookie_file):
        cmd.extend(["--cookies", cookie_file])

    try:
        if progress_msg:
            await progress_msg.edit_text("🔄 Starting download...")

        # Run yt-dlp command
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=tmpdir
        )

        if progress_msg:
            await progress_msg.edit_text("📥 Downloading and converting to MP3...")

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise Exception(f"yt-dlp failed: {error_msg}")

        # Find generated MP3 files
        mp3_files = []
        for root, dirs, files in os.walk(tmpdir):
            for file in files:
                if file.endswith('.mp3'):
                    mp3_files.append(os.path.join(root, file))

        # Sort playlist files by index if present
        mp3_files.sort(key=lambda x: (
            int(os.path.basename(x).split(' - ')[0])
            if os.path.basename(x).split(' - ')[0].isdigit()
            else float('inf')
        ))

        if progress_msg:
            await progress_msg.edit_text(f"✅ Generated {len(mp3_files)} MP3 file(s)")

        return mp3_files, tmpdir

    except Exception as e:
        # Clean up on error
        try:
            shutil.rmtree(tmpdir)
        except:
            pass
        raise e

def is_playlist_url(url: str) -> bool:
    """Check if URL is a playlist."""
    return ('list=' in url and 'v=' not in url) or '/playlist' in url

async def yt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /yt command."""
    if context.args:
        url = context.args[0]
        await update.message.reply_text(f"🚀 Starting download from: {url}")
        await handle_download_and_send(update, context, url)
        return

    await update.message.reply_text("📝 Please send the YouTube URL:")
    context.user_data["awaiting_yt_url"] = True

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages."""
    if not update.message or not update.message.text:
        return

    if context.user_data.pop("awaiting_yt_url", False):
        url = update.message.text.strip()
        await update.message.reply_text(f"🚀 Starting download from: {url}")
        await handle_download_and_send(update, context, url)

async def handle_download_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Download and send files using shell commands."""
    msg = await update.message.reply_text("🔄 Preparing download...")

    try:
        # Check if it's a playlist
        is_playlist = is_playlist_url(url)
        if is_playlist:
            await msg.edit_text("📋 Playlist detected, downloading all items...")

        # Download using shell command
        mp3_files, tmpdir = await download_with_shell(url, msg, is_playlist)

        if not mp3_files:
            await msg.edit_text("❌ No MP3 files were generated.")
            return

        # Send files
        if len(mp3_files) == 1:
            # Single file
            await send_single_file(update, msg, mp3_files[0])
        else:
            # Multiple files
            await send_multiple_files(update, msg, mp3_files)

        # Cleanup
        try:
            shutil.rmtree(tmpdir)
        except:
            pass

    except Exception as e:
        error_text = str(e).lower()
        if "sign in" in error_text or "private" in error_text or "members-only" in error_text:
            await msg.edit_text(
                "🔒 **Authentication Required**\n\n"
                "This video requires login. To fix this:\n"
                "1. Export cookies.txt from your browser\n"
                "2. Set YTDLP_COOKIES_FILE environment variable\n"
                "3. Or contact the bot administrator\n\n"
                "The video may be private or age-restricted."
            )
        elif "javascript runtime" in error_text or "node" in error_text:
            await msg.edit_text("❌ Server needs JavaScript runtime (Node.js). Contact administrator.")
        else:
            await msg.edit_text(f"❌ Download failed: {e}")

async def send_single_file(update: Update, msg, mp3_path: str):
    """Send a single MP3 file."""
    try:
        from telegram import InputFile
        with open(mp3_path, "rb") as f:
            input_file = InputFile(f, filename=os.path.basename(mp3_path))
            await update.message.reply_audio(audio=input_file)
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Failed to send file: {e}")

async def send_multiple_files(update: Update, msg, mp3_files: list):
    """Send multiple MP3 files from a playlist."""
    try:
        from telegram import InputFile
        await msg.edit_text(f"📤 Sending {len(mp3_files)} files...")

        for idx, mp3_path in enumerate(mp3_files, 1):
            if not os.path.exists(mp3_path):
                await update.message.reply_text(f"⚠️ [{idx}/{len(mp3_files)}] File not found: {os.path.basename(mp3_path)}")
                continue

            try:
                await update.message.reply_text(f"📤 [{idx}/{len(mp3_files)}]: {os.path.basename(mp3_path)}")
                with open(mp3_path, "rb") as f:
                    await update.message.reply_audio(audio=InputFile(f, filename=os.path.basename(mp3_path)))
            except Exception:
                # Fallback to document
                try:
                    with open(mp3_path, "rb") as f:
                        await update.message.reply_document(
                            document=InputFile(f, filename=os.path.basename(mp3_path)),
                            caption=f"🎵 {os.path.basename(mp3_path)}"
                        )
                except Exception:
                    await update.message.reply_text(f"❌ Failed to send: {os.path.basename(mp3_path)}")

            # Rate limiting
            await asyncio.sleep(0.5)

        await msg.delete()

    except Exception as e:
        await msg.edit_text(f"❌ Failed to send files: {e}")

# Check dependencies at startup
def check_shell_dependencies():
    """Check if required shell commands are available."""
    deps = {'status': True, 'missing': []}

    # Check yt-dlp
    try:
        result = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ yt-dlp version: {result.stdout.strip()}")
        else:
            deps['status'] = False
            deps['missing'].append('yt-dlp')
    except FileNotFoundError:
        deps['status'] = False
        deps['missing'].append('yt-dlp')
        print("❌ yt-dlp not found")

    # Check ffmpeg
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ FFmpeg available")
        else:
            deps['status'] = False
            deps['missing'].append('ffmpeg')
    except FileNotFoundError:
        deps['status'] = False
        deps['missing'].append('ffmpeg')
        print("❌ FFmpeg not found")

    # Check JavaScript runtime
    js_found = False
    for runtime in ['node', 'deno']:
        try:
            result = subprocess.run([runtime, '--version'], capture_output=True, text=True)
            if result.returncode == 0:
                print(f"✅ JavaScript runtime available: {runtime}")
                js_found = True
                break
        except FileNotFoundError:
            continue

    if not js_found:
        deps['status'] = False
        deps['missing'].append('JavaScript runtime (node/deno)')
        print("❌ No JavaScript runtime found")

    return deps

if __name__ == '__main__':
    # Check dependencies
    deps = check_shell_dependencies()
    if not deps['status']:
        print(f"❌ Missing dependencies: {', '.join(deps['missing'])}")
        print("The bot may not work properly without these dependencies.")

    app = ApplicationBuilder().token(TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("yt", yt_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

    # Run bot
    webhook_base = os.environ.get("TELEGRAM_WEBHOOK_BASE")
    port = int(os.environ.get("PORT", "8000"))

    if webhook_base:
        # Webhook mode for Render
        import hashlib
        secret_path = hashlib.sha256(TOKEN.encode('utf8')).hexdigest()[:40]
        webhook_path = f"/{secret_path}"
        webhook_url = webhook_base.rstrip('/') + webhook_path
        print(f"🚀 Starting webhook mode on port {port}")
        app.run_webhook(listen='0.0.0.0', port=port, url_path=webhook_path, webhook_url=webhook_url)
    else:
        print("🚀 Starting polling mode (development)")
        app.run_polling()