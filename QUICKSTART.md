# 🚀 Quick Deploy to Render

## Option 1: Automated Deployment (Recommended)

### 1. Run the deployment script:
```bash
./deploy.sh
```

### 2. Follow the instructions to:
- Set up Render service
- Configure environment variables
- Optionally set up GitHub Actions

## Option 2: Manual Steps

### 1. Environment Setup
```bash
# Copy environment template
cp .env.template .env

# Edit with your bot token
nano .env
```

### 2. Push to GitHub
```bash
git add .
git commit -m "Deploy bot to Render"
git push origin main
```

### 3. Create Render Service
1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click "New +" → "Web Service"
3. Connect your GitHub repo: `CleisonManriqueAguirre/Youdownlist`
4. Use these settings:
   - **Runtime**: Docker
   - **Build Command**: (leave empty)
   - **Start Command**: (leave empty)

### 4. Set Environment Variables
In Render dashboard, add:
```
TELEGRAM_TOKEN=your_bot_token_from_botfather
TELEGRAM_WEBHOOK_BASE=https://your-service-name.onrender.com
```

### 5. Deploy!
Click "Create Web Service" and wait for deployment.

## Testing Locally

### Using Make (recommended):
```bash
make setup    # Setup development environment
make dev      # Run in development mode
```

### Using Docker:
```bash
make run-local    # Run with Docker Compose
```

### Direct Python:
```bash
pip install -r requirements.txt
python telegram_bot_fixed.py
```

## Commands Available

```bash
make help      # Show all available commands
make test      # Test bot functionality
make deploy    # Deploy to Render
make clean     # Clean up files
```

## Get Your Bot Token

1. Message [@BotFather](https://t.me/botfather) on Telegram
2. Send `/newbot`
3. Follow instructions to create your bot
4. Copy the token and set it in environment variables

## Troubleshooting

### Bot not responding?
- Check `TELEGRAM_TOKEN` is correct
- Check `TELEGRAM_WEBHOOK_BASE` matches your Render URL
- Check Render service is running

### Downloads failing?
- Age-restricted videos need cookies (use `/setcookies`)
- Check if yt-dlp and FFmpeg are installed in container

### Need help?
- Check the `DEPLOYMENT.md` file for detailed instructions
- Look at the logs in Render dashboard