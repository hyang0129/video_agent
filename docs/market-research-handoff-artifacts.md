# Market Research → Script Generation: Handoff Artifacts

This document defines the *contract* between the Market Research stage and the Script Generation Agent.

Goal: pass only the information necessary to reliably generate scripts that are relevant to the *validated* topics/subtopics (and their constraints), while preserving traceability back to the evidence used during research.

> Principle: **Scripts should be grounded in a Topic Brief, not in the researcher’s raw chat output.**

---

## Why a Structured Handoff

The current market research implementation produces primarily narrative text plus (via tools) underlying video metadata. Narrative text is good for humans, but fragile for downstream automation.

A structured handoff:
- reduces prompt length and ambiguity
- improves reproducibility (same inputs → similar outputs)
- enables evaluation and audit (why was this topic chosen?)
- supports iteration (swap script templates without re-running research)

---

## Artifact Set (What Gets Passed Forward)

### 1) `MarketResearchReport` (batch-level)
**Purpose:** provenance, research scope, and the ranked set of opportunities.

**Consumer:** Script Generation (selects which `TopicBrief` to script), and later Evaluator.

**Must include:**
- report metadata (id, created_at, schema_version)
- the broad category/categories researched
- search strategy summary (queries used, filters, recency windows)
- ranked opportunities list (each points to a `TopicBrief`)
- quotas/costs (so future agents can budget)

**Nice to have:**
- failure notes (rate limits, dead-end queries)
- caching hints (what’s already fetched)

### 2) `TopicBrief` (topic + subtopic cluster)
**Purpose:** the single source of truth for script generation.

**Consumer:** Script Generation Agent.

**Must include:**
- topic + subtopic hierarchy (and the chosen subtopic)
- target content format (e.g., “Did You Know”, “Top X”, “Lore Explained”, “Theory”, “Explainer”)
- opportunity rationale + score breakdown (demand/gap/engagement)
- audience assumptions + positioning (what makes it distinct)
- creative constraints (tone, allowed claims, forbidden angles)
- evidence bundle: list of supporting long-form videos (and optionally short-form scan results)

### 3) `EvidenceBundle` (references)
**Purpose:** traceable grounding without bloating prompts.

**Consumer:** Script Generation (for grounding), Fact Checker (optional), Evaluator (later).

**Must include:**
- a short list of seed videos (IDs + key stats) that justified the topic/subtopic
- optional: the exact search query that produced each seed set

**Best practice:** keep the evidence list *small* (e.g., 5–15 items). The script agent shouldn’t be reading 200 video titles.

### 4) `CreativeSpec` (channel-level defaults)
**Purpose:** stable “brand + production constraints” shared across many scripts.

**Consumer:** Script Generation, Video Generation.

**Examples:**
- platform target (YouTube Shorts / TikTok / Reels)
- target duration (seconds) + pacing
- voice style (first-person vs narrator)
- CTA policy (subscribe, comment prompt)
- compliance constraints (no medical advice, no harassment, etc.)

> If you don’t have this yet, you can still generate scripts from `TopicBrief`, but you’ll want to add `CreativeSpec` soon to avoid per-script drift.

---

## Recommended Schemas (JSON)

### Schema Versioning
- Include `schema_version` on every artifact.
- Prefer semantic versioning (e.g., `1.0.0`).
- Breaking changes: bump major.

### `MarketResearchReport` (recommended)
```json
{
  "schema_version": "1.0.0",
  "report_id": "mr_2026-01-31_scifi_001",
  "created_at": "2026-01-31T00:00:00Z",
  "inputs": {
    "categories": ["science fiction"],
    "min_opportunity_score": 6.0,
    "notes": "Informational content only; avoid trailers/music."
  },
  "research_strategy": {
    "query_patterns": [
      "{category} facts",
      "{category} explained",
      "{category} theories",
      "{category} lore"
    ],
    "filters": {
      "min_longform_views": 100000,
      "min_engagement_rate": 0.02,
      "shorts_max_seconds": 60
    }
  },
  "quota": {
    "youtube_units_used_estimate": 0,
    "cache_enabled": true
  },
  "opportunities": [
    {
      "topic_id": "topic_scifi_facts",
      "topic_name": "Sci‑Fi Facts",
      "top_subtopics": [
        {"subtopic_id": "sub_star_wars_facts", "name": "Star Wars Facts"}
      ],
      "opportunity_score": 7.6,
      "score_breakdown": {
        "longform_demand": 8.2,
        "shortform_gap": 7.4,
        "engagement": 6.8,
        "trend": 6.0
      },
      "topic_brief_ref": "topicbrief_topic_scifi_facts_sub_star_wars_facts.json"
    }
  ],
  "notes_for_next_agent": [
    "Prefer list-style hooks; avoid plot summary."
  ]
}
```

### `TopicBrief` (recommended)
```json
{
  "schema_version": "1.0.0",
  "topic_id": "topic_scifi_facts",
  "subtopic_id": "sub_star_wars_facts",
  "topic": {
    "name": "Sci‑Fi Facts",
    "positioning": "Curiosity-driven, educational sci-fi trivia and lore in punchy Shorts."
  },
  "subtopic": {
    "name": "Star Wars Facts",
    "angle": "Less-known production facts and universe lore with surprise reveals",
    "avoid": ["full plot recaps", "copyrighted clip-dependent jokes"]
  },
  "format": {
    "primary": "Did You Know",
    "secondary": ["Top X About Y"],
    "target_duration_seconds": 45
  },
  "why_this": {
    "opportunity_score": 7.6,
    "rationale": [
      "High long-form engagement on trivia/lore videos",
      "Short-form coverage appears under-saturated for this specific angle"
    ],
    "score_breakdown": {
      "longform_demand": 8.2,
      "shortform_gap": 7.4,
      "engagement": 6.8,
      "trend": 6.0
    }
  },
  "script_constraints": {
    "tone": "energetic, informative",
    "claims_policy": "Use cautious language for uncertain claims; avoid definitive statements without support.",
    "reading_level": "general audience",
    "banned_phrases": ["guaranteed", "definitely true"],
    "cta": "Ask a question at the end to drive comments."
  },
  "evidence": {
    "seed_videos": [
      {
        "id": "VIDEO_ID",
        "title": "Example title",
        "channel_name": "Example channel",
        "views": 123456,
        "likes": 4567,
        "engagement_rate": 0.037
      }
    ],
    "source_queries": ["star wars facts explained"]
  },
  "outputs_expected": {
    "deliverables": [
      "one 45s short script",
      "one alternate hook",
      "one caption",
      "5 hashtags"
    ]
  }
}
```

### `CreativeSpec` (recommended)
```json
{
  "schema_version": "1.0.0",
  "channel": {
    "name": "Short Form Video Agent",
    "platforms": ["youtube_shorts"],
    "voice": "narrator"
  },
  "style": {
    "pacing": "fast",
    "humor": "light",
    "music": "optional",
    "visuals": "kinetic text + b-roll/illustrations"
  },
  "compliance": {
    "no_medical_advice": true,
    "no_hate_or_harassment": true,
    "no_misinformation": true
  }
}
```

---

## Minimal Fields Required for Relevance

If you pass *only* the below, the script generation agent can still reliably stay on-topic:
- `topic.name`
- `subtopic.name` and `subtopic.angle`
- `format.primary` + `target_duration_seconds`
- `why_this.opportunity_score` (and 1–3 bullet rationale)
- `script_constraints` (tone + claims policy)

Everything else improves quality, auditability, and iteration speed.

---

## Cross-Agent Interaction Best Practices

### Contract & Versioning
- **Contract-first:** define schemas before implementing new agents.
- **Version every artifact:** include `schema_version` and a stable `*_id`.
- **Prefer additive changes:** add fields instead of changing meaning.

### Traceability & Grounding
- **Always attach evidence:** include source video IDs/titles/stats that motivated the subtopic.
- **Separate “facts” from “hypotheses”:** if something is inferred (e.g., “gap looks low”), label it as such.
- **Keep provenance metadata:** inputs, queries, timestamps.

### Prompt Hygiene
- **Pass structured artifacts, not transcripts:** avoid sending the full market research narrative as context.
- **Keep it small:** constrain the handoff to what the next agent needs.
- **Explicit objectives and constraints:** the script agent should know what success looks like.

### Determinism & Reproducibility
- **Idempotent artifacts:** re-running should produce a new report ID, but comparable structure.
- **Stable units:** seconds, 0–10 scoring, ISO timestamps.
- **Record scoring weights and thresholds:** otherwise scores are not comparable over time.

### Failure Modes & Validation
- **Validate schema at boundaries:** fail fast if required fields are missing.
- **Graceful degradation:** if evidence is thin, the script agent should shorten claims and increase hedging.
- **Quality gates:** evaluator agent (later stage) should check topicality, clarity, and policy compliance.

### Security & Privacy
- **No secrets in artifacts:** never include API keys, tokens, or user credentials.
- **Sanitize logs:** artifacts may be stored in `results/` and shared.

---

## Where to Store These Artifacts

Recommended:
- Write artifacts to `results/` as JSON.
- One folder per run, e.g. `results/mr_2026-01-31_scifi_001/`.
- Include:
  - `market_research_report.json`
  - `topicbrief_*.json`
  - `creative_spec.json` (if stable, can live in config instead)

---

## Do We Need a Separate Video Generation Agent?

Yes—splitting Script Generation and Video Generation is usually the better design.

### Why Separate
- **Different optimization targets:** scripts optimize for narrative + hooks; video generation optimizes for visuals, timing, and production constraints.
- **Different toolchains:** script generation is mostly text; video generation involves assets, TTS, subtitles, editing, rendering.
- **Cleaner interfaces:** video generation should consume a *structured* `VideoPlan` derived from the script.

### Suggested Agent Lineup
1. **Market Research Agent** → outputs `MarketResearchReport` + `TopicBrief`
2. **Script Generation Agent** → outputs `ScriptPackage`
3. **Video Generation Agent** → outputs `VideoPackage` (rendered video + project files)
4. **Evaluation Agent** (optional but valuable) → scores topicality, pacing, policy, and predicts retention

### Recommended Script → Video Handoff (future)
Introduce a `VideoPlan` artifact:
- scenes with timestamps
- on-screen text per scene
- asset prompts/requirements per scene (b-roll type, image style)
- TTS voice + pacing
- subtitle style

This keeps the video generator deterministic and makes it easier to swap renderers (CapCut templates, MoviePy, FFmpeg, After Effects automation, etc.).
