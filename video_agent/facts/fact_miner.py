"""Fact mining pipeline: Extract structured facts from video captions and metadata.

This module provides tools to:
1. Extract facts from YouTube video captions using LLM
2. Mine video titles/descriptions for fact patterns
3. Score facts based on video engagement
4. Store facts in the FactStore
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from ..config import make_llm
from ..tools.youtube_tools import get_youtube_client
from ..utils.json_utils import safe_json_loads
from .fact_store import FactStore
from .caption_cache import CaptionCache


FACT_EXTRACTION_PROMPT = """You are a fact extraction specialist. Extract discrete, interesting, specific facts from the provided video transcript text.

CRITICAL RULES:
1. Extract ACTUAL FACTS, not meta-information about the video
2. Each fact must be specific and informative (e.g., "The Death Star's superlaser required 24 hours to recharge" NOT "The Death Star has many facts")
3. Focus on interesting trivia, behind-the-scenes info, or surprising details
4. Each fact should be a complete, standalone statement
5. Preserve specific numbers, dates, names, and details
6. Remove filler words and conversational language
7. If a claim seems uncertain, prepend "Reportedly," or "According to sources,"
8. Maximum 15 facts per video

EXAMPLES OF GOOD FACTS:
✓ "The Death Star's superlaser required 24 hours to recharge between firing"
✓ "Boba Fett's armor originally belonged to the Mandalorian Jaster Mereel"
✓ "George Lucas originally named Luke Skywalker as 'Luke Starkiller'"

EXAMPLES OF BAD META-FACTS (DO NOT EXTRACT):
✗ "There are 101 facts about the Death Star"
✗ "Boba Fett has 10 interesting pieces of trivia"
✗ "This video contains Easter eggs"

OUTPUT FORMAT:
Return a JSON array of fact objects:
[
  {{
    "fact_text": "The actual interesting fact statement",
    "keywords": ["keyword1", "keyword2"],
    "confidence": "high|medium|low"
  }}
]

TEXT TO ANALYZE:
{text}
"""


TITLE_FACT_MINING_PROMPT = """Extract potential facts from these video titles. Many titles hint at specific facts.

EXAMPLES:
- "10 Star Wars Facts You Didn't Know" → likely contains 10 facts
- "Why Yoda's Species Is Still A Mystery" → fact about Yoda's species being unnamed
- "The Hidden Meaning of Darth Vader's Name" → fact about name etymology

RULES:
1. Extract implied facts from titles
2. Keep them general (don't hallucinate specifics)
3. Mark confidence as "title_hint" to indicate needs verification

VIDEO TITLES:
{titles}

Return JSON array of fact objects with fact_text, keywords, and confidence.
"""


class FactMiner:
    """Extracts and stores facts from YouTube videos."""

    def __init__(self, fact_store: Optional[FactStore] = None, caption_cache: Optional[CaptionCache] = None, cookies_file: Optional[str] = None):
        """Initialize fact miner.

        Args:
            fact_store: FactStore instance. If None, creates a new one.
            caption_cache: CaptionCache instance. If None, creates a new one.
            cookies_file: Path to YouTube cookies.txt file for caption extraction.
        """
        self.fact_store = fact_store or FactStore()
        self.caption_cache = caption_cache or CaptionCache()
        self.llm = make_llm(temperature=0.3)
        self.youtube_client = get_youtube_client(cookies_file=cookies_file)

    def extract_facts_from_text(
        self,
        text: str,
        max_facts: int = 15,
    ) -> List[Dict[str, Any]]:
        """Extract facts from text using LLM.

        Args:
            text: Text to analyze (captions, transcript, etc.)
            max_facts: Maximum facts to extract

        Returns:
            List of fact dicts with fact_text, keywords, confidence
        """
        if not text or len(text.strip()) < 100:
            return []

        # Truncate very long texts to avoid token limits
        max_chars = 15000
        if len(text) > max_chars:
            text = text[:max_chars] + "... [truncated]"

        prompt = FACT_EXTRACTION_PROMPT.format(text=text)

        messages = [
            SystemMessage(content="You are a fact extraction specialist. Return only valid JSON."),
            HumanMessage(content=prompt),
        ]

        try:
            response = self.llm.invoke(messages)
            response_text = str(response.content).strip()
            
            # Debug output
            print(f"    LLM response length: {len(response_text)} chars")
            
            facts = safe_json_loads(response_text)

            if not isinstance(facts, list):
                print(f"    Warning: LLM returned {type(facts)} instead of list")
                return []

            # Validate and limit
            valid_facts = []
            for fact in facts[:max_facts]:
                if isinstance(fact, dict) and "fact_text" in fact:
                    valid_facts.append({
                        "fact_text": str(fact["fact_text"]).strip(),
                        "keywords": fact.get("keywords", []),
                        "confidence": fact.get("confidence", "medium"),
                    })

            print(f"    Validated {len(valid_facts)} facts")
            return valid_facts

        except Exception as e:
            print(f"    Error extracting facts: {e}")
            import traceback
            traceback.print_exc()
            return []

    def mine_video_captions(
        self,
        video_id: str,
        topic_id: str,
        subtopic_id: Optional[str] = None,
        store_facts: bool = True,
    ) -> Dict[str, Any]:
        """Mine facts from a video's captions.

        Args:
            video_id: YouTube video ID
            topic_id: Topic identifier for fact storage
            subtopic_id: Optional subtopic identifier
            store_facts: Whether to store facts in fact store

        Returns:
            Dict with extracted facts and metadata
        """
        # Check cache first
        caption_data = self.caption_cache.get(video_id)
        if caption_data:
            print(f"  [OK] Using cached captions")
        else:
            # Get captions from YouTube
            caption_data = self.youtube_client.get_video_captions(video_id)
            
            # Cache successful extractions
            if caption_data:
                self.caption_cache.set(video_id, caption_data)
                print(f"  [OK] Captions extracted and cached")

        if not caption_data:
            print(f"  [SKIP] Captions unavailable (disabled, IP blocked, or no captions)")
            return {
                "video_id": video_id,
                "success": False,
                "reason": "captions_unavailable",
                "facts": [],
            }

        # Extract facts
        print(f"  Caption length: {len(caption_data['text'])} chars")
        facts = self.extract_facts_from_text(caption_data["text"])
        print(f"  Extracted {len(facts)} facts from captions")

        # Get video metadata for engagement scoring
        video_info = None
        try:
            videos = self.youtube_client.search_videos(
                query=f"video_id:{video_id}",
                max_results=1
            )
            if videos:
                video_info = videos[0]
        except:
            pass

        # Calculate engagement score
        engagement_score = 5.0  # default
        if video_info:
            views = video_info.get("views", 0)
            engagement_rate = video_info.get("engagement_rate", 0)

            # Score based on views and engagement
            view_score = min(10.0, (views / 100000) * 5)
            engagement_multiplier = min(2.0, (engagement_rate / 0.02) * 1.5)
            engagement_score = min(10.0, view_score * engagement_multiplier)

        # Store facts
        stored_ids = []
        if store_facts and facts:
            source = {
                "type": "youtube_captions",
                "video_id": video_id,
                "video_url": f"https://youtube.com/watch?v={video_id}",
            }
            if video_info:
                source.update({
                    "title": video_info.get("title"),
                    "views": video_info.get("views"),
                    "engagement_rate": video_info.get("engagement_rate"),
                })

            for fact in facts:
                fact_id = self.fact_store.add_fact(
                    fact_text=fact["fact_text"],
                    topic_id=topic_id,
                    subtopic_id=subtopic_id,
                    sources=[source],
                    engagement_score=engagement_score,
                    verified=False,
                    keywords=fact.get("keywords", []),
                    metadata={"confidence": fact.get("confidence", "medium")},
                )
                stored_ids.append(fact_id)

        return {
            "video_id": video_id,
            "success": True,
            "facts_extracted": len(facts),
            "facts": facts,
            "stored_fact_ids": stored_ids,
            "engagement_score": engagement_score,
        }

    def mine_video_titles(
        self,
        videos: List[Dict[str, Any]],
        topic_id: str,
        subtopic_id: Optional[str] = None,
        store_facts: bool = True,
    ) -> Dict[str, Any]:
        """Extract fact hints from video titles.

        Useful for quick mining without caption download.

        Args:
            videos: List of video dicts with at least 'title' field
            topic_id: Topic identifier
            subtopic_id: Optional subtopic
            store_facts: Whether to store facts

        Returns:
            Dict with extraction results
        """
        titles = [v.get("title", "") for v in videos if v.get("title")]

        if not titles:
            return {"success": False, "reason": "no_titles", "facts": []}

        titles_text = "\n".join([f"- {t}" for t in titles[:50]])  # Limit to 50

        prompt = TITLE_FACT_MINING_PROMPT.format(titles=titles_text)

        messages = [
            SystemMessage(content="You are a fact extraction specialist. Return only valid JSON."),
            HumanMessage(content=prompt),
        ]

        try:
            response = self.llm.invoke(messages)
            facts = safe_json_loads(str(response.content))

            if not isinstance(facts, list):
                return {"success": False, "reason": "invalid_response", "facts": []}

            # Calculate average engagement from videos
            avg_engagement = 5.0
            if videos:
                view_scores = []
                for v in videos:
                    views = v.get("views", 0)
                    if views > 0:
                        view_scores.append(min(10.0, (views / 100000) * 5))
                if view_scores:
                    avg_engagement = sum(view_scores) / len(view_scores)

            # Store facts
            stored_ids = []
            if store_facts:
                for fact in facts:
                    if not isinstance(fact, dict) or "fact_text" not in fact:
                        continue

                    fact_id = self.fact_store.add_fact(
                        fact_text=fact["fact_text"],
                        topic_id=topic_id,
                        subtopic_id=subtopic_id,
                        sources=[{
                            "type": "video_title_hint",
                            "sample_titles": titles[:5],
                        }],
                        engagement_score=avg_engagement * 0.7,  # Lower confidence
                        verified=False,
                        keywords=fact.get("keywords", []),
                        metadata={"confidence": "title_hint"},
                    )
                    stored_ids.append(fact_id)

            return {
                "success": True,
                "facts_extracted": len(facts),
                "facts": facts,
                "stored_fact_ids": stored_ids,
            }

        except Exception as e:
            print(f"Error mining titles: {e}")
            return {"success": False, "reason": str(e), "facts": []}

    def mine_top_videos(
        self,
        topic_query: str,
        topic_id: str,
        subtopic_id: Optional[str] = None,
        max_videos: int = 5,
        use_captions: bool = True,
    ) -> Dict[str, Any]:
        """Mine facts from top-performing videos on a topic.

        Args:
            topic_query: Search query for videos
            topic_id: Topic identifier
            subtopic_id: Optional subtopic
            max_videos: Number of videos to mine
            use_captions: Whether to download and mine captions

        Returns:
            Dict with mining results and statistics
        """
        # Search for top videos
        videos = self.youtube_client.search_videos(
            query=topic_query,
            max_results=max_videos,
            order="viewCount",
            duration="medium",  # Long-form content
        )

        if not videos:
            return {
                "success": False,
                "reason": "no_videos_found",
                "total_facts": 0,
            }

        results = {
            "topic_query": topic_query,
            "videos_found": len(videos),
            "videos_mined": 0,
            "total_facts": 0,
            "video_results": [],
        }

        # Mine captions if requested
        if use_captions:
            for idx, video in enumerate(videos):
                video_id = video.get("id")
                if not video_id:
                    continue

                print(f"Mining captions from video {idx+1}/{len(videos)}: {video.get('title', video_id)}")
                result = self.mine_video_captions(
                    video_id=video_id,
                    topic_id=topic_id,
                    subtopic_id=subtopic_id,
                    store_facts=True,
                )

                if result["success"]:
                    results["videos_mined"] += 1
                    results["total_facts"] += result["facts_extracted"]
                else:
                    print(f"  Skipped: {result.get('reason', 'unknown')}")

                results["video_results"].append(result)
                
                # Rate limiting: wait 10 seconds between requests to avoid IP blocking
                # (skip delay after last video)
                if idx < len(videos) - 1:
                    print(f"  [WAIT] Rate limiting: waiting 10 seconds...")
                    time.sleep(10)

        # DISABLED: Title mining produces meta-facts, not actual facts
        # We now rely only on caption mining for quality
        
        results["success"] = True

        return results
