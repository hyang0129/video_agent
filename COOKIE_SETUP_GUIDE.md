# How to Export YouTube Cookies

To bypass IP blocking when extracting YouTube captions, you need to export your YouTube cookies and use them with the fact mining system.

## Step 1: Install a Cookie Exporter Extension

Choose one of these browser extensions:

### Chrome/Edge:
- **Get cookies.txt LOCALLY** (recommended)
  - https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc

### Firefox:
- **cookies.txt**
  - https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/

## Step 2: Export YouTube Cookies

1. **Go to YouTube**: Open https://www.youtube.com in your browser
2. **Make sure you're logged in** to your YouTube/Google account
3. **Click the cookie extension icon**
4. **Click "Export"** or "Download" (depends on extension)
5. **Save the file** as `youtube_cookies.txt`

## Step 3: Place Cookie File

Put the exported `youtube_cookies.txt` file in your project root:

```
video_agent/
├── youtube_cookies.txt  ← Place here
├── src/
├── results/
└── ...
```

The system will automatically detect and use this file.

## Step 4: Test Cookie Authentication

Run the test script:

```bash
python test_with_cookies.py
```

This will verify:
- Cookies are loaded correctly
- Caption extraction works
- IP blocking is bypassed

## Alternative: Custom Cookie Location

If you want to use a different location, specify it in code:

```python
from src.facts import FactMiner

# Use custom cookie file
miner = FactMiner(cookies_file="path/to/my_cookies.txt")
```

## Cookie File Format

The cookies.txt file should be in Netscape/Mozilla format:
```
# Netscape HTTP Cookie File
.youtube.com	TRUE	/	TRUE	1234567890	cookie_name	cookie_value
...
```

## Security Note

⚠️ **DO NOT commit cookies to Git!**

Add to your `.gitignore`:
```
youtube_cookies.txt
cookies.txt
*.cookies
```

Cookies contain your authentication session and should be kept private.

## Troubleshooting

### "Failed to load cookies"
- Check the file format (must be Netscape format)
- Make sure you exported from YouTube, not another site
- Try a different browser extension

### "IP BLOCKED" still appears
- Make sure you're logged into YouTube before exporting
- Try exporting fresh cookies
- Check that the cookie file is being loaded (look for "✓ Loaded N cookies" message)

### Cookies expire
- YouTube cookies typically last several months
- If you see blocking again, export fresh cookies
- The system will still work without cookies (but slower with rate limiting)

## How It Works

When you provide cookies:
1. youtube-transcript-api uses your authenticated session
2. YouTube sees requests as coming from a logged-in user
3. IP blocking is bypassed (or significantly reduced)
4. Caption extraction works reliably

## Success Indicators

You'll know it's working when you see:
```
✓ Loaded 15 cookies from youtube_cookies.txt
✓ Captions extracted and cached
```

Instead of:
```
✗ Captions unavailable (disabled, IP blocked, or no captions)
```
