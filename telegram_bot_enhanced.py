import os
import tempfile
import asyncio
import shutil
import subprocess
import json
from typing import Optional
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler,
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
    keyboard = [
        [InlineKeyboardButton("📥 Download Video", callback_data="help_download")],
        [InlineKeyboardButton("🍪 Setup Cookies", callback_data="help_cookies")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help_general")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🎵 **YouTube to MP3 Bot**\n\n"
        "I can download audio from YouTube videos and playlists!\n\n"
        "Choose an option below to get started:",
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📱 Mobile Setup", callback_data="cookies_mobile")],
        [InlineKeyboardButton("💻 Desktop Setup", callback_data="cookies_desktop")],
        [InlineKeyboardButton("🔧 Advanced Setup", callback_data="cookies_advanced")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🍪 **Cookie Setup Guide**\n\n"
        "For age-restricted or private videos, you need to provide cookies.\n"
        "Choose your device type for specific instructions:",
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "help_download":
        await query.edit_message_text(
            "📥 **How to Download**\n\n"
            "**Single Video:**\n"
            "`/yt https://youtube.com/watch?v=VIDEO_ID`\n\n"
            "**Playlist:**\n"
            "`/yt https://youtube.com/playlist?list=PLAYLIST_ID`\n\n"
            "**Or just send:**\n"
            "`/yt` and I'll ask for the URL\n\n"
            "**Supported:** MP3 audio, any YouTube video/playlist"
        )

    elif query.data == "help_cookies":
        keyboard = [
            [InlineKeyboardButton("📱 Mobile", callback_data="cookies_mobile")],
            [InlineKeyboardButton("💻 Desktop", callback_data="cookies_desktop")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "🍪 **Cookie Setup**\n\n"
            "Cookies are needed for:\n"
            "• Age-restricted videos (18+)\n"
            "• Private/unlisted videos\n"
            "• Some region-locked content\n\n"
            "Choose your device:",
            reply_markup=reply_markup
        )

    elif query.data == "cookies_mobile":
        await query.edit_message_text(
            "📱 **Mobile Cookie Setup**\n\n"
            "**Android (Chrome):**\n"
            "1. Install 'Cookie Editor' app\n"
            "2. Open YouTube in Chrome, login\n"
            "3. Open Cookie Editor → Export\n"
            "4. Send file to this bot using /setcookies\n\n"
            "**iPhone (Safari):**\n"
            "1. Use 'Web Inspector' in Settings\n"
            "2. Or use desktop method instead\n\n"
            "**Easier:** Use desktop browser and send file to phone"
        )

    elif query.data == "cookies_desktop":
        await query.edit_message_text(
            "💻 **Desktop Cookie Setup**\n\n"
            "**Chrome:**\n"
            "1. Install 'Get cookies.txt LOCALLY' extension\n"
            "2. Go to youtube.com, login to your account\n"
            "3. Click extension icon → Export\n"
            "4. Save as cookies.txt\n"
            "5. Upload here: /setcookies\n\n"
            "**Firefox:**\n"
            "1. Install 'cookies.txt' addon\n"
            "2. Go to youtube.com, login\n"
            "3. Click addon → Export cookies\n"
            "4. Upload here: /setcookies"
        )

    elif query.data == "auto_cookies":
        await auto_cookie_setup(update, context)

    elif query.data == "help_upload":
        await query.edit_message_text(
            "📁 **Upload Cookie File**\n\n"
            "1. Export cookies.txt from your browser\n"
            "2. Send the file to this chat as a document\n"
            "3. I'll automatically save and test it\n\n"
            "**Supported formats:** cookies.txt (Netscape format)"
        )

    elif query.data == "help_paste":
        await query.edit_message_text(
            "📋 **Paste Cookie Contents**\n\n"
            "1. Use /setcookies_paste command\n"
            "2. Paste your raw cookie contents\n"
            "3. I'll save them for this chat\n\n"
            "**Note:** Only use this in private chats for security"
        )
        await query.edit_message_text(
            "🔧 **Advanced Cookie Setup**\n\n"
            "**Method 1: File Upload**\n"
            "• Use /setcookies command\n"
            "• Upload your cookies.txt file\n\n"
            "**Method 2: Paste Contents**\n"
            "• Use /setcookies_paste\n"
            "• Paste raw cookie data\n\n"
            "**Method 3: Developer Tools**\n"
            "• F12 → Application → Cookies\n"
            "• Copy all youtube.com cookies\n"
            "• Format as Netscape cookies.txt"
        )

async def yt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        url = context.args[0]
        await update.message.reply_text(f"🚀 Starting download from: {url}")
        await handle_download_and_send(update, context, url)
        return

    await update.message.reply_text("📝 Please send the YouTube URL:")
    context.user_data["awaiting_yt_url"] = True

async def smart_download(url: str, progress_msg: Optional[object] = None, cookies_file: str = None) -> tuple[list, str]:
    """Smart download with automatic fallback strategies."""
    tmpdir = tempfile.mkdtemp(prefix="yt_smart_")

    # Strategy 1: Try with cookies if available
    cmd_base = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "192",
        "--output", os.path.join(tmpdir, "%(title)s.%(ext)s"),
        "--no-warnings",
        "--ignore-errors"
    ]

    strategies = []

    # Add cookies if available
    if cookies_file and os.path.exists(cookies_file):
        strategies.append(cmd_base + ["--cookies", cookies_file, url])

    # Fallback strategies
    strategies.extend([
        cmd_base + [url],  # Without cookies
        cmd_base + ["--age-limit", "0", url],  # Skip age check
        cmd_base + ["--skip-download", "--write-info-json", url]  # Info only
    ])

    last_error = None

    for i, cmd in enumerate(strategies):
        try:
            if progress_msg:
                await progress_msg.edit_text(f"🔄 Trying download method {i+1}/{len(strategies)}...")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tmpdir
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                # Success! Find MP3 files
                mp3_files = []
                for root, dirs, files in os.walk(tmpdir):
                    for file in files:
                        if file.endswith('.mp3'):
                            mp3_files.append(os.path.join(root, file))

                if mp3_files:
                    return mp3_files, tmpdir
            else:
                last_error = stderr.decode() if stderr else stdout.decode()

        except Exception as e:
            last_error = str(e)
            continue

    # All strategies failed
    shutil.rmtree(tmpdir)
    raise Exception(f"All download strategies failed. Last error: {last_error}")

async def handle_download_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Enhanced download handler with smart error recovery."""
    msg = await update.message.reply_text("🔄 Preparing download...")

    try:
        # Get cookies if available for this chat
        cookies_file = context.chat_data.get("cookiefile")

        # Try smart download
        mp3_files, tmpdir = await smart_download(url, msg, cookies_file)

        if not mp3_files:
            await msg.edit_text("❌ No audio files were generated.")
            return

        # Send files
        if len(mp3_files) == 1:
            await send_single_file(update, msg, mp3_files[0])
        else:
            await send_multiple_files(update, msg, mp3_files)

        # Cleanup
        try:
            shutil.rmtree(tmpdir)
        except:
            pass

    except Exception as e:
        error_text = str(e).lower()

        # Smart error handling with actionable solutions
        if any(phrase in error_text for phrase in ["sign in", "private", "age", "restricted"]):
            keyboard = [
                [InlineKeyboardButton("📱 Mobile Setup", callback_data="cookies_mobile")],
                [InlineKeyboardButton("💻 Desktop Setup", callback_data="cookies_desktop")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await msg.edit_text(
                "🔒 **Authentication Required**\n\n"
                "This video needs cookies for access.\n"
                "Choose your device for setup instructions:",
                reply_markup=reply_markup
            )
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
                continue

            try:
                await update.message.reply_text(f"📤 [{idx}/{len(mp3_files)}]: {os.path.basename(mp3_path)}")
                with open(mp3_path, "rb") as f:
                    await update.message.reply_audio(audio=InputFile(f, filename=os.path.basename(mp3_path)))
            except Exception:
                try:
                    with open(mp3_path, "rb") as f:
                        await update.message.reply_document(
                            document=InputFile(f, filename=os.path.basename(mp3_path)),
                            caption=f"🎵 {os.path.basename(mp3_path)}"
                        )
                except Exception:
                    await update.message.reply_text(f"❌ Failed to send: {os.path.basename(mp3_path)}")

            await asyncio.sleep(0.5)

        await msg.delete()

    except Exception as e:
        await msg.edit_text(f"❌ Failed to send files: {e}")

async def setcookies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📁 Upload File", callback_data="help_upload")],
        [InlineKeyboardButton("📋 Paste Text", callback_data="help_paste")],
        [InlineKeyboardButton("🤖 Auto-Setup Guide", callback_data="auto_cookies")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🍪 **Cookie Setup Methods**\n\n"
        "Choose how you want to provide cookies:",
        reply_markup=reply_markup
    )

async def auto_cookie_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate personalized cookie setup instructions."""
    try:
        # Call the cookie automation script to generate instructions
        process = await asyncio.create_subprocess_exec(
            "./cookie-automation.sh", "export",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            instructions = stdout.decode()
            await update.message.reply_text(f"```\n{instructions}\n```", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Could not generate auto-setup instructions")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded cookie files."""
    if not update.message or not update.message.document:
        return

    doc = update.message.document
    fname = doc.file_name or ""

    if "cookie" not in fname.lower() and "cookies" not in fname.lower():
        await update.message.reply_text("📄 File doesn't appear to be a cookies file. Upload your browser's exported cookies.txt file.")
        return

    try:
        f = await doc.get_file()
        tmp_cf = os.path.join(tempfile.gettempdir(), f"ytdlp_cookies_chat_{update.effective_chat.id}.txt")
        await f.download_to_drive(tmp_cf)
        context.chat_data["cookiefile"] = tmp_cf

        # Test the cookies using the automation script
        test_result = await test_cookies_file(tmp_cf)
        if test_result:
            await update.message.reply_text("✅ Cookie file saved and tested successfully! Ready for downloads.")
        else:
            await update.message.reply_text("⚠️ Cookie file saved but may not be working. Try downloading to test.")

    except Exception as e:
        await update.message.reply_text(f"❌ Failed to save cookie file: {e}")

async def test_cookies_file(cookies_path: str) -> bool:
    """Test if cookies file works using the automation script."""
    try:
        # Create a temporary script to test cookies
        test_cmd = [
            "yt-dlp", "--cookies", cookies_path, "--simulate",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        ]

        process = await asyncio.create_subprocess_exec(
            *test_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()
        return process.returncode == 0

    except Exception:
        return False

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    if context.user_data.pop("awaiting_yt_url", False):
        url = update.message.text.strip()
        await update.message.reply_text(f"🚀 Starting download from: {url}")
        await handle_download_and_send(update, context, url)

# Main application setup
if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("yt", yt_command))
    app.add_handler(CommandHandler("setcookies", setcookies_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    app.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, document_handler))

    # Run bot
    webhook_base = os.environ.get("TELEGRAM_WEBHOOK_BASE")
    port = int(os.environ.get("PORT", "8000"))

    if webhook_base:
        import hashlib
        secret_path = hashlib.sha256(TOKEN.encode('utf8')).hexdigest()[:40]
        webhook_path = f"/{secret_path}"
        webhook_url = webhook_base.rstrip('/') + webhook_path
        print(f"🚀 Starting enhanced bot with webhook on port {port}")
        app.run_webhook(listen='0.0.0.0', port=port, url_path=webhook_path, webhook_url=webhook_url)
    else:
        print("🚀 Starting enhanced bot in polling mode")
        app.run_polling()