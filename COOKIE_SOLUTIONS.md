# Global Cookie Solution for YouTube Bot

## 🎯 **Cookie Automation Solutions**

### **Solution 1: Set Global Cookies (Recommended)**

Export cookies once and set them globally for all users:

#### **Step 1: Export Your Cookies**
```bash
# Run the automation script
./cookie-automation.sh all
```

#### **Step 2: Set in Render Environment**
Add this to your Render environment variables:
```
YTDLP_COOKIES_B64=your_base64_encoded_cookies_here
```

#### **Step 3: Automatic Cookie Refresh**
Set up a periodic cookie refresh (optional):
```bash
# Add to crontab or Render cron job
0 0 * * 0 ./cookie-automation.sh convert && curl -X POST render_webhook_url
```

---

### **Solution 2: Cookie Proxy Service**

Create a service that handles authentication automatically.

#### **Create Cookie Service:**
```python
# cookie_service.py
import requests
import base64
import os
from datetime import datetime, timedelta

class CookieManager:
    def __init__(self):
        self.cookies_file = "/tmp/youtube_cookies.txt"
        self.last_update = None

    def get_fresh_cookies(self):
        """Get fresh cookies from your cookie source."""
        # This could fetch from a secure endpoint
        cookie_url = os.environ.get("COOKIE_REFRESH_URL")
        if cookie_url:
            response = requests.get(cookie_url, headers={
                "Authorization": f"Bearer {os.environ.get('COOKIE_TOKEN')}"
            })
            if response.status_code == 200:
                return response.text
        return None

    def should_refresh(self):
        """Check if cookies need refresh (daily)."""
        if not self.last_update:
            return True
        return datetime.now() - self.last_update > timedelta(days=1)

    def refresh_cookies(self):
        """Refresh cookies if needed."""
        if self.should_refresh():
            cookies = self.get_fresh_cookies()
            if cookies:
                with open(self.cookies_file, 'w') as f:
                    f.write(cookies)
                self.last_update = datetime.now()
                return True
        return False

    def get_cookies_file(self):
        """Get path to cookies file."""
        self.refresh_cookies()
        return self.cookies_file if os.path.exists(self.cookies_file) else None
```

---

### **Solution 3: Browser Automation (Advanced)**

Automatically extract cookies using headless browser:

```python
# auto_cookies.py
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time
import json

def auto_extract_cookies(username, password):
    """Automatically extract YouTube cookies."""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")

    driver = webdriver.Chrome(options=chrome_options)

    try:
        # Login to YouTube
        driver.get("https://accounts.google.com/signin")
        # Add login automation here

        # Get cookies
        cookies = driver.get_cookies()

        # Convert to Netscape format
        cookie_str = ""
        for cookie in cookies:
            if 'youtube.com' in cookie.get('domain', ''):
                cookie_str += f"{cookie['domain']}\tTRUE\t{cookie['path']}\t"
                cookie_str += f"{'TRUE' if cookie.get('secure') else 'FALSE'}\t"
                cookie_str += f"{cookie.get('expiry', 0)}\t{cookie['name']}\t{cookie['value']}\n"

        return cookie_str

    finally:
        driver.quit()
```

---

## 🚀 **Quick Implementation**

### **Option A: Use Your Personal Cookies Globally**

1. **Export cookies from your browser**:
   ```bash
   ./cookie-automation.sh export
   # Follow instructions to get cookies.txt
   ```

2. **Convert to base64**:
   ```bash
   ./cookie-automation.sh convert
   ```

3. **Set in Render**:
   - Go to Environment Variables
   - Add: `YTDLP_COOKIES_B64=<your_base64_cookies>`

### **Option B: Enhanced Bot with Better Guidance**

Deploy the new enhanced bot that provides step-by-step cookie guidance:

```bash
# Update your Render start command:
python telegram_bot_enhanced.py
```

---

## 📱 **User Experience Improvements**

The enhanced bot now provides:

- ✅ **Interactive buttons** for cookie setup
- ✅ **Device-specific instructions** (mobile/desktop)
- ✅ **Multiple download strategies** with fallbacks
- ✅ **Better error messages** with actionable solutions
- ✅ **Smart retry logic** when downloads fail

---

**Which solution would you like to implement first?**

1. **Global cookies** (set once, works for everyone)
2. **Enhanced bot** (better user guidance)
3. **Both** (recommended)

Let me know and I'll help you set it up!