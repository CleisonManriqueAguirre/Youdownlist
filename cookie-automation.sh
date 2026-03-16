#!/bin/bash
# Cookie Management Script for YouTube Telegram Bot
# This script helps set up automated cookie handling

set -e

echo "🍪 YouTube Bot - Cookie Automation Setup"
echo "======================================="

# Function to get cookies from browser
get_browser_cookies() {
    echo "📋 Browser Cookie Export Guide:"
    echo ""
    echo "For Chrome:"
    echo "1. Install 'Get cookies.txt LOCALLY' extension"
    echo "2. Visit youtube.com and login"
    echo "3. Click extension icon → Export"
    echo "4. Save as cookies.txt"
    echo ""
    echo "For Firefox:"
    echo "1. Install 'cookies.txt' addon"
    echo "2. Visit youtube.com and login"
    echo "3. Click addon icon → Export cookies"
    echo "4. Save as cookies.txt"
    echo ""
}

# Function to convert cookies to base64
convert_cookies_to_base64() {
    if [ -f "cookies.txt" ]; then
        echo "🔄 Converting cookies.txt to base64..."
        BASE64_COOKIES=$(base64 -w 0 cookies.txt)
        echo ""
        echo "✅ Base64 encoded cookies:"
        echo "$BASE64_COOKIES"
        echo ""
        echo "💡 Copy this value and set as YTDLP_COOKIES_B64 in Render environment variables"
    else
        echo "❌ cookies.txt file not found in current directory"
    fi
}

# Function to test cookies
test_cookies() {
    if [ -f "cookies.txt" ]; then
        echo "🧪 Testing cookies with yt-dlp..."
        yt-dlp --cookies cookies.txt --simulate "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        if [ $? -eq 0 ]; then
            echo "✅ Cookies are working!"
        else
            echo "❌ Cookies test failed"
        fi
    fi
}

# Function to upload cookies to server
upload_to_server() {
    if [ -f "cookies.txt" ]; then
        echo "🚀 Upload options:"
        echo "1. Set as Render environment variable:"
        convert_cookies_to_base64
        echo ""
        echo "2. Or create a cookie URL endpoint (advanced)"
    fi
}

# Main menu
case "${1:-menu}" in
    "export")
        get_browser_cookies
        ;;
    "convert")
        convert_cookies_to_base64
        ;;
    "test")
        test_cookies
        ;;
    "upload")
        upload_to_server
        ;;
    "all")
        get_browser_cookies
        echo "Press Enter when you have exported cookies.txt..."
        read
        test_cookies
        upload_to_server
        ;;
    *)
        echo "Usage: $0 {export|convert|test|upload|all}"
        echo ""
        echo "Commands:"
        echo "  export  - Show how to export cookies from browser"
        echo "  convert - Convert cookies.txt to base64"
        echo "  test    - Test if cookies work"
        echo "  upload  - Prepare cookies for server upload"
        echo "  all     - Complete workflow"
        ;;
esac