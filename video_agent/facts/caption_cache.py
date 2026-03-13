"""Caption caching system to avoid redundant YouTube requests."""

import json
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime


class CaptionCache:
    """File-based cache for YouTube video captions."""

    def __init__(self, cache_dir: Optional[Path] = None):
        """Initialize caption cache.

        Args:
            cache_dir: Directory to store cached captions. Defaults to results/captions/
        """
        if cache_dir is None:
            from ..config import RESULTS_DIR
            cache_dir = RESULTS_DIR / "captions"
        
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, video_id: str) -> Path:
        """Get cache file path for a video ID."""
        return self.cache_dir / f"{video_id}.json"

    def get(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached captions for a video.

        Args:
            video_id: YouTube video ID

        Returns:
            Caption data dict or None if not cached
        """
        cache_path = self._get_cache_path(video_id)
        
        if not cache_path.exists():
            return None

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("caption_data")
        except (json.JSONDecodeError, IOError):
            return None

    def set(self, video_id: str, caption_data: Dict[str, Any]) -> bool:
        """Store captions in cache.

        Args:
            video_id: YouTube video ID
            caption_data: Caption data from youtube API

        Returns:
            True if successfully cached
        """
        cache_path = self._get_cache_path(video_id)

        cache_entry = {
            "video_id": video_id,
            "cached_at": datetime.now().isoformat(),
            "caption_data": caption_data,
        }

        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_entry, f, indent=2, ensure_ascii=False)
            return True
        except IOError as e:
            print(f"Failed to cache captions for {video_id}: {e}")
            return False

    def has(self, video_id: str) -> bool:
        """Check if captions are cached for a video.

        Args:
            video_id: YouTube video ID

        Returns:
            True if cached
        """
        return self._get_cache_path(video_id).exists()

    def delete(self, video_id: str) -> bool:
        """Remove cached captions for a video.

        Args:
            video_id: YouTube video ID

        Returns:
            True if deleted, False if not found
        """
        cache_path = self._get_cache_path(video_id)
        
        if cache_path.exists():
            cache_path.unlink()
            return True
        return False

    def clear(self) -> int:
        """Clear all cached captions.

        Returns:
            Number of cache files deleted
        """
        count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
            count += 1
        return count

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with cache stats
        """
        cache_files = list(self.cache_dir.glob("*.json"))
        
        total_size = sum(f.stat().st_size for f in cache_files)
        
        return {
            "cached_videos": len(cache_files),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "cache_dir": str(self.cache_dir),
        }
