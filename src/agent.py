"""Market Research Agent using LangChain.

This module also supports exporting structured cross-agent artifacts to
`results/` for downstream stages (script generation, video generation, etc.).
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Dict, List

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, SystemMessage

from .tools.youtube_tools import (
    search_longform_content,
    search_shortform_content,
    fetch_videos_corpus,
    analyze_channel,
    compare_content_gap,
    compute_content_gap_metrics,
    get_youtube_client,
)
from .config import (
    make_llm,
    MIN_ENGAGEMENT_RATE,
    MIN_VIEWS_LONGFORM,
    RESULTS_DIR,
    SCORING_WEIGHTS,
    SHORT_FORM_DURATION,
)

from .artifacts.io import ensure_run_dir, new_run_id, slugify, write_json, write_text
from .utils.json_utils import safe_json_loads


# Agent prompt
SYSTEM_PROMPT = """You are a Market Research Agent specializing in identifying content opportunities on YouTube.

Your goal is to find topics that:
1. Have strong performance in long-form content (high views, engagement)
2. Are underrepresented in short-form content (Shorts)
3. Focus on informative content styles: "Did You Know", "Top X About Y", "You Won't Believe", "Lore Explained", "Theories"

WORKFLOW:
1. When given a broad category, use fetch_videos_corpus to retrieve a dataset of long-form videos. 
   IMPORTANT: Refine queries to target informational content (e.g., add 'facts', 'explained', 'theories', 'analysis', 'lore') to avoid narrative short films, trailers, or music videos.
2. Identify patterns in successful videos (common topics, channels, formats) from the corpus
3. For promising topics, compare long-form vs short-form presence
4. Calculate opportunity scores and provide recommendations
5. Suggest specific sub-topics to explore

ANALYSIS CRITERIA:
- Long-form demand: Look for videos with 100K+ views
- Engagement: Minimum 2% engagement rate (likes/views)
- Competition: Fewer shorts = bigger opportunity
- Content style: Educational, fact-based, list-format content. Ignore fictional narrative (short films) and music.

OUTPUT FORMAT:
Always provide:
- Clear topic/sub-topic hierarchy
- Specific opportunity scores
- Reasoning for recommendations
- Actionable next steps

Be thorough but efficient with API calls. Use your tools strategically."""


ARTIFACTS_SYSTEM_PROMPT = """You are generating structured market research artifacts for a downstream script-writing agent.

CRITICAL: Return ONLY valid JSON. Do NOT include markdown formatting, code blocks, explanations, or any text outside the JSON object.

The JSON must conform to:

{
    "schema_version": "1.0.0",
    "category": "...",
    "opportunities": [
        {
            "topic_name": "...",
            "topic_query": "...",
            "format_primary": "Did You Know|Top X About Y|Lore Explained|Theories|Explainer",
            "format_secondary": ["..."],
            "positioning": "...",
            "avoid": ["..."],
            "rationale": ["..."],
            "subtopics": [
                {
                    "name": "...",
                    "query": "...",
                    "angle": "...",
                    "avoid": ["..."]
                }
            ]
        }
    ]
}

Rules:
- Provide 3 to 5 opportunities.
- Each opportunity should include 3 to 6 subtopics.
- Keep queries short and informational (add facts/explained/theories/lore if helpful).
- Avoid narrative short films, trailers, music videos.
"""


class MarketResearchAgent:
    """Agent for conducting market research on YouTube content opportunities."""
    
    def __init__(self):
        self.llm = make_llm(temperature=0.2)
        
        # Define tools
        self.tools = [
            search_longform_content,
            search_shortform_content,
            fetch_videos_corpus,
            analyze_channel,
            compare_content_gap,
        ]
        
        # Create prompt template
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        
        # Create agent
        agent = create_tool_calling_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=self.prompt,
        )
        
        # Create executor
        self.agent_executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=True,
            max_iterations=10,
            handle_parsing_errors=True,
        )
    
    def research_category(self, category: str) -> str:
        """
        Research a broad category to identify specific topic opportunities.
        
        Args:
            category: Broad category (e.g., "science", "history", "technology")
        
        Returns:
            Research findings with recommendations
        """
        prompt = f"""Research the '{category}' category on YouTube.

Tasks:
1. Use fetch_videos_corpus to get a list of popular long-form videos. IMPORTANT: Use specific queries like '{category} facts', '{category} explained', '{category} theories', or '{category} lore' to ensure you find informational content rather than just generic videos.
2. Analyze the corpus to identify 3-5 specific sub-topics/clusters that show strong engagement. Ignore general clusters like "Short Films" or "Trailers".
3. For each promising informational sub-topic, assess the short-form content gap.
4. Rank topics by opportunity score.
5. Suggest specific sub-topics for the top opportunities.

Provide a structured analysis with clear recommendations."""
        
        result = self.agent_executor.invoke({"input": prompt})
        return result["output"]
    
    def analyze_topic(self, topic: str) -> str:
        """
        Deep dive analysis of a specific topic.
        
        Args:
            topic: Specific topic (e.g., "sci-fi movie facts")
        
        Returns:
            Detailed topic analysis with sub-topics
        """
        prompt = f"""Analyze the topic: '{topic}'

Tasks:
1. Use compare_content_gap to get the opportunity score
2. Search long-form content to identify patterns in successful videos
3. Identify 5-10 specific sub-topics within this area
4. For top 3 sub-topics, estimate their individual potential
5. Provide content format recommendations

Give me actionable insights for creating short-form content in this topic."""
        
        result = self.agent_executor.invoke({"input": prompt})
        return result["output"]
    
    def find_opportunities(
        self,
        categories: List[str],
        min_score: float = 5.0
    ) -> str:
        """
        Scan multiple categories to find best opportunities.
        
        Args:
            categories: List of categories to research
            min_score: Minimum opportunity score threshold
        
        Returns:
            Top opportunities across all categories
        """
        prompt = f"""Scan these categories for content opportunities: {', '.join(categories)}

For each category:
1. Identify 2-3 promising topics
2. Use compare_content_gap to score each topic
3. Filter for opportunities scoring {min_score}+/10

Then:
- Rank all opportunities by score
- Present top 5 opportunities with details
- For #1 opportunity, list 5 specific sub-topics to pursue

Be efficient - focus on high-potential areas."""
        
        result = self.agent_executor.invoke({"input": prompt})
        return result["output"]
    
    def chat(self, message: str) -> str:
        """
        General chat interface for custom queries.
        
        Args:
            message: User message/query
        
        Returns:
            Agent response
        """
        result = self.agent_executor.invoke({"input": message})
        return result["output"]

    def research_category_artifacts(self, category: str, max_results: int = 50) -> Dict[str, Any]:
        """Research a category and export structured artifacts for downstream agents.

        This method writes a `MarketResearchReport` plus one or more `TopicBrief`
        files under `results/<run_id>/`.

        Args:
            category: Broad category (e.g., "science fiction").
            max_results: Max YouTube results per query (<= 50).

        Returns:
            Dict with keys: run_id, run_dir, report_path, topic_brief_paths, report.
        """
        run_id = new_run_id("mr", category)
        run_dir = ensure_run_dir(RESULTS_DIR, run_id)

        queries = [
            f"{category} facts",
            f"{category} explained",
        ]

        corpuses: List[Dict[str, Any]] = []
        merged_by_id: Dict[str, Dict[str, Any]] = {}

        for q in queries:
            corpus_text = fetch_videos_corpus.invoke(
                {"query": q, "kind": "longform", "max_results": min(max_results, 50)}
            )
            corpus = safe_json_loads(str(corpus_text))
            if isinstance(corpus, dict):
                corpuses.append(corpus)
                for video in corpus.get("videos", []) or []:
                    video_id = str(video.get("id") or "")
                    if not video_id:
                        continue
                    current = merged_by_id.get(video_id)
                    if current is None or int(video.get("views", 0) or 0) > int(current.get("views", 0) or 0):
                        merged_by_id[video_id] = video

        merged_videos = sorted(
            merged_by_id.values(), key=lambda v: int(v.get("views", 0) or 0), reverse=True
        )
        top_videos = merged_videos[:30]

        # Ask the LLM to propose topic clusters and subtopics.
        llm_payload = {
            "category": category,
            "inputs": {
                "queries": queries,
                "videos": [
                    {
                        "id": v.get("id"),
                        "title": v.get("title"),
                        "channel_name": v.get("channel_name"),
                        "views": v.get("views"),
                        "engagement_rate": v.get("engagement_rate"),
                        "tags": v.get("tags"),
                    }
                    for v in top_videos
                ],
            },
        }

        messages = [
            SystemMessage(content=ARTIFACTS_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    "Propose opportunities and subtopics for this category.\n"
                    "Use the provided video titles as evidence of what performs.\n"
                    "Return ONLY a JSON object (no markdown, no explanations).\n\n"
                    "INPUTS_JSON:\n" + json.dumps(llm_payload, ensure_ascii=False)
                )
            ),
        ]

        print("\n[LLM] Asking LLM to propose topic opportunities...")
        response = self.llm.invoke(messages)
        raw_response = str(response.content)
        
        # Save raw response for debugging
        debug_path = run_dir / "llm_proposal_raw.txt"
        write_text(debug_path, raw_response)
        print(f"[debug] Saved raw LLM response to: {debug_path}")
        
        try:
            proposal = safe_json_loads(raw_response)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[WARN] LLM response parsing failed: {e}")
            print(f"[WARN] Response preview: {raw_response[:500]}...")
            print("[WARN] Falling back to heuristic topic extraction...")
            proposal = None

        opportunities_in: List[Dict[str, Any]] = []
        if isinstance(proposal, dict):
            opportunities_in = list(proposal.get("opportunities", []) or [])
        
        # Fallback: if LLM didn't return valid opportunities, create a basic one from the category
        if not opportunities_in:
            print("[WARN] Creating fallback opportunity from category...")
            opportunities_in = [
                {
                    "topic_name": f"{category.title()} Facts",
                    "topic_query": f"{category} facts explained",
                    "format_primary": "Did You Know",
                    "format_secondary": ["Top X About Y"],
                    "positioning": f"Curiosity-driven {category} trivia and facts",
                    "avoid": ["plot summaries", "trailers"],
                    "rationale": ["High engagement potential in informational content"],
                    "subtopics": [
                        {
                            "name": f"Popular {category.title()} Topics",
                            "query": f"{category} explained",
                            "angle": "Educational and engaging explanations",
                            "avoid": ["overly technical jargon"],
                        }
                    ],
                }
            ]

        # Score topics with deterministic metrics.
        scored: List[Dict[str, Any]] = []
        print(f"\n[info] Scoring {len(opportunities_in)} proposed opportunities...")
        for item in opportunities_in:
            if not isinstance(item, dict):
                continue
            topic_query = str(item.get("topic_query") or item.get("topic_name") or item.get("opportunity") or item.get("title") or "").strip()
            if not topic_query:
                continue
            # If no explicit topic_query in schema, the LLM gave a theme title — prefix with
            # the category so YouTube search finds relevant longform content.
            if "topic_query" not in item and category.lower() not in topic_query.lower():
                topic_query = f"{category} {topic_query}"
            print(f"   Scoring: {topic_query}")
            metrics = compute_content_gap_metrics(topic=topic_query, max_results=50)
            if not metrics.get("viable", False):
                print(f"   [SKIP] Not viable (insufficient content)")
                continue
            score = float(metrics["scores"]["opportunity"])
            print(f"   [OK] Score: {score:.1f}/10")
            scored.append({"proposal": item, "metrics": metrics})

        scored.sort(key=lambda x: float(x["metrics"]["scores"]["opportunity"]), reverse=True)
        
        if not scored:
            print("\n[ERROR] No viable opportunities found. Try a different category or check API connectivity.")
            return {
                "run_id": run_id,
                "run_dir": str(run_dir),
                "report_path": None,
                "topic_brief_paths": [],
                "report": None,
            }

        youtube_client = get_youtube_client()
        created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        print(f"\n[OK] Found {len(scored)} viable opportunities. Creating topic briefs...")

        report: Dict[str, Any] = {
            "schema_version": "1.0.0",
            "report_id": run_id,
            "created_at": created_at,
            "inputs": {
                "categories": [category],
                "notes": "Informational content only; avoid narrative short films, trailers, and music.",
            },
            "research_strategy": {
                "query_patterns": queries,
                "filters": {
                    "min_longform_views": MIN_VIEWS_LONGFORM,
                    "min_engagement_rate": MIN_ENGAGEMENT_RATE,
                    "shorts_max_seconds": SHORT_FORM_DURATION,
                },
                "scoring_weights": SCORING_WEIGHTS,
            },
            "quota": {
                "youtube_units_used_estimate": int(getattr(youtube_client, "quota_used", 0) or 0),
            },
            "opportunities": [],
            "notes_for_next_agent": [
                "Prefer curiosity-driven informational hooks.",
                "Avoid plot summaries and clip-dependent jokes.",
            ],
        }

        topic_brief_paths: List[str] = []

        for idx, entry in enumerate(scored[:5], 1):
            proposal_item = entry["proposal"]
            metrics = entry["metrics"]
            scores = metrics.get("scores", {})

            topic_name = str(proposal_item.get("topic_name") or proposal_item.get("topic_query") or "topic")
            topic_id = f"topic_{slugify(topic_name)[:32]}"

            subtopics = list(proposal_item.get("subtopics", []) or [])
            top_subtopic = subtopics[0] if subtopics and isinstance(subtopics[0], dict) else {}
            subtopic_name = str(top_subtopic.get("name") or "subtopic")
            subtopic_id = f"sub_{slugify(subtopic_name)[:32]}"

            topic_brief_filename = f"topicbrief_{topic_id}_{subtopic_id}.json"
            topic_brief_path = run_dir / topic_brief_filename

            # Fetch topic-specific evidence (cached when ENABLE_CACHE=true).
            evidence_videos: List[Dict[str, Any]] = []
            try:
                topic_corpus_text = fetch_videos_corpus.invoke(
                    {
                        "query": str(proposal_item.get("topic_query") or ""),
                        "kind": "longform",
                        "max_results": 15,
                    }
                )
                topic_corpus = safe_json_loads(str(topic_corpus_text))
                if isinstance(topic_corpus, dict):
                    ev = list(topic_corpus.get("videos", []) or [])
                    evidence_videos = [v for v in ev if isinstance(v, dict)][:10]
            except Exception:
                evidence_videos = top_videos[:10]

            topic_brief: Dict[str, Any] = {
                "schema_version": "1.0.0",
                "topic_id": topic_id,
                "subtopic_id": subtopic_id,
                "topic": {
                    "name": topic_name,
                    "positioning": str(proposal_item.get("positioning") or ""),
                },
                "subtopic": {
                    "name": subtopic_name,
                    "angle": str(top_subtopic.get("angle") or ""),
                    "avoid": list(top_subtopic.get("avoid", []) or []),
                },
                "format": {
                    "primary": str(proposal_item.get("format_primary") or "Did You Know"),
                    "secondary": list(proposal_item.get("format_secondary", []) or []),
                    "target_duration_seconds": 45,
                },
                "why_this": {
                    "opportunity_score": float(scores.get("opportunity", 0.0) or 0.0),
                    "rationale": list(proposal_item.get("rationale", []) or []),
                    "score_breakdown": {
                        "longform_demand": float(scores.get("demand", 0.0) or 0.0),
                        "shortform_gap": float(scores.get("gap", 0.0) or 0.0),
                        "engagement": float(scores.get("engagement", 0.0) or 0.0),
                    },
                },
                "script_constraints": {
                    "tone": "energetic, informative",
                    "claims_policy": "Hedge uncertain claims and avoid absolutes without evidence.",
                    "reading_level": "general audience",
                    "cta": "Ask a question at the end to drive comments.",
                },
                "evidence": {
                    "seed_videos": evidence_videos,
                    "source_queries": [
                        str(proposal_item.get("topic_query") or ""),
                        *queries,
                    ],
                },
                "outputs_expected": {
                    "deliverables": ["one 45s short script", "one alternate hook", "one caption", "5 hashtags"],
                },
            }

            write_json(topic_brief_path, topic_brief)
            topic_brief_paths.append(str(topic_brief_path))

            report["opportunities"].append(
                {
                    "rank": idx,
                    "topic_id": topic_id,
                    "topic_name": topic_name,
                    "topic_query": str(proposal_item.get("topic_query") or ""),
                    "top_subtopics": [
                        {"subtopic_id": subtopic_id, "name": subtopic_name}
                    ],
                    "opportunity_score": float(scores.get("opportunity", 0.0) or 0.0),
                    "score_breakdown": {
                        "longform_demand": float(scores.get("demand", 0.0) or 0.0),
                        "shortform_gap": float(scores.get("gap", 0.0) or 0.0),
                        "engagement": float(scores.get("engagement", 0.0) or 0.0),
                    },
                    "topic_brief_ref": topic_brief_filename,
                }
            )

        report_path = run_dir / "market_research_report.json"
        write_json(report_path, report)

        # Also write a short, human-readable summary for quick inspection.
        summary_lines = [
            f"Run: {run_id}",
            f"Category: {category}",
            "",
            "Top Opportunities:",
        ]
        for opp in report["opportunities"]:
            summary_lines.append(
                f"- #{opp['rank']} {opp['topic_name']} (score {opp['opportunity_score']:.1f}/10)"
            )
        write_text(run_dir / "summary.txt", "\n".join(summary_lines) + "\n")

        return {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "report_path": str(report_path),
            "topic_brief_paths": topic_brief_paths,
            "report": report,
        }


def create_agent() -> MarketResearchAgent:
    """Factory function to create and return a MarketResearchAgent instance."""
    return MarketResearchAgent()
