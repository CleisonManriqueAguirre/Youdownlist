# Use Python slim image for efficiency
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    # FFmpeg for audio processing
    ffmpeg \
    # Node.js for JavaScript runtime (required by yt-dlp)
    nodejs \
    npm \
    # Additional tools
    wget \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Verify installations
RUN ffmpeg -version && node --version

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY telegram_bot_fixed.py .
COPY entrypoint.sh .

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Create directory for secrets
RUN mkdir -p /run/secrets

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:$PORT/ || exit 1

# Expose port
EXPOSE $PORT

# Use entrypoint
ENTRYPOINT ["./entrypoint.sh"]