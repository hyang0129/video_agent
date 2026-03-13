# Image Generation Investigation: Complementing Stock Retrieval with AI-Generated Backgrounds

**Date:** March 13, 2026
**Status:** Investigation / Human Review

---

## 1. Problem Statement

The pipeline currently retrieves background images from **Pexels** (primary) and **Wikimedia Commons** (fallback), with solid-color BMP placeholders as a last resort. This has two key limitations:

1. **Generic results** -- Stock photo searches often return loosely-related images. A scene about "Allied soldiers calling any enemy tank a Tiger" returns generic tank photos, not scene-specific imagery.
2. **Search query mismatch** -- The screenplay agent writes `visual.search_queries` optimized for Pexels keyword search, which forces abstract or narrative concepts into stock-photo vocabulary. Some topics simply don't have good stock coverage.

AI image generation would let us produce **scene-specific backgrounds** that match the screenplay's visual description exactly, at low cost.

---

## 2. Current Pipeline (How Images Flow Today)

```
ScreenplayAgent
  writes per-scene: visual.description, visual.search_queries
    |
    v
screenplay_to_script_package()
  maps visual.search_queries -> beat.visual_queries
    |
    v
ScriptImageRetrievalAgent
  builds search queries from visual_queries (or falls back to VO text)
  searches: Pexels -> Wikimedia -> placeholder BMP
  scores candidates by token overlap with script context
    |
    v
VisualAgent
  LLM-based selection of best candidate per scene
  downloads + validates
    |
    v
CompositorAgent -> RenderAgent
```

**Key files:**
- [screenplay_agent.py](../src/screenwriting/screenplay_agent.py) -- writes `visual.description` + `visual.search_queries`
- [screenplay.py](../src/artifacts/screenplay.py) -- `screenplay_to_script_package()` bridge
- [script_image_agent.py](../src/script_image_agent.py) -- retrieval + relevance scoring
- [visual_agent.py](../src/visual_agent.py) -- selection + download
- [image_search_tools.py](../src/tools/image_search_tools.py) -- Pexels/Wikimedia API clients

**What the screenplay already provides per scene:**
```json
{
  "scene_id": "scene_03",
  "vo_line": "Allied soldiers called any enemy tank a Tiger...",
  "visual": {
    "description": "Archival footage of a German Tiger I tank advancing through a European battlefield",
    "mood": "tense",
    "search_queries": ["German Tiger I tank battlefield", "WW2 tank combat Europe"]
  }
}
```

The `visual.description` field is already written as a concrete scene description -- it's essentially an image generation prompt that we currently throw away (only `search_queries` are used downstream).

---

## 3. Image Generation API Options (March 2026 Pricing)

| Provider | Model | Cost/Image | Quality (Elo) | Resolution | Notes |
|----------|-------|-----------|---------------|------------|-------|
| **OpenAI** | GPT Image 1 Mini (low) | **$0.005** | Decent | 1024x1024 | Cheapest option, good for drafts |
| **OpenAI** | GPT Image 1 (medium) | **$0.07** | High | 1024x1536 | Portrait mode available |
| **Google** | Imagen 4 Fast | **$0.02** | High | 1024x1024 | Best quality/price ratio |
| **BFL** | Flux 2 Schnell | **$0.015** | Good | 1024x1024 | Fast, good value |
| **BFL** | Flux 2 Dev | **$0.025** | Very Good | 1024x1024 | ~90% of Pro quality |
| **BFL** | Flux 2 Pro v1.1 | **$0.055** | Top tier (1265) | 1024x1024 | Tied for #1 quality |
| **Stability** | SD 3.5 Large | **$0.025** / free self-host | Good | 1024x1024 | Free if self-hosted |
| Replicate/fal.ai | Flux Schnell | **$0.003** | Good | 1024x1024 | Cheapest via aggregator |

### Cost projection for this pipeline

A typical video has **5-9 scenes**. At the budget end:

| Scenario | Provider | Cost/Video | Cost/100 Videos |
|----------|----------|-----------|-----------------|
| All generated (budget) | GPT Image 1 Mini | $0.04 | $4.00 |
| All generated (quality) | Imagen 4 Fast | $0.14 | $14.00 |
| Hybrid: generate only when stock fails | Imagen 4 Fast | ~$0.06 | ~$6.00 |
| All generated (premium) | Flux 2 Pro | $0.39 | $39.00 |

**Verdict:** Even at quality tier, generating all images for a video costs less than $0.15. This is negligible alongside LLM costs for script generation (~$0.05-0.20/run).

### Recommended providers (in priority order)

1. **OpenAI GPT Image 1** -- Already likely have an API key (`OPENAI_API_KEY`). Portrait (1024x1536) mode maps well to 9:16 vertical. Token-based pricing is transparent. Medium quality at ~$0.07/image is strong.
2. **Google Imagen 4 Fast** -- Best price/quality at $0.02. Requires Google Cloud credentials (we already have `langchain-google-genai` installed).
3. **Flux via fal.ai/Replicate** -- $0.003-0.015/image. Cheapest if budget is paramount. Requires a new API key.

---

## 4. Proposed Changes (Three-Part Plan)

### Part A: Enhance screenplay prompts for image generation

**What:** Update the screenplay agent's system prompt to write `visual.description` as a proper image generation prompt, and add a new `visual.generation_prompt` field that is specifically formatted for AI image generation (style cues, composition, no text).

**Why:** The current `visual.description` is halfway there ("Archival footage of a German Tiger I tank advancing through a European battlefield") but lacks the style/composition cues that image generators need. Stock search queries and generation prompts have different optimal formats.

**Schema change to scene.visual:**
```json
{
  "description": "A German Tiger I tank advancing through a muddy European battlefield, WW2",
  "mood": "tense",
  "search_queries": ["German Tiger I tank battlefield", "WW2 tank combat Europe"],
  "generation_prompt": "Dramatic wide shot of a German Tiger I tank advancing through a muddy European battlefield, overcast sky, smoke in the background, WW2 era, cinematic lighting, photorealistic, vertical composition 9:16",
  "prefer_generated": false
}
```

- `generation_prompt`: Purpose-built for image generation APIs. Includes style, composition, and format cues.
- `prefer_generated`: Hint from the screenplay about whether this scene benefits more from generation (abstract/narrative scenes) vs. stock (concrete real-world subjects).

**Files to change:**
- `src/screenwriting/screenplay_agent.py` -- Update `_WRITE_SYSTEM` and `_REVISE_SYSTEM` prompts
- `src/screenwriting/screenplay_agent.py` -- Update `_coerce_scenes()` to preserve new fields
- `src/artifacts/screenplay.py` -- Update `screenplay_to_script_package()` to forward `generation_prompt`
- `src/screenwriting/screenplay_reviewer.py` -- Add validation for `generation_prompt` quality

**Effort:** Small (~1-2 hours). Mostly prompt engineering + schema plumbing.

---

### Part B: Add image generation provider to the retrieval pipeline

**What:** Add an AI image generation backend alongside Pexels/Wikimedia in the image source chain. The generation provider would use `visual.generation_prompt` (or fall back to `visual.description`) to create scene-specific images.

**Integration strategy -- two options:**

#### Option B1: Generation as fallback (conservative)
```
Pexels -> Wikimedia -> AI Generation -> Placeholder BMP
```
Generate only when stock search returns no candidates above the relevance threshold. This minimizes cost and only uses generation where stock coverage is genuinely poor.

**Pros:** Lowest cost, least disruptive, preserves stock images for real-world subjects.
**Cons:** Stock images may still win for scenes where generated would be better.

#### Option B2: Generation as parallel candidate (recommended)
```
[Pexels candidates] + [Wikimedia candidates] + [1 generated image]
    -> VisualAgent LLM picks best across all sources
```
Always generate one image and include it in the candidate pool. The existing LLM-based selection in `VisualAgent` picks the best across stock and generated candidates.

**Pros:** Best quality -- LLM chooses the most relevant image regardless of source. Generated images compete on merit.
**Cons:** Slightly higher cost (~$0.02-0.07 per scene even when stock wins). Adds latency for generation call.

#### Option B3: Generation-first for `prefer_generated` scenes
```
If prefer_generated:  AI Generation (skip stock)
Else:                 Pexels -> Wikimedia -> AI Generation -> Placeholder
```
Use the screenplay's hint to skip stock search entirely for abstract/narrative scenes.

**Pros:** Fastest for scenes where stock is unlikely to help. Most cost-efficient.
**Cons:** Requires the screenplay agent to correctly classify scenes (may need tuning).

**Recommended: Start with B1 (fallback), upgrade to B2 once quality is validated.**

**New file:** `src/tools/image_generation_tools.py`
```python
# Thin wrapper around the chosen image generation API
# Implements the same candidate schema as Pexels/Wikimedia results
# Config: IMAGE_GENERATION_PROVIDER env var (openai | google | flux)
# Config: IMAGE_GENERATION_API_KEY env var
```

**Files to change:**
- `src/tools/image_generation_tools.py` -- New file: API client for image generation
- `src/script_image_agent.py` -- Add generation provider to fallback chain
- `src/config.py` -- Add `IMAGE_GENERATION_PROVIDER`, `IMAGE_GENERATION_API_KEY` config
- `requirements.txt` -- Add `openai` (if not present) or provider SDK

**Effort:** Medium (~4-6 hours). API integration + candidate schema normalization + config.

---

### Part C: Image-script alignment evaluation loop

**What:** After images are selected (or generated), run an alignment check that compares each scene's `visual.description` / `generation_prompt` against the actual selected image. Flag scenes where alignment is poor and optionally trigger regeneration.

**Why:** Currently, relevance scoring is token-overlap based (counting shared words between alt-text and script context). This misses semantic alignment. A scene about "the first cheese factory in America" might match a photo of a modern cheese factory -- technically relevant keywords but wrong era.

**Two-tier approach:**

#### Tier 1: LLM-based alignment scoring (no new dependencies)
Use the existing LLM (already available via `make_llm()`) to evaluate alignment:

```
For each scene:
  Input:  visual.description + vo_line + selected image URL/path
  Prompt: "Rate 1-5 how well this image matches the scene description.
           Return JSON: {score, issues, suggestion}"

  If score < 3:
    Flag as DEGRADED in production_report.json
    Optionally: regenerate with AI image generation
    Optionally: revise search queries and re-search stock
```

This leverages the multimodal capabilities of modern LLMs (GPT-4o, Gemini) to actually "look" at the image and compare it to the description.

**Pros:** High accuracy, uses existing LLM infrastructure, no new dependencies.
**Cons:** Adds one LLM call per scene (~$0.01-0.03/scene for vision). Adds latency.

#### Tier 2: CLIP embedding similarity (batch-friendly, offline)
Use CLIP to compute cosine similarity between text description and image embedding:

```python
# score = cosine_similarity(
#     clip.encode_text(visual.description),
#     clip.encode_image(selected_image)
# )
# threshold: 0.25 (empirically tuned)
```

**Pros:** Fast, deterministic, no API cost (runs locally), good for batch evaluation.
**Cons:** Requires `transformers` + `torch` (~2GB download). Less nuanced than LLM.

**Recommended: Start with Tier 1 (LLM-based). Add Tier 2 later if batch speed matters.**

**Integration point -- the orchestrator revision loop:**

The `ProductionOrchestrator` in [orchestrator.py](../src/orchestrator.py) already has a scene-level revision loop that detects degraded scenes and re-runs affected agents. The alignment evaluator would plug in naturally:

```
Round 1: fetch stock images -> align check -> flag low-scoring scenes
Round 2: regenerate flagged scenes with AI generation -> align check
Round 3 (if needed): revise screenplay visual descriptions -> regenerate
```

**Files to change:**
- `src/tools/image_alignment_tools.py` -- New file: alignment scoring (LLM-based)
- `src/script_image_agent.py` -- Add post-selection alignment check
- `src/orchestrator.py` -- Wire alignment scores into revision loop decisions
- `src/mcp/video_agent_server.py` -- Expose as `evaluate_image_alignment` MCP tool (optional)

**Effort:** Medium (~4-6 hours for Tier 1 LLM-based).

---

## 5. Implementation Sequence

```
Phase 1 (Part A): Enhance screenplay prompts          ~1-2 hours
  - Update prompts to write generation_prompt
  - Update schema + reviewer
  - No new dependencies, no API cost change
  - Can ship independently and improves stock search too

Phase 2 (Part B1): Add generation as fallback          ~4-6 hours
  - Implement image_generation_tools.py
  - Wire into script_image_agent.py fallback chain
  - Requires IMAGE_GENERATION_API_KEY
  - Test with a few topics, compare stock vs generated

Phase 3 (Part C Tier 1): LLM alignment evaluation      ~4-6 hours
  - Implement alignment scoring
  - Wire into orchestrator revision loop
  - Validate on existing test fixtures

Phase 4 (Part B2): Generation as parallel candidate     ~2 hours
  - Once alignment eval confirms generated images win often enough,
    upgrade from fallback to always-generate-one-candidate
  - Tune LLM selection prompt to compare stock vs generated fairly

Phase 5 (Part C Tier 2): CLIP scoring (optional)        ~3-4 hours
  - Add CLIP for batch/offline alignment evaluation
  - Only if Tier 1 LLM scoring proves too slow or expensive
```

**Total estimated effort: ~12-16 hours across all phases.**

---

## 6. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Generated images look "AI-ish" | Use photorealistic style cues in prompts; prefer stock for real-world subjects |
| API cost creep | Start with fallback-only (B1); track per-run cost in `evaluation.json` |
| Latency increase | Generation runs in parallel with stock search (already async in orchestrator) |
| API key management | Use existing pattern: env var + config.py; graceful fallback if missing |
| Content policy violations | Image gen APIs have built-in safety filters; add our own check in alignment eval |
| Portrait (9:16) generation quality | OpenAI GPT Image supports 1024x1536 natively; others need crop/resize |
| LLM alignment eval hallucination | Use structured JSON output with score + reasoning; threshold conservatively |

---

## 7. Impact on Existing Artifacts

| Artifact | Change |
|----------|--------|
| Screenplay | New optional fields: `generation_prompt`, `prefer_generated` |
| ScriptPackage | New optional field: `generation_prompt` forwarded from screenplay |
| ScriptImageManifest | Candidates may include `source: "generated"` entries |
| VisualManifest | Selected asset may have `source: "openai"` / `"google"` / `"flux"` |
| evaluation.json | New section: `image_alignment_scores` per scene |
| production_report.json | New issue type: `low_image_alignment` |

All changes are **additive** -- existing artifacts remain valid. No breaking changes to the pipeline.

---

## 8. Decision Points for Human Review

1. **Which provider to start with?** OpenAI (likely already have key) vs Google Imagen (best price/quality) vs Flux via aggregator (cheapest)?

2. **Fallback-only (B1) or always-generate (B2)?** B1 is cheaper and less disruptive. B2 produces better results but costs ~$0.02-0.07 more per scene even when stock wins.

3. **Should `prefer_generated` be screenplay-driven or rule-based?** Screenplay-driven is more flexible but requires prompt tuning. Rule-based (e.g., "generate if stock relevance < 3.0") is simpler.

4. **LLM alignment eval (Tier 1) or skip straight to CLIP (Tier 2)?** LLM is more accurate but costs ~$0.01-0.03/scene. CLIP is free but requires torch (~2GB).

5. **Priority vs ROADMAP?** This work spans Tier 1 (image quality) and Tier 3 (CLIP scoring, content moderation). Parts A and B could reasonably fit into Tier 1. Part C is more Tier 2-3.

---

## Sources

- [AI Image Generation API Comparison 2026](https://blog.laozhang.ai/en/posts/ai-image-generation-api-comparison-2026)
- [AI Image Pricing: Google vs OpenAI](https://intuitionlabs.ai/articles/ai-image-generation-pricing-google-openai)
- [OpenAI Image Pricing Calculator](https://costgoat.com/pricing/openai-images)
- [Cheapest Image Gen Models 2026](https://www.siliconflow.com/articles/en/the-cheapest-image-gen-models)
- [AI Image Model Pricing Comparison](https://pricepertoken.com/image)
- [10 Best AI Image Generators 2026 (fal.ai)](https://fal.ai/learn/tools/ai-image-generators)
