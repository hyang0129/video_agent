"""YouTube Data API tools for market research."""

from typing import List, Dict, Optional, Literal, Any
import re
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
import isodate
import requests
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import requests_cache
from langchain_core.tools import tool
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    IpBlocked,
    VideoUnavailable,
)
from http.cookiejar import MozillaCookieJar

from ..config import (
    YOUTUBE_API_KEY,
    ENABLE_CACHE,
    CACHE_EXPIRE_HOURS,
    CACHE_DIR,
    SHORT_FORM_DURATION,
    MIN_ENGAGEMENT_RATE,
    SCORING_WEIGHTS,
)


# Initialize cache
if ENABLE_CACHE:
    requests_cache.install_cache(
        str(CACHE_DIR / "youtube_cache"),
        expire_after=timedelta(hours=CACHE_EXPIRE_HOURS),
    )


class YouTubeClient:
    """Client for interacting with YouTube Data API."""
    
    def __init__(self, api_key: str = YOUTUBE_API_KEY, cookies_file: Optional[str] = None):
        if not api_key:
            raise ValueError("YouTube API key is required")
        self.youtube = build("youtube", "v3", developerKey=api_key)
        self.quota_used = 0
        
        # Load cookies for transcript API if provided
        self.cookies = None
        self.http_client = None
        if cookies_file:
            cookies_path = Path(cookies_file)
            if cookies_path.exists():
                self.cookies = MozillaCookieJar(str(cookies_path))
                try:
                    self.cookies.load(ignore_discard=True, ignore_expires=True)
                    # Create requests session with cookies
                    self.http_client = requests.Session()
                    self.http_client.cookies = self.cookies
                    print(f"[OK] Loaded {len(self.cookies)} cookies from {cookies_file}")
                except Exception as e:
                    print(f"[FAIL] Failed to load cookies: {e}")
                    self.cookies = None
                    self.http_client = None
            else:
                print(f"[FAIL] Cookie file not found: {cookies_file}")
        
        # Try default cookie location if not provided
        if not self.cookies:
            default_cookies = Path("youtube_cookies.txt")
            if default_cookies.exists():
                self.cookies = MozillaCookieJar(str(default_cookies))
                try:
                    self.cookies.load(ignore_discard=True, ignore_expires=True)
                    # Create requests session with cookies
                    self.http_client = requests.Session()
                    self.http_client.cookies = self.cookies
                    print(f"[OK] Loaded {len(self.cookies)} cookies from default location")
                except:
                    self.cookies = None
                    self.http_client = None
    
    def parse_duration(self, duration_str: str) -> int:
        """Parse ISO 8601 duration to seconds."""
        try:
            duration = isodate.parse_duration(duration_str)
            return int(duration.total_seconds())
        except:
            return 0
    
    def get_video_captions(self, video_id: str, languages: List[str] = ["en"]) -> Optional[Dict[str, Any]]:
        """Get video captions/subtitles if available.
        
        Uses youtube-transcript-api which doesn't consume YouTube API quota.
        
        Args:
            video_id: YouTube video ID
            languages: List of preferred language codes (default: ["en"])
        
        Returns:
            Dict with 'text' (full transcript) and 'segments' (timestamped entries),
            or None if unavailable
        """
        try:
            # Create transcript API instance with http_client if cookies available
            if self.http_client:
                api = YouTubeTranscriptApi(http_client=self.http_client)
            else:
                api = YouTubeTranscriptApi()
            
            # Fetch transcript (returns FetchedTranscript object)
            transcript = api.fetch(video_id, languages=languages)
            
            # Get raw transcript data as list
            transcript_list = transcript.to_raw_data()
            
            # Build full text and keep segments
            full_text = " ".join([entry["text"] for entry in transcript_list])
            
            return {
                "video_id": video_id,
                "text": full_text,
                "segments": transcript_list,  # [{text, start, duration}, ...]
                "language": transcript.language_code
            }
            
        except (TranscriptsDisabled, NoTranscriptFound, IpBlocked, VideoUnavailable):
            # Captions not available, disabled, or IP blocked
            return None
        except Exception as e:
            # Catch all other errors (e.g., network issues)
            print(f"Caption extraction error for {video_id}: {type(e).__name__}: {str(e)}")
            return None
    
    def search_videos(
        self,
        query: str,
        max_results: int = 50,
        order: str = "relevance",
        duration: Optional[str] = None,
        published_after: Optional[datetime] = None,
    ) -> List[Dict]:
        """
        Search for videos on YouTube.
        
        Args:
            query: Search query string
            max_results: Maximum number of results (max 50 per call)
            order: Sort order (relevance, viewCount, date, rating)
            duration: Video duration (short, medium, long)
            published_after: Only include videos after this date
        
        Returns:
            List of video metadata dictionaries
        """
        try:
            params = {
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": min(max_results, 50),
                "order": order,
            }
            
            if duration:
                params["videoDuration"] = duration
            
            if published_after:
                params["publishedAfter"] = published_after.isoformat() + "Z"
            
            search_response = self.youtube.search().list(**params).execute()
            self.quota_used += 100  # Search costs 100 quota units
            
            video_ids = [item["id"]["videoId"] for item in search_response.get("items", [])]
            
            if not video_ids:
                return []
            
            # Get detailed video statistics
            videos_response = self.youtube.videos().list(
                part="snippet,statistics,contentDetails",
                id=",".join(video_ids)
            ).execute()
            self.quota_used += 1  # Video details cost 1 unit
            
            videos = []
            for item in videos_response.get("items", []):
                duration_seconds = self.parse_duration(
                    item["contentDetails"]["duration"]
                )
                
                stats = item["statistics"]
                views = int(stats.get("viewCount", 0))
                likes = int(stats.get("likeCount", 0))
                comments = int(stats.get("commentCount", 0))
                
                videos.append({
                    "id": item["id"],
                    "title": item["snippet"]["title"],
                    "channel_id": item["snippet"]["channelId"],
                    "channel_name": item["snippet"]["channelTitle"],
                    "published": item["snippet"]["publishedAt"],
                    "description": item["snippet"]["description"],
                    "duration_seconds": duration_seconds,
                    "views": views,
                    "likes": likes,
                    "comments": comments,
                    "engagement_rate": likes / views if views > 0 else 0,
                    "tags": item["snippet"].get("tags", []),
                })
            
            return videos
        
        except HttpError as e:
            print(f"YouTube API error: {e}")
            return []
    
    def get_channel_info(self, channel_id: str) -> Optional[Dict]:
        """Get detailed information about a YouTube channel."""
        try:
            response = self.youtube.channels().list(
                part="snippet,statistics,contentDetails",
                id=channel_id
            ).execute()
            self.quota_used += 1
            
            if not response.get("items"):
                return None
            
            item = response["items"][0]
            stats = item["statistics"]
            
            return {
                "id": channel_id,
                "name": item["snippet"]["title"],
                "description": item["snippet"]["description"],
                "subscribers": int(stats.get("subscriberCount", 0)),
                "total_views": int(stats.get("viewCount", 0)),
                "video_count": int(stats.get("videoCount", 0)),
                "published": item["snippet"]["publishedAt"],
            }
        
        except HttpError as e:
            print(f"YouTube API error: {e}")
            return None
    
    def get_channel_videos(
        self,
        channel_id: str,
        max_results: int = 50,
        order: str = "date"
    ) -> List[Dict]:
        """Get recent videos from a channel."""
        try:
            # Get uploads playlist ID
            channel_response = self.youtube.channels().list(
                part="contentDetails",
                id=channel_id
            ).execute()
            self.quota_used += 1
            
            if not channel_response.get("items"):
                return []
            
            uploads_playlist_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
            
            # Get videos from uploads playlist
            playlist_response = self.youtube.playlistItems().list(
                part="snippet",
                playlistId=uploads_playlist_id,
                maxResults=min(max_results, 50)
            ).execute()
            self.quota_used += 1
            
            video_ids = [item["snippet"]["resourceId"]["videoId"] for item in playlist_response.get("items", [])]
            
            if not video_ids:
                return []
            
            # Get video statistics
            videos_response = self.youtube.videos().list(
                part="snippet,statistics,contentDetails",
                id=",".join(video_ids)
            ).execute()
            self.quota_used += 1
            
            videos = []
            for item in videos_response.get("items", []):
                stats = item["statistics"]
                views = int(stats.get("viewCount", 0))
                likes = int(stats.get("likeCount", 0))
                
                videos.append({
                    "id": item["id"],
                    "title": item["snippet"]["title"],
                    "published": item["snippet"]["publishedAt"],
                    "views": views,
                    "likes": likes,
                    "engagement_rate": likes / views if views > 0 else 0,
                })
            
            return videos
        
        except HttpError as e:
            print(f"YouTube API error: {e}")
            return []


_youtube_client: Optional[YouTubeClient] = None


def get_youtube_client(cookies_file: Optional[str] = None) -> YouTubeClient:
    """Lazily construct and reuse the YouTube client.

    This avoids import-time failures (e.g., missing API keys) so the rest of
    the app can show a friendly configuration error first.
    
    Args:
        cookies_file: Path to YouTube cookies.txt file for caption extraction
    """
    global _youtube_client
    if _youtube_client is None:
        _youtube_client = YouTubeClient(cookies_file=cookies_file)
    return _youtube_client


def _videos_to_public_dicts(videos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert internal video dicts to a stable, JSON-serializable schema."""
    public: List[Dict[str, Any]] = []
    for v in videos:
        public.append(
            {
                "id": v.get("id"),
                "title": v.get("title"),
                "channel_id": v.get("channel_id"),
                "channel_name": v.get("channel_name"),
                "published": v.get("published"),
                "duration_seconds": int(v.get("duration_seconds", 0) or 0),
                "views": int(v.get("views", 0) or 0),
                "likes": int(v.get("likes", 0) or 0),
                "comments": int(v.get("comments", 0) or 0),
                "engagement_rate": float(v.get("engagement_rate", 0.0) or 0.0),
                "tags": v.get("tags", []),
            }
        )
    return public


def compute_content_gap_metrics(topic: str, max_results: int = 50) -> Dict[str, Any]:
    """Compute long-form vs short-form gap metrics as a structured dict."""
    youtube_client = get_youtube_client()

    longform = youtube_client.search_videos(
        query=topic,
        max_results=max_results,
        order="viewCount",
        duration="medium",
    )

    shortform_all = youtube_client.search_videos(
        query=topic,
        max_results=max_results,
        order="viewCount",
        duration="short",
    )
    shortform = [v for v in shortform_all if v.get("duration_seconds", 0) <= SHORT_FORM_DURATION]

    if not longform:
        return {
            "topic": topic,
            "viable": False,
            "reason": "insufficient_longform",
        }

    lf_views = sum(int(v.get("views", 0) or 0) for v in longform)
    lf_avg_engagement = (
        sum(float(v.get("engagement_rate", 0.0) or 0.0) for v in longform) / max(len(longform), 1)
    )
    sf_count = len(shortform)
    sf_views = sum(int(v.get("views", 0) or 0) for v in shortform) if shortform else 0

    demand_score = min(lf_views / 1_000_000, 10)
    gap_score = max(0.0, 10.0 - (sf_count / 5.0))
    engagement_score = min((lf_avg_engagement / max(MIN_ENGAGEMENT_RATE, 1e-9)) * 10.0, 10.0)

    used_weights = {
        "longform_demand": float(SCORING_WEIGHTS.get("longform_demand", 0.0)),
        "shortform_gap": float(SCORING_WEIGHTS.get("shortform_gap", 0.0)),
        "engagement": float(SCORING_WEIGHTS.get("engagement", 0.0)),
    }
    weight_total = sum(used_weights.values()) or 1.0
    opportunity_score = (
        demand_score * (used_weights["longform_demand"] / weight_total)
        + gap_score * (used_weights["shortform_gap"] / weight_total)
        + engagement_score * (used_weights["engagement"] / weight_total)
    )

    return {
        "topic": topic,
        "viable": True,
        "longform": {
            "videos_found": len(longform),
            "total_views": lf_views,
            "avg_engagement": lf_avg_engagement,
            "top_channel": longform[0].get("channel_name") if longform else None,
        },
        "shortform": {
            "shorts_found": sf_count,
            "total_views": sf_views,
        },
        "scores": {
            "opportunity": float(round(opportunity_score, 3)),
            "demand": float(round(demand_score, 3)),
            "gap": float(round(gap_score, 3)),
            "engagement": float(round(engagement_score, 3)),
        },
    }


@tool
def search_longform_content(query: str, max_results: int = 50) -> str:
    """
    Search for long-form YouTube content (videos over 4 minutes).
    Use this to find popular long-form content in a topic area.
    
    Args:
        query: The search query (e.g., "sci-fi facts", "history mysteries")
        max_results: Maximum number of results to return (default 50)
    
    Returns:
        Summary of found videos with statistics
    """
    youtube_client = get_youtube_client()
    videos = youtube_client.search_videos(
        query=query,
        max_results=max_results,
        order="viewCount",
        duration="medium",  # 4-20 minutes
    )
    
    if not videos:
        return f"No long-form videos found for query: {query}"
    
    # Calculate statistics
    total_views = sum(v["views"] for v in videos)
    avg_views = total_views / len(videos) if videos else 0
    avg_engagement = sum(v["engagement_rate"] for v in videos) / len(videos) if videos else 0
    
    # Get unique channels
    channels = {}
    for v in videos:
        channel_id = v["channel_id"]
        if channel_id not in channels:
            channels[channel_id] = {
                "name": v["channel_name"],
                "videos": 0,
                "total_views": 0,
            }
        channels[channel_id]["videos"] += 1
        channels[channel_id]["total_views"] += v["views"]
    
    top_channels = sorted(
        channels.values(),
        key=lambda x: x["total_views"],
        reverse=True
    )[:5]
    
    # Top videos
    top_videos = sorted(videos, key=lambda x: x["views"], reverse=True)[:5]
    
    result = f"""Long-form Content Analysis for: "{query}"
    
Found {len(videos)} videos
Total Views: {total_views:,}
Average Views per Video: {avg_views:,.0f}
Average Engagement Rate: {avg_engagement:.2%}

Top 5 Channels:
"""
    for i, ch in enumerate(top_channels, 1):
        result += f"{i}. {ch['name']} - {ch['videos']} videos, {ch['total_views']:,} views\n"
    
    result += "\nTop 5 Videos:\n"
    for i, v in enumerate(top_videos, 1):
        result += f"{i}. {v['title'][:60]}... - {v['views']:,} views ({v['engagement_rate']:.2%} engagement)\n"
    
    return result


@tool
def fetch_videos_corpus(query: str, kind: Literal["longform", "shortform"] = "longform", max_results: int = 50) -> str:
    """Return a structured JSON corpus of videos for downstream subtopic mining.

    Args:
        query: Search query (e.g., "science fiction facts")
        kind: "longform" (4-20 min) or "shortform" (<= 4 min, filtered to <=60s)
        max_results: Max results to request (<=50)

    Returns:
        JSON string with {query, kind, videos: [...], summary: {...}}
    """
    youtube_client = get_youtube_client()

    if kind == "longform":
        videos = youtube_client.search_videos(
            query=query,
            max_results=max_results,
            order="viewCount",
            duration="medium",
        )
    else:
        videos_all = youtube_client.search_videos(
            query=query,
            max_results=max_results,
            order="viewCount",
            duration="short",
        )
        videos = [v for v in videos_all if v.get("duration_seconds", 0) <= SHORT_FORM_DURATION]

    public_videos = _videos_to_public_dicts(videos)
    total_views = sum(v["views"] for v in public_videos)
    avg_views = total_views / max(len(public_videos), 1)
    avg_engagement = sum(v["engagement_rate"] for v in public_videos) / max(len(public_videos), 1)

    payload = {
        "query": query,
        "kind": kind,
        "videos": public_videos,
        "summary": {
            "videos": len(public_videos),
            "total_views": total_views,
            "avg_views": avg_views,
            "avg_engagement": avg_engagement,
        },
    }
    return json.dumps(payload, ensure_ascii=False)


@tool
def search_shortform_content(query: str, max_results: int = 50) -> str:
    """
    Search for short-form YouTube content (Shorts - videos under 60 seconds).
    Use this to assess competition in the short-form space.
    
    Args:
        query: The search query (e.g., "sci-fi facts", "history mysteries")
        max_results: Maximum number of results to return (default 50)
    
    Returns:
        Summary of found short-form videos with statistics
    """
    youtube_client = get_youtube_client()
    videos = youtube_client.search_videos(
        query=query,
        max_results=max_results,
        order="viewCount",
        duration="short",  # Under 4 minutes
    )
    
    # Filter to only shorts (under 60 seconds)
    shorts = [v for v in videos if v["duration_seconds"] <= SHORT_FORM_DURATION]
    
    if not shorts:
        return f"No short-form content found for query: {query}. This indicates a potential gap!"
    
    # Calculate statistics
    total_views = sum(v["views"] for v in shorts)
    avg_views = total_views / len(shorts) if shorts else 0
    avg_engagement = sum(v["engagement_rate"] for v in shorts) / len(shorts) if shorts else 0
    
    # Get unique channels
    unique_channels = len(set(v["channel_id"] for v in shorts))
    
    result = f"""Short-form Content Analysis for: "{query}"
    
Found {len(shorts)} shorts (out of {len(videos)} short videos searched)
Unique Channels: {unique_channels}
Total Views: {total_views:,}
Average Views per Short: {avg_views:,.0f}
Average Engagement Rate: {avg_engagement:.2%}

Competition Level: {"LOW" if len(shorts) < 20 else "MEDIUM" if len(shorts) < 50 else "HIGH"}
"""
    
    if len(shorts) > 0:
        top_shorts = sorted(shorts, key=lambda x: x["views"], reverse=True)[:5]
        result += "\nTop 5 Shorts:\n"
        for i, v in enumerate(top_shorts, 1):
            result += f"{i}. {v['title'][:60]}... - {v['views']:,} views\n"
    
    return result


@tool
def analyze_channel(channel_id: str) -> str:
    """
    Analyze a specific YouTube channel to understand their content strategy.
    
    Args:
        channel_id: YouTube channel ID
    
    Returns:
        Channel analysis with subscriber count, video performance, and topics
    """
    youtube_client = get_youtube_client()
    channel_info = youtube_client.get_channel_info(channel_id)
    
    if not channel_info:
        return f"Could not find channel with ID: {channel_id}"
    
    recent_videos = youtube_client.get_channel_videos(channel_id, max_results=20)
    
    result = f"""Channel Analysis: {channel_info['name']}

Subscribers: {channel_info['subscribers']:,}
Total Views: {channel_info['total_views']:,}
Total Videos: {channel_info['video_count']:,}
Average Views per Video: {channel_info['total_views'] / max(channel_info['video_count'], 1):,.0f}

Recent Video Performance (last 20 videos):
"""
    
    if recent_videos:
        avg_views = sum(v["views"] for v in recent_videos) / len(recent_videos)
        avg_engagement = sum(v["engagement_rate"] for v in recent_videos) / len(recent_videos)
        
        result += f"Average Views: {avg_views:,.0f}\n"
        result += f"Average Engagement: {avg_engagement:.2%}\n\n"
        
        result += "Top 5 Recent Videos:\n"
        top_videos = sorted(recent_videos, key=lambda x: x["views"], reverse=True)[:5]
        for i, v in enumerate(top_videos, 1):
            result += f"{i}. {v['title'][:60]}... - {v['views']:,} views\n"
    
    return result


@tool
def compare_content_gap(topic: str) -> str:
    """
    Compare long-form vs short-form content for a topic to identify gaps.
    This is the main tool for finding content opportunities.
    
    Args:
        topic: The topic to analyze (e.g., "sci-fi facts")
    
    Returns:
        Gap analysis with opportunity score
    """
    print(f"Analyzing content gap for: {topic}")
    
    metrics = compute_content_gap_metrics(topic=topic, max_results=50)
    if not metrics.get("viable", False):
        return f"Topic '{topic}' has insufficient long-form content. Not a viable topic."

    lf = metrics["longform"]
    sf = metrics["shortform"]
    scores = metrics["scores"]

    result = f"""Content Gap Analysis: "{topic}"

LONG-FORM CONTENT:
    Videos Found: {lf['videos_found']}
    Total Views: {lf['total_views']:,}
    Avg Engagement: {lf['avg_engagement']:.2%}
    Top Channel: {lf['top_channel'] or 'N/A'}

SHORT-FORM CONTENT:
    Shorts Found: {sf['shorts_found']}
    Total Views: {sf['total_views']:,}
    Competition Level: {"LOW" if sf['shorts_found'] < 20 else "MEDIUM" if sf['shorts_found'] < 50 else "HIGH"}

OPPORTUNITY SCORE: {scores['opportunity']:.1f}/10
    Demand Score: {scores['demand']:.1f}/10 (based on long-form views)
    Gap Score: {scores['gap']:.1f}/10 (based on short-form competition)
    Engagement Score: {scores['engagement']:.1f}/10 (based on long-form engagement)

RECOMMENDATION: """

    if scores["opportunity"] >= 7:
        result += "[HIGH] HIGH OPPORTUNITY - Strong demand with low short-form competition"
    elif scores["opportunity"] >= 5:
        result += "[MED] MEDIUM OPPORTUNITY - Moderate potential, research sub-topics"
    else:
        result += "[LOW] LOW OPPORTUNITY - Either low demand or high competition"

    return result
