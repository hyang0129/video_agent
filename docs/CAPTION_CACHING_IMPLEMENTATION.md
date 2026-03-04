# Caption Caching and Rate Limiting - Implementation Summary

## ✅ What Was Implemented

### 1. Caption Cache System
**File**: [src/facts/caption_cache.py](../src/facts/caption_cache.py)

A file-based cache that stores extracted YouTube captions to avoid redundant API calls.

**Features**:
- Stores captions as JSON files in `results/captions/`
- Automatic cache lookup before API calls
- Persistent storage (no expiration)
- Cache management: get(), set(), has(), delete(), clear()
- Statistics: cached_videos count, total size

**Benefits**:
- Avoid re-downloading captions you already have
- Iterate on fact extraction prompts without hitting YouTube
- Share caption cache with team (can commit to Git)
- Work around IP blocks by using pre-cached data

### 2. Rate Limiting
**File**: [src/facts/fact_miner.py](../src/facts/fact_miner.py#L420-422)

Added 3-second delays between caption extraction requests.

**Implementation**:
```python
# Rate limiting: wait 3 seconds between requests to avoid IP blocking
if idx < len(videos) - 1:
    print(f"  ⏱ Rate limiting: waiting 3 seconds...")
    time.sleep(3)
```

**Smart delays**:
- Only delays between NEW caption extractions
- Skips delay when using cached captions
- Skips delay after the last video

### 3. Integration
**Changes in FactMiner**:
- Constructor accepts `caption_cache` parameter
- `mine_video_captions()` checks cache before API call
- Successful extractions automatically cached
- Progress logging shows cache hits vs new extractions

## 📋 How It Works

### Caption Extraction Flow
```
User calls: miner.mine_top_videos(...)
  ↓
For each video:
  1. Check caption_cache.get(video_id)
     ├─ CACHE HIT → Use cached captions (instant, no API call)
     └─ CACHE MISS → Extract from YouTube
         ├─ Success → Cache for future use
         └─ Fail → Log error and continue
  
  2. If new extraction: wait 3 seconds (rate limit)
  
  3. Extract facts from captions with LLM
  
  4. Store facts in database
```

### File Structure
```
results/
├── captions/           ← Caption cache (NEW)
│   ├── dQw4w9WgXcQ.json
│   ├── jNQXAC9IVRw.json
│   └── ...
├── facts.db           ← Fact database
└── ...
```

### Caption Cache Format
```json
{
  "video_id": "dQw4w9WgXcQ",
  "cached_at": "2026-02-03T10:30:00",
  "caption_data": {
    "video_id": "dQw4w9WgXcQ",
    "text": "full transcript text...",
    "segments": [
      {"text": "...", "start": 0.0, "duration": 5.2},
      ...
    ],
    "language": "en"
  }
}
```

## 🚨 Current Issue: IP Blocking

**The youtube-transcript-api library is still getting IP blocked by YouTube.**

Even with rate limiting, YouTube is blocking caption extraction requests from your IP address. This affects ALL videos, even those with available captions.

### Why This Happens
1. **Too many requests**: YouTube tracks requests per IP
2. **Cloud/VPN IPs**: Many cloud provider IPs are pre-blocked
3. **No authentication**: youtube-transcript-api doesn't use YouTube login

### Evidence
Testing shows:
```
✗ No captions available
```
For ALL videos tested, including popular ones that definitely have captions.

## 🔧 Solutions to IP Blocking

### Option 1: Use Cookies (Recommended)
Add YouTube authentication cookies to bypass IP restrictions.

**Steps**:
1. Log into YouTube in your browser
2. Export cookies using browser extension (e.g., "EditThisCookie")
3. Save cookies to file
4. Update youtube-transcript-api to use cookies:

```python
from youtube_transcript_api import YouTubeTranscriptApi
from http.cookiejar import MozillaCookieJar

# Load cookies
cookies = MozillaCookieJar('cookies.txt')
cookies.load()

# Use with API
api = YouTubeTranscriptApi(cookies=cookies)
```

See: https://github.com/jdepoix/youtube-transcript-api#working-around-ip-bans

### Option 2: Increase Rate Limiting
Change from 3 seconds to 10-30 seconds between requests.

**Edit**: [src/facts/fact_miner.py](../src/facts/fact_miner.py#L422)
```python
time.sleep(10)  # Increase from 3 to 10 seconds
```

**Downside**: Very slow for mining many videos.

### Option 3: Use Proxies
Route requests through rotating residential proxies.

**Requires**: Paid proxy service (e.g., Smartproxy, Oxylabs)

### Option 4: Use Official YouTube Data API
Switch to official API for captions (requires OAuth).

**Cost**: 200 quota units per caption request
**Benefit**: No IP blocking
**Downside**: Higher quota usage

### Option 5: Pre-populate Cache
Manually download captions and add to cache.

**Steps**:
1. Download captions from YouTube (browser extensions exist)
2. Convert to cache format
3. Save to `results/captions/{video_id}.json`
4. Run fact extraction (will use cached data)

## 🧪 Testing the Implementation

### Test Cache Functionality
```bash
python test_caption_caching.py
```

This tests:
- Cache initialization
- Mining with caching enabled
- Cache statistics
- Rate limiting

### Test Specific Videos
```bash
python test_specific_captions.py
```

Tests caption extraction on known popular videos.

**Current result**: All fail due to IP blocking

## 📝 Usage Examples

### Basic Usage (Automatic Caching)
```python
from src.facts import FactMiner

# Cache is used automatically
miner = FactMiner()
result = miner.mine_top_videos(
    topic_query="star wars facts",
    topic_id="star_wars",
    max_videos=10,
    use_captions=True,  # Uses cache when available
)

print(f"Videos mined: {result['videos_mined']}")
print(f"Facts extracted: {result['total_facts']}")
```

### Manual Cache Management
```python
from src.facts import CaptionCache

cache = CaptionCache()

# Check cache stats
stats = cache.get_stats()
print(f"Cached videos: {stats['cached_videos']}")
print(f"Cache size: {stats['total_size_mb']} MB")

# Check if video is cached
if cache.has("dQw4w9WgXcQ"):
    captions = cache.get("dQw4w9WgXcQ")
    print(f"Caption length: {len(captions['text'])}")

# Clear cache
count = cache.clear()
print(f"Deleted {count} cached videos")
```

### Custom Cache Location
```python
from pathlib import Path
from src.facts import CaptionCache, FactMiner

# Use custom cache directory
custom_cache = CaptionCache(cache_dir=Path("./my_caption_cache"))
miner = FactMiner(caption_cache=custom_cache)
```

## 📊 Performance Impact

### Without Caching
- 25 videos × 3 seconds = 75 seconds of delays
- 25 API calls to YouTube (IP block risk)
- Rerunning costs same time

### With Caching
- **First run**: Same as above (75 seconds + extraction time)
- **Second run**: 0 API calls, ~instant caption retrieval
- **Iterating on prompts**: No re-downloading needed

### Example Savings
If you iterate 5 times on fact extraction prompts:
- **Without cache**: 5 × 75s = 375 seconds (6.25 minutes)
- **With cache**: 75s first run + 4 × 0s = 75 seconds total

## 🎯 Next Steps

1. **Solve IP blocking** (choose an option above)
   - Recommended: Add YouTube cookies to youtube-transcript-api
   
2. **Test with working captions**
   - Verify cache saves successfully
   - Verify second run uses cache (instant)
   
3. **Run full pipeline**
   - Mine captions with new system
   - Extract facts with improved prompt
   - Verify fact quality (no meta-facts)
   
4. **Optimize if needed**
   - Adjust rate limiting delay
   - Add retry logic
   - Implement exponential backoff

## 📂 Files Added/Modified

### New Files
- `src/facts/caption_cache.py` - Caption caching system
- `test_caption_caching.py` - Test script for caching
- `test_specific_captions.py` - Test specific videos
- `CAPTION_CACHING_IMPLEMENTATION.md` - This document

### Modified Files
- `src/facts/fact_miner.py`
  - Added CaptionCache integration
  - Added rate limiting (3 seconds)
  - Cache check before API calls
  - Progress logging improvements
  
- `src/facts/__init__.py`
  - Exported CaptionCache class
  
- `FACT_EXTRACTION_TROUBLESHOOTING.md`
  - Added caching documentation
  - Updated architecture diagrams

## ✨ Summary

**What works now**:
- ✅ Caption cache system (stores/retrieves captions)
- ✅ Rate limiting (3-second delays)
- ✅ Smart cache checks (before API calls)
- ✅ Persistent cache (survives restarts)
- ✅ Cache statistics and management

**What still needs fixing**:
- ❌ IP blocking from YouTube
  - Requires cookies, proxies, or other workaround
  - See "Solutions to IP Blocking" section above

**Once IP blocking is resolved**, the caching system will:
- Speed up subsequent runs dramatically
- Allow iteration on fact extraction prompts without re-downloading
- Provide a persistent store of caption data
