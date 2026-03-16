import os
import tempfile
import asyncio
import shutil
import time
import glob
import urllib.parse
from typing import Optional, List
from pathlib import Path
import subprocess
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
import base64
import urllib.request
import tempfile as _tempfile

# Load environment variables from .env file if present
from pathlib import Path
_DOTENV_PATH = Path(__file__).with_name('.env')
try:
    from dotenv import load_dotenv  # type: ignore
    if _DOTENV_PATH.exists():
        load_dotenv(dotenv_path=str(_DOTENV_PATH))
    else:
        load_dotenv()
except Exception:
    pass

# SECURITY: Read the token from environment variable only
TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TOKEN:
    print("ERROR: TELEGRAM_TOKEN environment variable not set!")
    print("Please set it in your .env file or environment variables")
    exit(1)

# Cookie TTL in days (0 disables expiry). Defaults to 7 days.
COOKIE_TTL_DAYS = int(os.environ.get("YTDLP_COOKIE_TTL_DAYS", "7"))

# Optional owner id for admin commands (list all cookies)
try:
    BOT_OWNER_ID = int(os.environ.get("BOT_OWNER_ID")) if os.environ.get("BOT_OWNER_ID") else None
except Exception:
    BOT_OWNER_ID = None

def check_dependencies():
    """Check if required dependencies are available."""
    dependencies = {'status': True, 'missing': []}

    # Check for JavaScript runtime (required for yt-dlp)
    js_runtimes = ['node', 'deno', 'phantomjs']
    js_available = False
    for runtime in js_runtimes:
        try:
            subprocess.run([runtime, '--version'], capture_output=True, check=True)
            js_available = True
            print(f"JavaScript runtime found: {runtime}")
            break
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    if not js_available:
        dependencies['status'] = False
        dependencies['missing'].append('JavaScript runtime (node, deno, or phantomjs)')
        print("WARNING: No JavaScript runtime found! This may cause YouTube extraction failures.")
        print("Consider installing Node.js or deno for your deployment.")

    # Check for FFmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("FFmpeg found")
    except (subprocess.CalledProcessError, FileNotFoundError):
        dependencies['status'] = False
        dependencies['missing'].append('FFmpeg')
        print("WARNING: FFmpeg not found! Audio conversion may fail.")

    return dependencies

def log_cookie_info():
    """Print a non-sensitive summary of cookie-related env vars to stdout (visible in Render logs)."""
    cfile = os.environ.get("YTDLP_COOKIES_FILE")
    cval = os.environ.get("YTDLP_COOKIES")
    if cfile:
        try:
            exists = os.path.exists(cfile)
            size = os.path.getsize(cfile) if exists else None
            print(f"YTDLP_COOKIES_FILE={cfile} (exists={exists}, size={size})")
        except Exception:
            print(f"YTDLP_COOKIES_FILE={cfile} (exists=? )")
    if cval:
        try:
            print(f"YTDLP_COOKIES present: length={len(cval)} chars")
        except Exception:
            print("YTDLP_COOKIES present")
    if not cfile and not cval:
        print("No YTDLP cookies configured (YTDLP_COOKIES_FILE or YTDLP_COOKIES).")

# Support base64-encoded cookies in env (helpful for Render's UI)
_b64 = os.environ.get("YTDLP_COOKIES_B64")
if _b64:
    try:
        decoded = base64.b64decode(_b64).decode("utf8")
        os.environ["YTDLP_COOKIES"] = decoded
    except Exception as _e:
        print(f"Failed to decode YTDLP_COOKIES_B64: {_e}")

def fetch_cookies_from_url():
    """If YTDLP_COOKIES_URL is set, download it (supports optional bearer token) and save to YTDLP_COOKIES_FILE."""
    url = os.environ.get("YTDLP_COOKIES_URL")
    if not url:
        return
    dest = os.environ.get("YTDLP_COOKIES_FILE") or "/run/secrets/ytdlp_cookies.txt"
    token = os.environ.get("YTDLP_COOKIES_URL_TOKEN")
    try:
        req = urllib.request.Request(url)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                print(f"Failed to download cookies from URL: HTTP {resp.status}")
                return
            data = resp.read()
        dest_dir = os.path.dirname(dest)
        if dest_dir and not os.path.exists(dest_dir):
            os.makedirs(dest_dir, exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(data)
        os.environ["YTDLP_COOKIES_FILE"] = dest
        print(f"Downloaded cookies from URL to {dest} (size={len(data)} bytes)")
    except Exception as e:
        print(f"Error fetching cookies URL: {e}")

# Command: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hello! Use /yt <youtube_url> or send /yt and then reply with the YouTube URL to download the audio as MP3.\n\n"
        "📌 For private/age-restricted videos, you may need to set cookies using /setcookies"
    )

# Command: /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎵 **YouTube to MP3 Bot**\n\n"
        "**Commands:**\n"
        "• `/yt <url>` - Download audio from YouTube URL\n"
        "• `/yt` - Bot will ask for URL\n"
        "• `/setcookies` - Upload cookies.txt file for private videos\n"
        "• `/setcookies_paste` - Paste cookie contents\n"
        "• `/cleancookies` - Remove stored cookies\n"
        "• `/listcookies` - Check stored cookies\n\n"
        "**Supports:** Single videos and playlists!\n"
        "**Note:** For age-restricted or private videos, you may need to provide cookies."
    )

async def download_audio_mp3(url: str, progress_msg: Optional[object] = None, loop: Optional[asyncio.AbstractEventLoop] = None, cookie_file: Optional[str] = None) -> str:
    """Download audio from url using yt_dlp and return path to the MP3 file with enhanced error handling."""
    tmpdir = tempfile.mkdtemp(prefix="ytmp_")
    outtmpl = os.path.join(tmpdir, "%(title)s.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "playlist_items": "1",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
        # Add JavaScript runtime support
        "js_runtimes": ["node", "deno", "phantomjs"],
        # Add more robust extraction options
        "extractor_retries": 3,
        "fragment_retries": 3,
        # Skip unavailable fragments
        "skip_unavailable_fragments": True,
    }

    # Handle cookies
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
        # Check cookie expiry if TTL is set
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

    def sizeof_fmt(num, suffix="B"):
        for unit in ["", "K", "M", "G", "T"]:
            if abs(num) < 1024.0:
                return f"{num:3.1f}{unit}{suffix}"
            num /= 1024.0
        return f"{num:.1f}P{suffix}"

    def make_progress_hook():
        last_time = {"t": 0.0}
        state = {"finished": False, "entry_id": None}

        def progress_hook(d):
            try:
                status = d.get("status")
                info_dict = d.get("info_dict") or {}
                entry_id = info_dict.get("id") or d.get("filename") or None

                if state["finished"] and entry_id is not None and state["entry_id"] == entry_id and status == "downloading":
                    return
                now = time.time()
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
                    message = f"📥 Downloading: {pct_text} • {speed_text} • ETA {eta_text}"
                elif status == "finished":
                    state["finished"] = True
                    if entry_id is not None:
                        state["entry_id"] = entry_id
                    message = "🎵 Download finished, converting to MP3..."
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
            filename = ydl.prepare_filename(info)
            base, _ = os.path.splitext(filename)
            return base + ".mp3"

    mp3_path = await loop.run_in_executor(None, run_ydl)
    return mp3_path

def is_playlist_url(url: str) -> bool:
    """Return True if the URL is a playlist URL."""
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
    """Download a playlist and return (list of MP3 file paths, tempdir). Caps at max_items."""
    tmpdir = tempfile.mkdtemp(prefix="ytplaylist_")
    outtmpl = os.path.join(tmpdir, "%(playlist_index)s - %(title)s.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": False,
        "ignoreerrors": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
        "js_runtimes": ["node", "deno", "phantomjs"],
        "extractor_retries": 3,
        "fragment_retries": 3,
        "skip_unavailable_fragments": True,
    }

    # Handle cookies
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
                    message = f"📥 {prefix}Downloading: {pct_text} • {speed_text} • ETA {eta_text}"
                elif status == "finished":
                    prefix = f"[{p_index}/{p_count}] " if p_index and p_count else ""
                    message = f"🎵 {prefix}Downloaded item; converting to MP3..."
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
        raise RuntimeError(f"Playlist produced {len(mp3_files)} mp3 files, limit is {max_items}")

    # Ensure files are fully written
    stable = []
    for f in mp3_files:
        last_size = -1
        for _ in range(6):
            try:
                cur = os.path.getsize(f)
            except Exception:
                cur = -1
            if cur > 0 and cur == last_size:
                stable.append(f)
                break
            last_size = cur
            time.sleep(0.5)
        else:
            if os.path.exists(f) and os.path.getsize(f) > 0:
                stable.append(f)

    mp3_files = [f for f in mp3_files if f in stable]
    mp3_files.sort(key=lambda p: int(os.path.basename(p).split(" - ")[0]) if os.path.basename(p).split(" - ")[0].isdigit() else 10**9)

    return mp3_files, tmpdir

async def yt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /yt command."""
    if context.args:
        url = context.args[0]
        await update.message.reply_text(f"🚀 Starting download from: {url}")
        await handle_download_and_send(update, context, url)
        return

    await update.message.reply_text("📝 Please send the YouTube URL for the song you want to download as MP3.")
    context.user_data["awaiting_yt_url"] = True

async def setcookies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Instructional command asking user to upload a cookies.txt file or paste cookies as a message."""
    await update.message.reply_text(
        "🍪 **Cookie Management**\n\n"
        "To download private/age-restricted videos:\n"
        "1. Upload cookies.txt file (File → Send as document)\n"
        "2. OR use `/setcookies_paste` and paste cookie contents\n\n"
        "**Export cookies from browser:**\n"
        "• Chrome: Use 'Get cookies.txt' extension\n"
        "• Firefox: Use 'cookies.txt' add-on\n\n"
        "Use `/cleancookies` to remove stored cookies."
    )

async def setcookies_paste_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a state where the next message text will be treated as raw cookie contents."""
    context.user_data["awaiting_cookies_paste"] = True
    await update.message.reply_text("📋 Please paste your cookies.txt contents in the next message. The data will be stored temporarily for this chat.")

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
        await update.message.reply_text("✅ Cookies removed for this chat.")
    else:
        await update.message.reply_text("❌ No cookies were stored for this chat.")

async def listcookies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List whether this chat has stored cookies and their age."""
    cd = context.chat_data
    if cd.get("cookiefile") and os.path.exists(cd.get("cookiefile")):
        p = cd.get("cookiefile")
        try:
            mtime = os.path.getmtime(p)
            age = datetime.timedelta(seconds=(time.time() - mtime))
            await update.message.reply_text(f"🍪 Cookie file stored: {os.path.basename(p)} (age: {age})")
        except Exception:
            await update.message.reply_text(f"🍪 Cookie file stored: {os.path.basename(p)}")
    elif cd.get("cookie_contents"):
        await update.message.reply_text("🍪 Cookies stored as pasted contents for this chat.")
    else:
        await update.message.reply_text("❌ No cookies stored for this chat.")

async def listallcookies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: list all cookie files present in temp dir matching our naming."""
    user = update.effective_user
    if BOT_OWNER_ID and user and user.id != BOT_OWNER_ID:
        await update.message.reply_text("❌ Not authorized.")
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
    if "cookie" not in fname.lower() and "cookies" not in fname.lower():
        await update.message.reply_text("📄 File doesn't appear to be a cookies file. Upload your browser's exported cookies.txt file.")
        return

    try:
        f = await doc.get_file()
        tmp_cf = os.path.join(tempfile.gettempdir(), f"ytdlp_cookies_chat_{update.effective_chat.id}.txt")
        await f.download_to_drive(tmp_cf)
        context.chat_data["cookiefile"] = tmp_cf
        await update.message.reply_text("✅ Cookie file saved! It will be used for downloads in this chat.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to save cookie file: {e}")

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
            context.chat_data["cookie_contents"] = contents
            await update.message.reply_text("✅ Cookies stored! They will be used for downloads in this chat.")
        except Exception as e:
            await update.message.reply_text(f"❌ Failed to store cookies: {e}")
        return

    if context.user_data.pop("awaiting_yt_url", False):
        url = update.message.text.strip()
        await update.message.reply_text(f"🚀 Starting download from: {url}")
        await handle_download_and_send(update, context, url)

async def handle_download_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Download the given URL as MP3 and send it back to the user. Cleans up temp files."""
    msg = await update.message.reply_text("🔄 Preparing download...")
    mp3_path = None
    try:
        loop = asyncio.get_event_loop()
        if is_playlist_url(url):
            await msg.edit_text("📋 Detected playlist URL — downloading all items...")
            cookie_file = context.chat_data.get("cookiefile")
            paths, playlist_tmpdir = await download_playlist_mp3(url, progress_msg=msg, loop=loop, cookie_file=cookie_file)
            mp3_paths = paths
        else:
            cookie_file = context.chat_data.get("cookiefile")
            mp3_path = await download_audio_mp3(url, progress_msg=msg, loop=loop, cookie_file=cookie_file)
            mp3_paths = [mp3_path] if mp3_path else []
    except Exception as e:
        # Enhanced error messages for common issues
        err_text = str(e).lower()
        if any(phrase in err_text for phrase in ["sign in to confirm", "cookies-from-browser", "cookies", "private", "members-only"]):
            help_msg = (
                "🔒 **Authentication Required**\n\n"
                "This video requires cookies for access. Try:\n"
                "1. Use `/setcookies` and upload your browser's cookies.txt file\n"
                "2. Or use `/setcookies_paste` to paste cookie contents\n\n"
                "**How to export cookies:**\n"
                "• Chrome: Install 'Get cookies.txt' extension\n"
                "• Firefox: Install 'cookies.txt' add-on\n"
                "• Visit YouTube, login, export cookies from the extension"
            )
            await msg.edit_text(help_msg)
            return
        elif "no javascript runtime" in err_text:
            await msg.edit_text("❌ Server configuration issue: JavaScript runtime missing. Please contact the bot admin.")
            return
        elif "ffmpeg" in err_text:
            await msg.edit_text("❌ Server configuration issue: FFmpeg missing. Please contact the bot admin.")
            return
        else:
            await msg.edit_text(f"❌ Download failed: {e}")
            return

    if not mp3_paths:
        await msg.edit_text("❌ No MP3 files were produced.")
        return

    # Send single file
    if len(mp3_paths) == 1:
        mp3_path = mp3_paths[0]
        if not os.path.isfile(mp3_path):
            await msg.edit_text(f"❌ MP3 file not found: {mp3_path}")
            return
        try:
            from telegram import InputFile
            with open(mp3_path, "rb") as f:
                input_file = InputFile(f, filename=os.path.basename(mp3_path))
                await update.message.reply_audio(audio=input_file)
            await msg.delete()
        except Exception as e:
            await msg.edit_text(f"❌ Failed to send audio file: {e}")
        finally:
            try:
                tmpdir = os.path.dirname(mp3_path)
                if tmpdir and os.path.exists(tmpdir):
                    shutil.rmtree(tmpdir)
            except Exception:
                pass
        return

    # Send multiple files from playlist
    try:
        from telegram import InputFile
        await msg.edit_text(f"📤 Sending {len(mp3_paths)} files from playlist...")

        for idx, p in enumerate(mp3_paths, start=1):
            if not p or not os.path.isfile(p):
                try:
                    await update.message.reply_text(f"⚠️ [{idx}/{len(mp3_paths)}] File missing: {p}")
                except Exception:
                    pass
                continue

            try:
                progress_text = f"📤 Sending [{idx}/{len(mp3_paths)}]: {os.path.basename(p)}"
                await update.message.reply_text(progress_text)
                with open(p, "rb") as f:
                    await update.message.reply_audio(audio=InputFile(f, filename=os.path.basename(p)))
            except Exception:
                # Fallback to document
                try:
                    with open(p, "rb") as f:
                        await update.message.reply_document(document=InputFile(f, filename=os.path.basename(p)), caption=f"🎵 {os.path.basename(p)}")
                except Exception:
                    try:
                        await update.message.reply_text(f"❌ Failed to send: {os.path.basename(p)}")
                    except Exception:
                        pass

            await asyncio.sleep(0.5)  # Rate limiting

        try:
            await msg.delete()
        except Exception:
            pass

        # Cleanup playlist temp directory
        try:
            if "playlist_tmpdir" in locals() and playlist_tmpdir and os.path.exists(playlist_tmpdir):
                shutil.rmtree(playlist_tmpdir)
        except Exception:
            pass

    except Exception as e:
        await msg.edit_text(f"❌ Failed to send playlist files: {e}")

# Main entry
if __name__ == '__main__':
    # Check dependencies at startup
    deps = check_dependencies()
    if not deps['status']:
        print(f"WARNING: Missing dependencies: {', '.join(deps['missing'])}")
        print("The bot may not work properly without these dependencies.")

    # Webhook mode for Render
    webhook_base = os.environ.get("TELEGRAM_WEBHOOK_BASE")
    port = int(os.environ.get("PORT", "8000"))

    app = ApplicationBuilder().token(TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("yt", yt_command))
    app.add_handler(CommandHandler("setcookies", setcookies_command))
    app.add_handler(CommandHandler("setcookies_paste", setcookies_paste_command))
    app.add_handler(CommandHandler("cleancookies", cleancookies_command))
    app.add_handler(CommandHandler("listcookies", listcookies_command))
    app.add_handler(CommandHandler("listallcookies", listallcookies_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    app.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, document_handler))

    # Startup tasks
    try:
        fetch_cookies_from_url()
        log_cookie_info()
        startup_cleanup_cookie_files()
    except Exception:
        pass

    if webhook_base:
        # Webhook mode for production (Render)
        import hashlib
        secret_path = hashlib.sha256(TOKEN.encode('utf8')).hexdigest()[:40]
        webhook_path = f"/{secret_path}"
        webhook_url = webhook_base.rstrip('/') + webhook_path
        print(f"🚀 Starting webhook mode on 0.0.0.0:{port}")
        print(f"🔗 Webhook URL: {webhook_url}")
        app.run_webhook(listen='0.0.0.0', port=port, url_path=webhook_path, webhook_url=webhook_url)
    else:
        # Polling mode for development
        print("🚀 Starting polling mode (development)")
        print("⚠️  Set TELEGRAM_WEBHOOK_BASE for production deployment")
        app.run_polling()