# Quick Start: Cookie Authentication for YouTube Caption Extraction

## Problem
YouTube is blocking caption extraction requests from your IP.

## Solution
Use YouTube cookies to authenticate requests.

## Steps (5 minutes)

### 1. Install Browser Extension

**Chrome/Edge**: Search "Get cookies.txt LOCALLY" in Chrome Web Store

**Firefox**: Search "cookies.txt" in Firefox Add-ons

### 2. Export Cookies

1. Open https://youtube.com in browser
2. **Make sure you're logged in**
3. Click the cookie extension icon
4. Click "Export" or "Download"
5. Save as `youtube_cookies.txt`

### 3. Move File

Place `youtube_cookies.txt` in project root:
```
video_agent/
├── youtube_cookies.txt  ← Here
├── src/
├── results/
└── ...
```

### 4. Test

```bash
python test_with_cookies.py
```

Look for:
```
✓ Loaded 15 cookies from youtube_cookies.txt
✓ SUCCESS: 12,534 characters
```

### 5. Run Fact Mining

```bash
python run_star_wars_auto.py
```

## What Changed

✅ **Cookie authentication**: Bypasses IP blocking
✅ **Rate limiting**: Increased 3s → 10s between requests  
✅ **Caption caching**: Saves captions for reuse
✅ **Auto-detection**: Finds `youtube_cookies.txt` automatically

## Troubleshooting

**"Cookie file not found"**
→ Make sure file is named exactly `youtube_cookies.txt`
→ Place in project root (same folder as `main.py`)

**"Failed to load cookies"**
→ Make sure you exported from YouTube, not another site
→ File should start with `# Netscape HTTP Cookie File`

**Still getting "IP BLOCKED"**
→ Export fresh cookies while logged into YouTube
→ Make sure cookies are from youtube.com, not m.youtube.com

## Documentation

- Full guide: [COOKIE_SETUP_GUIDE.md](COOKIE_SETUP_GUIDE.md)
- Implementation: [COOKIE_IMPLEMENTATION_COMPLETE.md](COOKIE_IMPLEMENTATION_COMPLETE.md)
- Caching system: [CAPTION_CACHING_IMPLEMENTATION.md](CAPTION_CACHING_IMPLEMENTATION.md)

## Security

⚠️ **Do not commit cookies to Git** (already in .gitignore)
- Cookies contain your authentication session
- Keep them private

## Need Help?

Run diagnostics:
```bash
python test_ip_blocking.py  # Check if IP is blocked
python test_with_cookies.py # Test cookie authentication
```
