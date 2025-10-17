#!/usr/bin/env sh
# Entry point for Render/docker: ensure cookies are written to the expected path
# Usage: set YTDLP_COOKIES_FILE=/run/secrets/ytdlp_cookies.txt and either
#        set YTDLP_COOKIES (raw contents) or YTDLP_COOKIES_B64 (base64 contents).

set -e

: ${YTDLP_COOKIES_FILE:=/run/secrets/ytdlp_cookies.txt}

if [ -n "$YTDLP_COOKIES_B64" ]; then
  echo "Decoding YTDLP_COOKIES_B64 to $YTDLP_COOKIES_FILE"
  echo "$YTDLP_COOKIES_B64" | base64 -d > "$YTDLP_COOKIES_FILE" || echo "Failed to decode base64 cookies"
elif [ -n "$YTDLP_COOKIES" ]; then
  echo "Writing YTDLP_COOKIES to $YTDLP_COOKIES_FILE"
  printf "%s" "$YTDLP_COOKIES" > "$YTDLP_COOKIES_FILE"
else
  echo "No YTDLP_COOKIES or YTDLP_COOKIES_B64 provided; leaving $YTDLP_COOKIES_FILE absent unless mounted."
fi

# Make sure file is readable by the app (best-effort)
if [ -f "$YTDLP_COOKIES_FILE" ]; then
  chmod 600 "$YTDLP_COOKIES_FILE" || true
  echo "Cookie file created: $YTDLP_COOKIES_FILE (size: $(wc -c < "$YTDLP_COOKIES_FILE") bytes)"
fi

exec python telegram_2.py
