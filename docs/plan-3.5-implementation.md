# Issue 3.5: AI Image Generation Integration -- Implementation Plan

**Status:** Ready for implementation
**Delete on merge:** Yes -- this file is a temporary implementation guide.

---

## Problem

The pipeline retrieves scene images from Pexels and Wikimedia, but many scenes describe abstract concepts, historical events, or narrative moments with no good stock coverage. The screenplay agent already writes `generation_prompts: {precise, general}` per scene (issue 1.7) and these flow through `screenplay_to_script_package()` into each beat -- but nothing reads them. AI image generation fills the stock coverage gap at $0.005-0.07/image.

## Approach

**B1 (fallback-only):** Add AI image generation as the last source before placeholder BMPs. Generation only fires when stock search returns zero usable candidates.

```
Pexels -> Wikimedia -> AI Generation -> Placeholder BMP
```

This is the conservative option from the design doc. B2 (always-generate-one-candidate) is a follow-up once quality is validated.

**Provider:** OpenAI GPT Image 1. The `.env` already has `ANTHROPIC_API_KEY` and `GOOGLE_API_KEY`; there is no `OPENAI_API_KEY` yet, but the OpenAI SDK is the most straightforward (native 1024x1536 portrait, transparent pricing, simple REST API). The interface is provider-agnostic so Google Imagen or Flux can be added later.

---

## Step 1: Add config entries

**File:** `video_agent/config.py` (after line 17, the `PEXELS_API_KEY` line)

```python
# Image Generation (AI-generated backgrounds as stock fallback)
IMAGE_GENERATION_PROVIDER = os.getenv("IMAGE_GENERATION_PROVIDER", "")  # "openai" | ""
IMAGE_GENERATION_API_KEY = os.getenv(
    "IMAGE_GENERATION_API_KEY",
    os.getenv("OPENAI_API_KEY", ""),
)
IMAGE_GENERATION_QUALITY = os.getenv("IMAGE_GENERATION_QUALITY", "medium")
```

Empty `IMAGE_GENERATION_PROVIDER` means generation is disabled. This ensures no behavior change for existing users. The API key falls back to `OPENAI_API_KEY` so users who already have one get generation for free by just setting `IMAGE_GENERATION_PROVIDER=openai`.

**File:** `.env` (append)

```bash
# AI Image Generation (fallback when stock search fails)
# Provider: "openai" (GPT Image 1) | "" (disabled)
IMAGE_GENERATION_PROVIDER=
# IMAGE_GENERATION_API_KEY defaults to OPENAI_API_KEY if set
# OPENAI_API_KEY=sk-...
```

---

## Step 2: Create `image_generation_tools.py`

**File:** `video_agent/tools/image_generation_tools.py` (NEW)

### Public API

```python
class ImageGenerationError(Exception):
    """Raised when image generation fails (missing key, API error, timeout)."""


def generate_image(
    prompt: str,
    output_path: Path,
    provider: str = "openai",
    size: str = "1024x1536",
    quality: str = "medium",
) -> Dict[str, Any]:
    """Generate an image from a text prompt and save it to disk.

    Args:
        prompt: Image generation prompt text.
        output_path: Where to save the generated image (e.g. run_dir/assets/scene_03_gen.png).
        provider: Provider name ("openai"). Others can be added later.
        size: Image dimensions as "WxH". Default "1024x1536" for 9:16 portrait.
        quality: Provider-specific quality tier ("low", "medium", "high").

    Returns:
        Normalized candidate dict matching the stock image schema:
        {
            "source": "generated_openai",
            "url": str(output_path),       # local file path
            "resolution": [1024, 1536],
            "attribution": {"required": False, "text": "AI-generated (OpenAI)", "license": "generated"},
            "metadata": {
                "alt": prompt[:200],
                "generation_prompt": prompt,
                "provider": "openai",
                "cost_usd": 0.07,
            }
        }

    Raises:
        ImageGenerationError: On any failure (missing API key, network, timeout, content policy).
    """
```

### OpenAI implementation detail

```python
def _generate_openai(prompt: str, output_path: Path, size: str, quality: str) -> Dict[str, Any]:
    import openai  # lazy import to avoid hard dependency when generation is disabled

    api_key = IMAGE_GENERATION_API_KEY
    if not api_key:
        raise ImageGenerationError("IMAGE_GENERATION_API_KEY (or OPENAI_API_KEY) is not configured")

    client = openai.OpenAI(api_key=api_key)

    # Map quality to OpenAI tiers and cost
    quality_map = {"low": ("low", 0.005), "medium": ("medium", 0.07), "high": ("high", 0.167)}
    oai_quality, cost_usd = quality_map.get(quality, quality_map["medium"])

    try:
        response = client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            n=1,
            size=size,          # "1024x1536" for portrait
            quality=oai_quality,
        )
    except openai.APIError as exc:
        raise ImageGenerationError(f"OpenAI image generation failed: {exc}")

    # response.data[0] has either .url or .b64_json depending on response_format
    image_data = response.data[0]

    # Save to disk
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(image_data, "b64_json") and image_data.b64_json:
        import base64
        raw = base64.b64decode(image_data.b64_json)
        output_path.write_bytes(raw)
    elif hasattr(image_data, "url") and image_data.url:
        import requests
        resp = requests.get(image_data.url, timeout=60)
        resp.raise_for_status()
        output_path.write_bytes(resp.content)
    else:
        raise ImageGenerationError("OpenAI returned neither b64_json nor url")

    w, h = (int(d) for d in size.split("x"))
    return {
        "source": "generated_openai",
        "url": str(output_path),
        "resolution": [w, h],
        "attribution": {"required": False, "text": "AI-generated (OpenAI GPT Image 1)", "license": "generated"},
        "metadata": {
            "alt": prompt[:200],
            "generation_prompt": prompt,
            "provider": "openai",
            "model": "gpt-image-1",
            "quality": oai_quality,
            "cost_usd": cost_usd,
        },
    }
```

### `generate_image` dispatcher

```python
_PROVIDERS = {
    "openai": _generate_openai,
}

def generate_image(prompt, output_path, provider="openai", size="1024x1536", quality="medium"):
    if not prompt or not prompt.strip():
        raise ImageGenerationError("Empty prompt")
    if provider not in _PROVIDERS:
        raise ImageGenerationError(f"Unknown image generation provider: {provider!r}. Available: {list(_PROVIDERS)}")
    return _PROVIDERS[provider](prompt.strip(), output_path, size, quality)
```

### Design decisions

- **`output_path` is caller-provided:** The caller (script_image_agent or MCP handler) knows the run_dir and scene_id, so it passes the exact save location. The tool doesn't need to know about run directories.
- **Lazy `import openai`:** Avoids import errors for users who haven't installed the `openai` package and don't use generation.
- **Cost is hardcoded per quality tier:** Simpler than parsing API response headers. The cost map can be updated when pricing changes.

---

## Step 3: Wire generation into `ScriptImageRetrievalAgent._build_segment_candidate`

**File:** `video_agent/script_image_agent.py`

### 3a. Add import at top of file (after line 29)

```python
from .config import IMAGE_GENERATION_PROVIDER, IMAGE_GENERATION_QUALITY
```

### 3b. Add generation fallback after the stock search loop

In `_build_segment_candidate`, after line 604 (after `candidates = candidates[:max_candidates]`) but before the return statement at line 618, insert the generation fallback block.

**Why after reranking:** The stock candidates have been scored and trimmed. If none survive (or all score below threshold), we know stock failed and generation is justified.

```python
        # -- AI image generation fallback --
        # Trigger when stock search produced no viable candidates and a generation
        # provider is configured.  Uses beat.generation_prompts written by the
        # screenplay agent (issue 1.7).
        generation_cost_usd = 0.0
        if IMAGE_GENERATION_PROVIDER and len(candidates) < min_candidates:
            gen_prompts = beat.get("generation_prompts") or {}
            assets_dir = self.output_dir / "assets" if self.output_dir else None
            if gen_prompts and assets_dir:
                from .tools.image_generation_tools import generate_image, ImageGenerationError

                for prompt_key in ("precise", "general"):
                    prompt_text = gen_prompts.get(prompt_key)
                    if not prompt_text:
                        continue
                    gen_dest = assets_dir / f"{beat_id}_gen_{prompt_key}.png"
                    try:
                        gen_result = generate_image(
                            prompt=prompt_text,
                            output_path=gen_dest,
                            provider=IMAGE_GENERATION_PROVIDER,
                            quality=IMAGE_GENERATION_QUALITY,
                        )
                        generation_cost_usd += float(
                            (gen_result.get("metadata") or {}).get("cost_usd") or 0.0
                        )
                        candidates.append({
                            "candidate_id": f"cand_{uuid.uuid4().hex[:8]}",
                            "source": gen_result.get("source", "generated"),
                            "url": gen_result["url"],
                            "resolution": gen_result.get("resolution", [0, 0]),
                            "attribution": gen_result.get("attribution", {}),
                            "metadata": {
                                "search_query": f"[generated:{prompt_key}]",
                                **(gen_result.get("metadata") or {}),
                            },
                        })
                        print(f"[INFO] Generated image for {beat_id} using {prompt_key} prompt")
                        break  # one generated image is enough for B1
                    except ImageGenerationError as exc:
                        provider_errors.append(f"generation({prompt_key}): {exc}")
                        continue
```

### 3c. Add `generation_cost_usd` to the returned segment dict

In the return dict (line 618), add one field:

```python
            "generation_cost_usd": generation_cost_usd,
```

### 3d. Initialize `generation_cost_usd = 0.0` at the top of the method

If generation is disabled or not needed, this stays 0.0 and costs nothing.

### Integration notes

- **The `output_dir` check:** `self.output_dir` may be `None` in tests. Generation is skipped when there's no output directory (it needs somewhere to save the file).
- **`break` after first success:** B1 only needs one generated image. If `precise` succeeds, skip `general`.
- **`provider_errors` already exists** in the method scope (line 545), so generation errors naturally flow into the segment's `retrieval_notes.provider_errors`.

---

## Step 4: Handle local file paths in `_download_image`

**File:** `video_agent/mcp/video_agent_server.py` (line 105)

The current `_download_image` does `requests.get(url)` which fails for local file paths from generated images. Add a local-file check at the top:

```python
def _download_image(url: str, dest: Path) -> bool:
    try:
        # Handle local file paths (from AI-generated images)
        source = Path(url)
        if source.is_file():
            import shutil
            dest.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != dest.resolve():
                shutil.copy2(source, dest)
            return True

        # Existing HTTP download logic below...
        if any(h in url for h in _WIKIMEDIA_HOSTS):
            wikimedia_rate_limiter.throttle()
        resp = requests.get(url, timeout=30, stream=True, headers=_DOWNLOAD_HEADERS)
        ...
```

This is the minimal change. If the URL is a local path pointing to an existing file, copy it to the destination. If it's already at the destination (same resolve), skip the copy.

---

## Step 5: Wire generation retry into MCP `fetch_assets` handler

**File:** `video_agent/mcp/video_agent_server.py` (after line 773, the Pexels retry block)

After the existing Pexels-only retry, add a generation retry for remaining placeholders:

```python
            # If any scenes are still placeholders after Pexels retry, try AI generation.
            if IMAGE_GENERATION_PROVIDER:
                still_placeholder_ids = [
                    a["scene_id"] for a in (visual_manifest.get("assets") or [])
                    if a.get("source") == "placeholder" and a.get("scene_id")
                ]
                if still_placeholder_ids:
                    from .tools.image_generation_tools import generate_image, ImageGenerationError

                    beats_by_scene = {}
                    for beat in (script_package.get("script", {}).get("beats") or []):
                        sid = str(beat.get("scene_id") or "")
                        if sid:
                            beats_by_scene[sid] = beat

                    assets_dir = run_dir / "assets"
                    generation_costs = []
                    for scene_id in still_placeholder_ids:
                        beat = beats_by_scene.get(scene_id, {})
                        gen_prompts = beat.get("generation_prompts") or {}
                        if not gen_prompts:
                            continue

                        for prompt_key in ("precise", "general"):
                            prompt_text = gen_prompts.get(prompt_key)
                            if not prompt_text:
                                continue
                            gen_dest = assets_dir / f"{scene_id}_gen.png"
                            try:
                                gen_result = generate_image(
                                    prompt=prompt_text,
                                    output_path=gen_dest,
                                    provider=IMAGE_GENERATION_PROVIDER,
                                    quality=IMAGE_GENERATION_QUALITY,
                                )
                                generation_costs.append(
                                    float((gen_result.get("metadata") or {}).get("cost_usd") or 0.0)
                                )
                                # Update the visual manifest entry for this scene
                                for asset in (visual_manifest.get("assets") or []):
                                    if asset["scene_id"] == scene_id:
                                        asset["file_path"] = str(gen_dest.relative_to(run_dir)).replace("\\", "/")
                                        asset["source"] = gen_result.get("source", "generated")
                                        asset["attribution"] = gen_result.get("attribution", {})
                                        break
                                print(f"[INFO] Generated image for {scene_id} (fetch_assets fallback)")
                                break  # success, move to next scene
                            except ImageGenerationError as exc:
                                print(f"[WARN] Generation failed for {scene_id} ({prompt_key}): {exc}")
                                continue
```

### Import needed at top of file

Add to the existing imports section:

```python
from ..config import IMAGE_GENERATION_PROVIDER, IMAGE_GENERATION_QUALITY
```

---

## Step 6: Cost tracking in production report

**File:** `video_agent/script_image_agent.py`

In `generate_script_image_manifest`, after building the manifest (line 481), aggregate generation costs:

```python
        total_generation_cost = sum(
            float(seg.get("generation_cost_usd") or 0.0) for seg in segment_assets
        )
        if total_generation_cost > 0:
            manifest["image_generation"] = {
                "total_cost_usd": round(total_generation_cost, 4),
                "provider": IMAGE_GENERATION_PROVIDER,
                "scenes_generated": sum(
                    1 for seg in segment_assets
                    if any(
                        "generated" in str(c.get("source", ""))
                        for c in (seg.get("candidates") or [])
                    )
                ),
            }
```

This data flows through the manifest into evaluation.json via the existing orchestrator reporting.

---

## Step 7: Add `openai` to requirements.txt

**File:** `requirements.txt` (after the `elevenlabs` line)

```
# AI Image Generation (optional -- only needed if IMAGE_GENERATION_PROVIDER is set)
openai>=1.0.0
```

---

## Step 8: Tests

### 8a. New file: `tests/test_image_generation_tools.py`

```python
"""Tests for video_agent.tools.image_generation_tools."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from video_agent.tools.image_generation_tools import (
    ImageGenerationError,
    generate_image,
)


class TestGenerateImage:
    def test_empty_prompt_raises(self, tmp_path):
        with pytest.raises(ImageGenerationError, match="Empty prompt"):
            generate_image("", output_path=tmp_path / "out.png")

    def test_unknown_provider_raises(self, tmp_path):
        with pytest.raises(ImageGenerationError, match="Unknown"):
            generate_image("a cat", output_path=tmp_path / "out.png", provider="invalid")

    @patch("video_agent.tools.image_generation_tools.IMAGE_GENERATION_API_KEY", "")
    def test_missing_api_key_raises(self, tmp_path):
        with pytest.raises(ImageGenerationError, match="not configured"):
            generate_image("a cat", output_path=tmp_path / "out.png", provider="openai")

    @patch("video_agent.tools.image_generation_tools.IMAGE_GENERATION_API_KEY", "sk-test")
    def test_openai_success(self, tmp_path):
        dest = tmp_path / "assets" / "scene_01.png"
        fake_b64 = "iVBORw0KGgo="  # minimal base64

        mock_response = MagicMock()
        mock_response.data = [MagicMock(b64_json=fake_b64, url=None)]

        with patch("video_agent.tools.image_generation_tools.openai") as mock_openai:
            mock_openai.OpenAI.return_value.images.generate.return_value = mock_response
            mock_openai.APIError = Exception

            result = generate_image("a cat on a roof", output_path=dest, provider="openai")

        assert result["source"] == "generated_openai"
        assert result["url"] == str(dest)
        assert result["resolution"] == [1024, 1536]
        assert result["metadata"]["cost_usd"] == 0.07
        assert result["metadata"]["provider"] == "openai"
        assert dest.exists()

    @patch("video_agent.tools.image_generation_tools.IMAGE_GENERATION_API_KEY", "sk-test")
    def test_openai_api_error_raises(self, tmp_path):
        with patch("video_agent.tools.image_generation_tools.openai") as mock_openai:
            mock_openai.OpenAI.return_value.images.generate.side_effect = Exception("rate limit")
            mock_openai.APIError = Exception

            with pytest.raises(ImageGenerationError, match="rate limit"):
                generate_image("a cat", output_path=tmp_path / "out.png", provider="openai")
```

### 8b. New tests in `tests/test_script_image_agent.py`

```python
class TestGenerationFallback:
    """Tests for AI image generation fallback in _build_segment_candidate."""

    @patch("video_agent.script_image_agent.IMAGE_GENERATION_PROVIDER", "openai")
    @patch("video_agent.script_image_agent.IMAGE_GENERATION_QUALITY", "medium")
    def test_generation_triggers_when_stock_empty(self, tmp_path):
        """When stock search returns nothing, generation fires using precise prompt."""
        config = ScriptImageConfig(
            output_dir=tmp_path,
            image_sources=("pexels",),
        )
        agent = ScriptImageRetrievalAgent(config)

        beat = {
            "vo_line": "The first cheese factory in America",
            "generation_prompts": {
                "precise": "18th century American cheese factory, wooden building, pastoral setting",
                "general": "old cheese factory",
            },
        }

        with patch.object(agent, "_search_source", return_value=[]):
            with patch("video_agent.script_image_agent.generate_image") as mock_gen:
                mock_gen.return_value = {
                    "source": "generated_openai",
                    "url": str(tmp_path / "assets" / "beat_01_gen_precise.png"),
                    "resolution": [1024, 1536],
                    "attribution": {},
                    "metadata": {"cost_usd": 0.07, "provider": "openai"},
                }
                segment = agent._build_segment_candidate(
                    beat=beat, beat_index=0, topic_hint="cheese history",
                )

        assert segment["candidate_count"] >= 1
        assert any("generated" in str(c.get("source", "")) for c in segment["candidates"])
        mock_gen.assert_called_once()
        assert "precise" in mock_gen.call_args.kwargs.get("prompt", mock_gen.call_args.args[0])

    @patch("video_agent.script_image_agent.IMAGE_GENERATION_PROVIDER", "openai")
    def test_generation_skipped_when_stock_succeeds(self, tmp_path):
        """When stock search returns enough candidates, generation is not called."""
        config = ScriptImageConfig(output_dir=tmp_path, image_sources=("pexels",))
        agent = ScriptImageRetrievalAgent(config)

        beat = {
            "vo_line": "A golden retriever playing fetch",
            "generation_prompts": {"precise": "golden retriever in park"},
        }
        stock_result = {
            "source": "pexels",
            "url": "https://example.com/dog.jpg",
            "resolution": [1024, 768],
            "metadata": {"alt": "golden retriever playing fetch in park"},
        }

        with patch.object(agent, "_search_source", return_value=[stock_result]):
            with patch("video_agent.script_image_agent.generate_image") as mock_gen:
                segment = agent._build_segment_candidate(
                    beat=beat, beat_index=0, topic_hint="dogs",
                )

        mock_gen.assert_not_called()
        assert segment["candidate_count"] >= 1

    @patch("video_agent.script_image_agent.IMAGE_GENERATION_PROVIDER", "")
    def test_generation_skipped_when_provider_empty(self, tmp_path):
        """When IMAGE_GENERATION_PROVIDER is empty, generation is never attempted."""
        config = ScriptImageConfig(output_dir=tmp_path, image_sources=("pexels",))
        agent = ScriptImageRetrievalAgent(config)
        beat = {"vo_line": "test", "generation_prompts": {"precise": "test prompt"}}

        with patch.object(agent, "_search_source", return_value=[]):
            with patch("video_agent.script_image_agent.generate_image") as mock_gen:
                agent._build_segment_candidate(beat=beat, beat_index=0, topic_hint="")

        mock_gen.assert_not_called()
```

---

## File change summary

| File | Change type | Lines changed (est.) |
|------|------------|---------------------|
| `video_agent/config.py` | Edit | +6 (after line 17) |
| `video_agent/tools/image_generation_tools.py` | **New file** | ~100 |
| `video_agent/script_image_agent.py` | Edit | +35 (generation fallback block) |
| `video_agent/mcp/video_agent_server.py` | Edit | +40 (local path handling + generation retry) |
| `.env` | Edit | +4 (new env vars) |
| `requirements.txt` | Edit | +2 |
| `tests/test_image_generation_tools.py` | **New file** | ~70 |
| `tests/test_script_image_agent.py` | Edit | +60 (3 new test methods) |

---

## Verification plan

1. **Unit tests:** `pytest tests/test_image_generation_tools.py -v`
2. **Integration tests:** `pytest tests/test_script_image_agent.py -v`
3. **Existing tests pass:** `pytest tests/ -v --ignore=tests/integration` (no regressions)
4. **Manual smoke test:**
   - Set `IMAGE_GENERATION_PROVIDER=openai` and `OPENAI_API_KEY=sk-...` in `.env`
   - Run stage 5 integration test with a topic that has poor stock coverage
   - Verify generated image appears in `results/` with `source: "generated_openai"`
   - Verify `image_generation.total_cost_usd` appears in the manifest
5. **Disabled path:** With `IMAGE_GENERATION_PROVIDER=` (empty), verify the entire pipeline behaves identically to before this change.

---

## Best guesses requiring human review

### 1. OpenAI SDK response format: `b64_json` vs `url`

**Guess:** GPT Image 1 returns `b64_json` by default. The implementation handles both `b64_json` and `url` response formats.

**Why:** The OpenAI images API has a `response_format` parameter defaulting to `url` for DALL-E but some models default to `b64_json`. The GPT Image 1 docs (post-cutoff model) may behave differently. The implementation defensively checks both fields so either works.

**Action if wrong:** If GPT Image 1 requires explicit `response_format="b64_json"` or `response_format="url"`, add that parameter to the `images.generate()` call.

### 2. OpenAI cost per image at `medium` quality: $0.07

**Guess:** Based on the design doc's pricing table (March 2026 data from external sources). GPT Image 1 medium quality is $0.07/image at 1024x1536.

**Why:** Pricing may have changed. The cost is used for reporting only (not billing), so an incorrect estimate just makes the `evaluation.json` cost tracking inaccurate.

**Action if wrong:** Update the `quality_map` dict in `_generate_openai` with current pricing.

### 3. `gpt-image-1` model name and `1024x1536` size string

**Guess:** The model ID is `gpt-image-1` and portrait size is specified as `"1024x1536"`.

**Why:** This matches the naming convention in the design doc and OpenAI's recent model naming patterns. The exact model ID and supported sizes are post-knowledge-cutoff.

**Action if wrong:** Update the model name and/or size string. If 1024x1536 isn't supported, fall back to `1024x1024` and note that the compositor's Ken Burns effect will handle the aspect ratio mismatch.

### 4. Generation trigger condition: `len(candidates) < min_candidates`

**Guess:** Generation fires when candidates after reranking + trimming are fewer than `min_candidates_per_segment` (default 1). This means generation triggers when stock returns zero usable images.

**Why:** The design doc says "fallback -- only when stock search returns no candidates above the relevance threshold." The reranking step already filters low-relevance candidates, so checking `< min_candidates` post-rerank is equivalent.

**Alternative considered:** Checking `_best_relevance_score(segment) < _RELEVANCE_THRESHOLD` would be more precise but requires restructuring the method since `segment` isn't built yet at the generation point. The current approach is simpler and achieves the same B1 behavior.

**Action if wrong:** If generation triggers too aggressively (stock has OK candidates but count is low), tighten the condition to `len(candidates) == 0`.

### 5. Placement of generation fallback: after reranking, before return

**Guess:** Insert the generation block after line 605 (`candidates = candidates[:max_candidates]`) and before the `candidate_sources` computation at line 606.

**Why:** At this point, stock candidates have been fetched, scored, reranked, and trimmed. We know the final stock candidate count. This is the natural place to decide "stock failed, try generation." The generated candidate is appended to the already-trimmed list, which may push total candidates above `max_candidates` by one -- acceptable for B1 where generation only fires on empty results.

**Action if wrong:** If the generated candidate needs to participate in reranking (relevant for B2), move the generation block before the `_rerank_candidates` call instead.

### 6. `_download_image` local path handling via `Path.is_file()`

**Guess:** Checking `Path(url).is_file()` correctly distinguishes local generated image paths from HTTP URLs, because HTTP URLs like `https://images.pexels.com/...` won't resolve as local files.

**Why:** `Path("https://images.pexels.com/photo.jpg").is_file()` returns `False` on Linux. Generated images are saved with absolute paths like `/workspaces/.../assets/scene_01_gen.png` which `Path.is_file()` correctly identifies.

**Action if wrong:** If any edge case causes a URL to resolve as a local path, add an explicit `url.startswith(("http://", "https://"))` guard before the local-file branch.
