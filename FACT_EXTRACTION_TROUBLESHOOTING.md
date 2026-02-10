# Fact Extraction Troubleshooting Summary

## Root Causes Identified

### 1. Caption Extraction IP Blocking
**Issue**: The `youtube-transcript-api` library is being blocked by YouTube's IP protection
- YouTube blocks excessive requests from the same IP
- Cloud provider IPs (AWS, GCP, Azure) are commonly blocked
- This causes ALL caption extraction attempts to fail silently

**Evidence**:
```
IpBlocked: Could not retrieve a transcript for the video
This is most likely caused by:
- You have done too many requests and your IP has been blocked by YouTube
- You are doing requests from an IP belonging to a cloud provider
```

**Impact**: Videos processed: 0 (despite finding 18 videos)

### 2. Title Mining Extracting Meta-Facts
**Issue**: The title mining component extracted information ABOUT videos, not actual facts
- Example bad facts:
  - "Death Star has 101 facts" (from video title "101 Facts About the Death Star")
  - "Boba Fett has at least 10 significant facts"
- These are useless for script generation

**Evidence**: All 6 facts in database had source type "video_title_hint", none from "youtube_captions"

## Solutions Implemented

### 1. Caption Caching System
**New**: Implemented file-based caption cache in [caption_cache.py](src/facts/caption_cache.py)
- **Stores extracted captions** in `results/captions/` directory
- **Reuses cached captions** on subsequent fact mining runs
- **Avoids redundant API calls** that trigger IP blocks
- **No expiration** - captions don't change, so cache persists

**Benefits**:
- Can re-run fact extraction without hitting YouTube API
- Iterate on fact extraction prompts without re-downloading
- Share caption cache across team members

**Usage**:
```python
from src.facts import FactMiner, CaptionCache

# Cache is automatically used
miner = FactMiner()
result = miner.mine_top_videos(...)  # Uses cache when available

# Check cache stats
cache = CaptionCache()
stats = cache.get_stats()
print(f"Cached videos: {stats['cached_videos']}")
```

### 2. Rate Limiting
**Added**: 3-second delays between caption extraction requests
- Prevents rapid-fire requests that trigger IP blocks
- Only delays between NEW extractions (skips delay for cached)
- Configurable delay in future versions

**Implementation**: See [fact_miner.py:420-422](src/facts/fact_miner.py#L420-L422)

### 3. Improved Fact Extraction Prompt
Enhanced `FACT_EXTRACTION_PROMPT` in [fact_miner.py](../src/facts/fact_miner.py):
- **Critical rules** explicitly forbidding meta-facts
- **Examples** showing good vs bad facts:
  - ✓ "The Death Star's superlaser required 24 hours to recharge between firing"
  - ✗ "There are 101 facts about the Death Star"
- Focus on **specific, interesting trivia** with numbers/dates/names

### 3. Improved Fact Extraction Prompt
Removed title mining from `mine_top_videos()` because:
- Titles contain meta-information, not actual facts
- Pollutes database with low-quality data
- Caption mining is the only reliable source

### 4. Disabled Title Mining
Updated [youtube_tools.py](../src/tools/youtube_tools.py):
- Added `IpBlocked` and `VideoUnavailable` to exception handling
- Added logging for caption extraction failures
- Graceful degradation when captions unavailable

### 5. Better Error Handling

### Immediate Actions
1. **Use cookies/proxies** for youtube-transcript-api
   - See: https://github.com/jdepoix/youtube-transcript-api#working-around-ip-bans
   - Cookie-based authentication can bypass IP blocks
   - Proxies can rotate IPs

2. **Rate limiting** between caption requests
   - Add delays (2-5 seconds) between videos
   - Prevents rapid-fire requests that trigger blocks

3. **Test with working videos** first
   - Find videos known to have captions
   - Verify caption extraction works before bulk mining

### Alternative Approaches

#### Option A: YouTube Data API Captions
Use official YouTube Data API instead of youtube-transcript-api:
- **Pros**: No IP blocking, official API
- **Cons**: Costs 200 quota per caption, requires OAuth for private videos

#### Option B: Manual Caption Files
Pre-download captions for key videos:
- **Pros**: No API calls, no blocking
- **Cons**: Manual work, not scalable

#### Option C: Proxy Service
Use rotating residential proxies:
- **Pros**: Bypasses IP blocks reliably
- **Cons**: Additional cost, setup complexity

## Testing Plan

1. **✅ Caption caching**: Implemented and integrated
2. **✅ Rate limiting**: 3-second delays between requests
3. **Test cache persistence**: Run script twice, verify second run uses cache
4. **Test with working videos**: Find videos with available captions
5. **Monitor success rate**: Track caption extraction success/failure ratios
6. **Fact quality check**: Review extracted facts for meta-information vs real facts

## Quick Start

Test the new caching system:
```bash
python test_caption_caching.py
```

This will:
- Show current cache status
- Mine 5 Star Wars videos with caching + rate limiting
- Display cache stats after mining
- Show sample extracted facts

## Files Modified

- **[src/facts/caption_cache.py](src/facts/caption_cache.py)** ← NEW
  - File-based cache for YouTube captions
  - get(), set(), has(), delete(), clear() operations
  - Cache statistics and management

- [src/facts/fact_miner.py](../src/facts/fact_miner.py)
  - Enhanced FACT_EXTRACTION_PROMPT with explicit rules
  - Disabled title mining
  - Added caption failure logging

- [src/tools/youtube_tools.py](../src/tools/youtube_tools.py)
  - Added IpBlocked exception handling
  - Better error logging

## Database Status

- **Cleared**: 6 bad meta-facts deleted
- **Ready**: Clean database for new fact mining
- **Location**: `results/facts.db`

## Next Steps

1. Implement cookie-based auth or proxy solution for youtube-transcript-api
2. Re-run Star Wars fact mining with working caption extraction
3. Verify extracted facts are real trivia, not meta-information
4. Test script generation with quality facts
