# YouTube to MP3 Telegram Bot - Deployment Guide

## Issues Fixed

✅ **JavaScript Runtime**: Added Node.js support for yt-dlp YouTube extraction
✅ **FFmpeg**: Proper FFmpeg installation for audio conversion
✅ **Security**: Removed hardcoded tokens, using environment variables
✅ **Error Handling**: Better error messages and user guidance
✅ **Compatibility**: Two implementation approaches available

## Deployment Options

### Option 1: Enhanced Python Bot (Recommended)
Uses `telegram_bot_fixed.py` - Full-featured with cookie management and enhanced error handling.

### Option 2: Shell Command Bot
Uses `telegram_bot_shell.py` - Simpler implementation using shell yt-dlp commands.

## Render Deployment Steps

### 1. Environment Variables
Set these in your Render dashboard:

```bash
# Required
TELEGRAM_TOKEN=your_bot_token_from_botfather
TELEGRAM_WEBHOOK_BASE=https://your-app-name.onrender.com

# Optional (for private/age-restricted videos)
YTDLP_COOKIES_B64=base64_encoded_cookies_from_browser
BOT_OWNER_ID=your_telegram_user_id
```

### 2. Update entrypoint.sh
Choose which bot version to run:

```bash
# For enhanced version (recommended)
exec python telegram_bot_fixed.py

# OR for shell version
exec python telegram_bot_shell.py
```

### 3. Deploy to Render
The provided Dockerfile will:
- Install Node.js (JavaScript runtime)
- Install FFmpeg (audio processing)
- Install Python dependencies
- Set up proper environment

## Local Development

1. Copy environment template:
```bash
cp .env.template .env
```

2. Edit `.env` with your values:
```bash
TELEGRAM_TOKEN=your_bot_token
# Leave TELEGRAM_WEBHOOK_BASE empty for polling mode
```

3. Install dependencies:
```bash
pip install -r requirements.txt
# Install Node.js and FFmpeg on your system
```

4. Run bot:
```bash
python telegram_bot_fixed.py
```

## Cookie Setup (for private videos)

### Browser Extensions:
- **Chrome**: "Get cookies.txt" extension
- **Firefox**: "cookies.txt" add-on

### Steps:
1. Install browser extension
2. Login to YouTube
3. Export cookies.txt
4. For Render: Convert to base64 and set as `YTDLP_COOKIES_B64`
5. For local: Save file and set `YTDLP_COOKIES_FILE` path

### Convert cookies to base64:
```bash
base64 -w 0 cookies.txt
```

## Troubleshooting

### "No JavaScript runtime found"
- **Solution**: Ensure Node.js is installed (included in Dockerfile)
- **Test**: `node --version`

### "FFmpeg not found"
- **Solution**: Install FFmpeg (included in Dockerfile)
- **Test**: `ffmpeg -version`

### "Sign in to confirm you're not a bot"
- **Solution**: Set up cookies using `/setcookies` command
- **Cause**: Age-restricted or private video

### Bot not responding on Render
- **Check**: `TELEGRAM_WEBHOOK_BASE` environment variable
- **Check**: Bot token is correct
- **Check**: Render service is running

## Features

### Commands:
- `/start` - Welcome message
- `/help` - Command help
- `/yt <url>` - Download from URL
- `/setcookies` - Upload cookies file
- `/setcookies_paste` - Paste cookie contents
- `/cleancookies` - Remove stored cookies
- `/listcookies` - Check stored cookies

### Supported:
- ✅ Single videos
- ✅ Playlists
- ✅ Age-restricted content (with cookies)
- ✅ Multiple audio formats
- ✅ Progress tracking
- ✅ Error recovery

## Architecture

```
User -> Telegram -> Webhook -> Render -> yt-dlp -> FFmpeg -> MP3 -> User
```

The bot uses webhooks in production (Render) and polling in development.