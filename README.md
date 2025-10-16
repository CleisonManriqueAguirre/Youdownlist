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

Run the bot (PowerShell):

```powershell
$env:TELEGRAM_TOKEN="<your-telegram-token>"; python telegrambot.py
```

Usage inside Telegram:
- `/start` - simple greeting
- `/help` - usage
- `/yt <youtube_url>` - download audio from the provided YouTube URL and receive an MP3
- `/yt` then send/paste the YouTube URL as the next message - the bot will download that URL

Notes:
- The bot uses `yt-dlp` and ffmpeg to create MP3 files. Make sure ffmpeg is installed on your system and accessible via PATH.
- Keep your bot token secret.
