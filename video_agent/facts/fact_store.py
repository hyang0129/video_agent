"""SQLite-backed fact storage with RAG capabilities.

Provides structured storage for facts mined from videos and external sources,
with query capabilities for script generation.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid


class FactStore:
    """Persistent fact storage with semantic query capabilities."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize fact store.

        Args:
            db_path: Path to SQLite database. If None, uses default in results/facts.db
        """
        if db_path is None:
            db_path = str(Path(__file__).parent.parent.parent / "results" / "facts.db")

        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Facts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                fact_id TEXT PRIMARY KEY,
                topic_id TEXT NOT NULL,
                subtopic_id TEXT,
                fact_text TEXT NOT NULL,
                sources JSON NOT NULL,
                engagement_score REAL DEFAULT 0.0,
                verified BOOLEAN DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                keywords TEXT,
                metadata JSON
            )
        """)

        # Indexes for fast queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_topic 
            ON facts(topic_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_subtopic 
            ON facts(topic_id, subtopic_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_engagement 
            ON facts(engagement_score DESC)
        """)

        conn.commit()
        conn.close()

    def add_fact(
        self,
        fact_text: str,
        topic_id: str,
        sources: List[Dict[str, Any]],
        subtopic_id: Optional[str] = None,
        engagement_score: float = 0.0,
        verified: bool = False,
        keywords: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Add a fact to the store.

        Args:
            fact_text: The factual claim or statement.
            topic_id: Topic identifier (e.g., "star_wars").
            sources: List of source dicts with type, url, video_id, etc.
            subtopic_id: Optional subtopic identifier.
            engagement_score: Score based on video engagement (0-10).
            verified: Whether fact has been externally verified.
            keywords: Optional list of keywords for search.
            metadata: Optional additional metadata.

        Returns:
            fact_id: Generated unique identifier for the fact.
        """
        fact_id = f"fact_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO facts (
                fact_id, topic_id, subtopic_id, fact_text, sources,
                engagement_score, verified, created_at, updated_at,
                keywords, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fact_id,
                topic_id,
                subtopic_id,
                fact_text,
                json.dumps(sources),
                engagement_score,
                1 if verified else 0,
                now,
                now,
                " ".join(keywords or []),
                json.dumps(metadata or {}),
            ),
        )

        conn.commit()
        conn.close()

        return fact_id

    def query(
        self,
        topic_id: str,
        subtopic_id: Optional[str] = None,
        limit: int = 10,
        min_engagement_score: float = 0.0,
        verified_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Query facts for script generation.

        Args:
            topic_id: Topic to query.
            subtopic_id: Optional subtopic filter.
            limit: Maximum number of facts to return.
            min_engagement_score: Minimum engagement score threshold.
            verified_only: Only return externally verified facts.

        Returns:
            List of fact dicts with all fields.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = """
            SELECT * FROM facts
            WHERE topic_id = ?
            AND engagement_score >= ?
        """
        params: List[Any] = [topic_id, min_engagement_score]

        if subtopic_id:
            query += " AND subtopic_id = ?"
            params.append(subtopic_id)

        if verified_only:
            query += " AND verified = 1"

        query += " ORDER BY engagement_score DESC, created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        facts = []
        for row in rows:
            facts.append(
                {
                    "fact_id": row["fact_id"],
                    "topic_id": row["topic_id"],
                    "subtopic_id": row["subtopic_id"],
                    "fact_text": row["fact_text"],
                    "sources": json.loads(row["sources"]),
                    "engagement_score": row["engagement_score"],
                    "verified": bool(row["verified"]),
                    "created_at": row["created_at"],
                    "keywords": row["keywords"],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                }
            )

        return facts

    def search_by_keyword(
        self,
        keywords: List[str],
        topic_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Search facts by keywords.

        Args:
            keywords: List of keywords to search.
            topic_id: Optional topic filter.
            limit: Maximum results.

        Returns:
            List of matching facts.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Build keyword search condition
        keyword_conditions = " OR ".join(
            ["keywords LIKE ?"] * len(keywords)
        )
        keyword_params = [f"%{kw}%" for kw in keywords]

        query = f"""
            SELECT * FROM facts
            WHERE ({keyword_conditions})
        """
        params: List[Any] = keyword_params

        if topic_id:
            query += " AND topic_id = ?"
            params.append(topic_id)

        query += " ORDER BY engagement_score DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        facts = []
        for row in rows:
            facts.append(
                {
                    "fact_id": row["fact_id"],
                    "topic_id": row["topic_id"],
                    "subtopic_id": row["subtopic_id"],
                    "fact_text": row["fact_text"],
                    "sources": json.loads(row["sources"]),
                    "engagement_score": row["engagement_score"],
                    "verified": bool(row["verified"]),
                }
            )

        return facts

    def get_stats(self, topic_id: Optional[str] = None) -> Dict[str, Any]:
        """Get statistics about stored facts.

        Args:
            topic_id: Optional topic filter.

        Returns:
            Dict with count, verified_count, avg_engagement, etc.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if topic_id:
            cursor.execute(
                """
                SELECT 
                    COUNT(*) as total,
                    SUM(verified) as verified_count,
                    AVG(engagement_score) as avg_engagement,
                    MAX(engagement_score) as max_engagement
                FROM facts
                WHERE topic_id = ?
                """,
                (topic_id,),
            )
        else:
            cursor.execute(
                """
                SELECT 
                    COUNT(*) as total,
                    SUM(verified) as verified_count,
                    AVG(engagement_score) as avg_engagement,
                    MAX(engagement_score) as max_engagement
                FROM facts
                """
            )

        row = cursor.fetchone()
        conn.close()

        return {
            "total_facts": row[0],
            "verified_count": row[1] or 0,
            "avg_engagement_score": round(row[2], 2) if row[2] else 0.0,
            "max_engagement_score": row[3] or 0.0,
        }

    def update_engagement_score(self, fact_id: str, engagement_score: float) -> None:
        """Update engagement score for a fact."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE facts
            SET engagement_score = ?, updated_at = ?
            WHERE fact_id = ?
            """,
            (engagement_score, now, fact_id),
        )

        conn.commit()
        conn.close()

    def mark_verified(self, fact_id: str, verified: bool = True) -> None:
        """Mark a fact as externally verified."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE facts
            SET verified = ?, updated_at = ?
            WHERE fact_id = ?
            """,
            (1 if verified else 0, now, fact_id),
        )

        conn.commit()
        conn.close()
