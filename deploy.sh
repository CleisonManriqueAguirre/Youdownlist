#!/bin/bash

# YouTube Telegram Bot - Render Deployment Script
# This script helps you deploy your bot to Render automatically

set -e

echo "🚀 YouTube Telegram Bot - Render Deployment Setup"
echo "=================================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if required tools are installed
check_dependencies() {
    echo -e "${BLUE}📋 Checking dependencies...${NC}"

    if ! command -v git &> /dev/null; then
        echo -e "${RED}❌ Git is not installed${NC}"
        exit 1
    fi

    if ! command -v curl &> /dev/null; then
        echo -e "${RED}❌ curl is not installed${NC}"
        exit 1
    fi

    echo -e "${GREEN}✅ Dependencies check passed${NC}"
}

# Validate environment variables
check_env_vars() {
    echo -e "${BLUE}🔍 Checking environment configuration...${NC}"

    if [ -f ".env" ]; then
        source .env
    fi

    if [ -z "$TELEGRAM_TOKEN" ]; then
        echo -e "${YELLOW}⚠️  TELEGRAM_TOKEN not set in .env${NC}"
        echo "Please set it manually in Render dashboard after deployment"
    else
        echo -e "${GREEN}✅ TELEGRAM_TOKEN found${NC}"
    fi
}

# Prepare files for deployment
prepare_deployment() {
    echo -e "${BLUE}📦 Preparing deployment files...${NC}"

    # Add new files to git
    git add .

    # Check if there are changes to commit
    if git diff --staged --quiet; then
        echo -e "${YELLOW}⚠️  No changes to commit${NC}"
    else
        # Create commit message
        COMMIT_MSG="🚀 Deploy: Update bot with enhanced features and dependencies

- Added JavaScript runtime support for yt-dlp
- Enhanced error handling and user feedback
- Improved security with environment variables
- Added automated deployment configuration
- Fixed YouTube extraction issues"

        git commit -m "$COMMIT_MSG"
        echo -e "${GREEN}✅ Changes committed${NC}"
    fi
}

# Deploy to GitHub
deploy_to_github() {
    echo -e "${BLUE}📡 Pushing to GitHub...${NC}"

    # Push to main branch
    git push origin main

    echo -e "${GREEN}✅ Successfully pushed to GitHub${NC}"
    echo -e "${BLUE}🔄 GitHub Actions will automatically deploy to Render${NC}"
}

# Instructions for Render setup
render_instructions() {
    echo -e "${YELLOW}📋 RENDER SETUP INSTRUCTIONS${NC}"
    echo "================================="
    echo ""
    echo -e "${BLUE}1. Go to https://dashboard.render.com${NC}"
    echo -e "${BLUE}2. Connect your GitHub repository: CleisonManriqueAguirre/Youdownlist${NC}"
    echo -e "${BLUE}3. Create a new Web Service${NC}"
    echo -e "${BLUE}4. Use these settings:${NC}"
    echo "   - Runtime: Docker"
    echo "   - Build Command: (leave empty, using Dockerfile)"
    echo "   - Start Command: (leave empty, using Dockerfile)"
    echo ""
    echo -e "${YELLOW}5. REQUIRED Environment Variables:${NC}"
    echo "   TELEGRAM_TOKEN = your_bot_token_from_botfather"
    echo "   TELEGRAM_WEBHOOK_BASE = https://your-service-name.onrender.com"
    echo ""
    echo -e "${YELLOW}6. OPTIONAL Environment Variables:${NC}"
    echo "   BOT_OWNER_ID = your_telegram_user_id"
    echo "   YTDLP_COOKIES_B64 = base64_encoded_cookies_for_private_videos"
    echo ""
    echo -e "${GREEN}7. Click 'Create Web Service' and wait for deployment${NC}"
    echo ""
}

# GitHub Secrets instructions
github_secrets_instructions() {
    echo -e "${YELLOW}🔐 GITHUB SECRETS SETUP (for auto-deployment)${NC}"
    echo "=============================================="
    echo ""
    echo -e "${BLUE}1. Go to your GitHub repository: https://github.com/CleisonManriqueAguirre/Youdownlist${NC}"
    echo -e "${BLUE}2. Go to Settings > Secrets and variables > Actions${NC}"
    echo -e "${BLUE}3. Add these secrets:${NC}"
    echo ""
    echo "   RENDER_API_KEY = your_render_api_key"
    echo "   RENDER_SERVICE_ID = your_service_id_from_render"
    echo ""
    echo -e "${BLUE}4. To get Render API key:${NC}"
    echo "   - Go to https://dashboard.render.com/account/api"
    echo "   - Create a new API key"
    echo ""
    echo -e "${BLUE}5. To get Service ID:${NC}"
    echo "   - Go to your service in Render dashboard"
    echo "   - Copy the service ID from the URL"
    echo ""
}

# Health check function
check_deployment() {
    echo -e "${BLUE}🏥 Deployment Health Check${NC}"
    echo "=========================="

    if [ -n "$TELEGRAM_WEBHOOK_BASE" ]; then
        echo -e "${BLUE}Testing webhook endpoint...${NC}"
        if curl -s -o /dev/null -w "%{http_code}" "$TELEGRAM_WEBHOOK_BASE" | grep -q "200\|404"; then
            echo -e "${GREEN}✅ Webhook endpoint is accessible${NC}"
        else
            echo -e "${YELLOW}⚠️  Webhook endpoint not responding (may be normal during deployment)${NC}"
        fi
    fi
}

# Main execution
main() {
    echo ""
    check_dependencies
    echo ""
    check_env_vars
    echo ""
    prepare_deployment
    echo ""
    deploy_to_github
    echo ""
    render_instructions
    echo ""
    github_secrets_instructions
    echo ""

    echo -e "${GREEN}🎉 DEPLOYMENT SETUP COMPLETE!${NC}"
    echo ""
    echo -e "${BLUE}Next steps:${NC}"
    echo "1. Set up your Render service (see instructions above)"
    echo "2. Configure environment variables in Render"
    echo "3. Optionally set up GitHub secrets for auto-deployment"
    echo "4. Test your bot by messaging it on Telegram"
    echo ""
    echo -e "${GREEN}Your bot should be live shortly after Render deployment completes!${NC}"
}

# Handle Ctrl+C
trap 'echo -e "\n${RED}❌ Deployment cancelled${NC}"; exit 1' INT

# Run main function
main