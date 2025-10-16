# Youdownlist

This Telegram bot downloads audio from a YouTube URL and returns an MP3 audio file.

Requirements
- Python 3.9+
- A Telegram bot token set in the environment variable `TELEGRAM_TOKEN`.
- FFmpeg installed and available on your PATH (used by yt-dlp for audio conversion).

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Usage inside Telegram:
- `/start` - simple greeting
- `/help` - usage
- `/yt <youtube_url>` - download audio from the provided YouTube URL and receive an MP3
- `/yt` then send/paste the YouTube URL as the next message - the bot will download that URL

Notes:
- The bot uses `yt-dlp` and ffmpeg to create MP3 files. Make sure ffmpeg is installed on your system and accessible via PATH.
- Keep your bot token secret.

Render deployment (webhook mode)
--------------------------------
This project supports running as a web service (webhook mode) on Render. When deployed as a web service, Telegram will POST updates to your service instead of the bot polling Telegram.

Environment variables to set on Render:
- `TELEGRAM_TOKEN`: your bot token
- `TELEGRAM_WEBHOOK_BASE`: the public base URL for your Render service, e.g. `https://your-service.onrender.com`

Render process type (Procfile):
- The `Procfile` is configured with `web: python telegram_2.py` so Render will bind your service to the assigned port.

When you deploy, Render will provide a `PORT` environment variable. The bot generates a secret webhook path from your token and registers the webhook automatically.
