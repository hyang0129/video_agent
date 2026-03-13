# Fix: Screenplay Text Sanitizer + On-Screen Text Flow

**Branch:** `fix/screenplay-sanitizer-and-text-flow`
**ROADMAP items:** #7 (P0), #9 (P0)
**Date:** March 13, 2026

---

## Problem

Two bugs in the screenplay-to-video pipeline:

### Bug #7: Non-ASCII Characters in Screenplay Text

The LLM screenplay writer emits Unicode punctuation (em-dashes `\u2014`, curly quotes `\u201C`/`\u201D`, ellipsis `\u2026`, emoji) in `vo_line` and `on_screen_text` fields. These cause:

- FFmpeg `drawtext` font glyph rendering errors (missing glyphs show as boxes)
- Inconsistent TTS behavior (Chatterbox may mispronounce or skip special chars)

**Example from pipeline run:**
```
"But Hamburg, Germany argues their \u2018steak tartare\u2019 \u2014 raw minced beef \u2014 was the inspiration"
```

### Bug #9: On-Screen Text Shows Wrong Content

The video's rendered on-screen text displayed the full `vo_line` narration instead of the intended brief `on_screen_text` caption.

**Root cause:** `composition_agent.py:create_text_overlays()` (line 273) preferred `vo_line` over `on_screen_text`:

```python
# BEFORE (buggy): vo_line takes priority
text = str(scene.get("vo_line") or "").strip()
if not text:
    text = str(scene.get("on_screen_text") or "").strip()
```

Result: A scene with `vo_line="The Tiger tank was a fearsome weapon of World War Two."` and `on_screen_text="Tiger Tank"` would render the full narration as the on-screen caption.

---

## Changes

### New file: `src/utils/text_sanitizer.py`

Two functions:

- **`sanitize_text(text) -> str`** — Single-pass replacement of non-ASCII punctuation with ASCII equivalents, plus emoji stripping and whitespace normalization.
  - Em/en dashes -> ` - `
  - Curly quotes -> straight quotes
  - Unicode ellipsis -> `...`
  - Zero-width chars, BOM -> removed
  - Non-breaking/special spaces -> regular space
  - Emoji -> removed
  - NFC normalization + whitespace collapse

- **`has_unsafe_characters(text) -> list[str]`** — Detection-only variant for validation. Returns human-readable issue descriptions without modifying text.

### Modified: `src/screenwriting/screenplay_agent.py`

- `_coerce_scenes()`: Calls `sanitize_text()` on `vo_line` and `on_screen_text` immediately after LLM output parsing.
- `revise_scene()`: Calls `sanitize_text()` on patched `vo_line` fields.

This is the earliest post-LLM stage, so all downstream consumers (audio agent, composition agent, render agent) receive clean text.

### Modified: `src/screenwriting/screenplay_reviewer.py`

- Added `unsafe_characters` check in per-scene validation loop.
- Calls `has_unsafe_characters()` on both `vo_line` and `on_screen_text`.
- Severity: `warn` (the sanitizer already fixes these, but the reviewer now flags if any slip through or if upstream text is passed without sanitization).

### Modified: `src/composition_agent.py`

- `create_text_overlays()` line 273: Inverted priority to prefer `on_screen_text`, falling back to `vo_line` only when `on_screen_text` is empty.

```python
# AFTER (fixed): on_screen_text takes priority
text = str(scene.get("on_screen_text") or "").strip()
if not text:
    text = str(scene.get("vo_line") or "").strip()
```

### Modified: `src/artifacts/screenplay.py`

- `screenplay_to_script_package()`: Changed `current_t` from `0.0` to `0.5` so the first scene starts at 0.5s instead of immediately at 0.0s. This adds a brief lead-in before audio/video content begins.

### Modified: `ROADMAP.md`

- Items #7 and #9 marked as FIXED with resolution details.

### Modified: `tests/test_composition_agent.py`

- Updated `test_create_render_specification_basic` to assert the correct `on_screen_text` content instead of the old `vo_line` content.

### New tests

- **`tests/test_text_sanitizer.py`** (20 tests) — Unit tests for `sanitize_text()` and `has_unsafe_characters()` covering em-dashes, curly quotes, ellipsis, emoji, zero-width chars, whitespace, real-world screenplay lines.
- **`tests/test_text_flow.py`** (8 tests) — Integration tests verifying:
  - `_coerce_scenes()` sanitizes non-ASCII in both fields
  - `CompositionAgent.create_text_overlays()` prefers `on_screen_text`
  - `ScreenplayReviewer` flags unsafe characters

---

## Test Results

- 192 pre-existing tests: all pass (0 regressions)
- 28 new tests: all pass
- 2 pre-existing failures unrelated to this PR:
  - `test_real_tts_generation`: expects `.mp3` but chatterbox produces `.wav` (TTS backend mismatch)
  - `test_mcp_server_full_pipeline`: pre-existing `NameError: name 'screenplay_agent' is not defined`

---

## Verification

Full MCP pipeline run with these fixes produces:
- Screenplay with clean ASCII text (no em-dashes, curly quotes, or emoji)
- On-screen text in the rendered video matches the `on_screen_text` field (brief captions, not full voiceover narration)
- TTS receives clean text with no special characters

Pipeline output log is saved in `results/test/full_mcp_pipeline/pipeline_run_log.json`.
