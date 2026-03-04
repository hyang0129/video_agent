# Script Image → Video Integration Plan

## Goal
Use beat-level `script_image_manifest.json` candidates to produce scene-accurate `visual_manifest.json` assets that flow into render output (`final_video.mp4`).

## Scope
- Integrate image retrieval artifacts into existing MVP pipeline.
- Keep existing render/composition contracts unchanged.
- Add source-fallback scaffolding so multiple providers can be introduced incrementally.

---

## Step 1 — Add ScriptImage → VisualManifest Bridge
**What to implement**
- Add a visual-agent bridge method that accepts:
  - `video_plan`
  - `script_image_manifest`
- Map scene/beat IDs and choose one candidate per scene (top ranked by relevance).
- Download selected image and emit standard `VisualManifest.assets[]` entries.

**Done when**
- A valid `visual_manifest.json` is generated from script-image data without changing `composition_agent` input shape.

## Step 2 — Wire Pipeline Paths (CLI + Runner)
**What to implement**
- In `main.py` MVP flow:
  1. Create `script_package`
  2. Create `script_image_manifest`
  3. Build `visual_manifest` from script-image bridge
- In `src/full_pipeline_runner.py`, replace placeholder-first visual flow with script-image-first flow.

**Done when**
- MVP and full runner both generate non-placeholder visual assets when valid candidates exist.

## Step 3 — Multi-Source Retrieval and Fallback Order
**What to implement**
- Treat `image_sources` as an ordered provider chain.
- For each query, try providers in order until enough candidates are collected.
- Continue to next provider when:
  - provider is unavailable,
  - request fails,
  - or returns no candidates.
- Record attempts/errors per source in `retrieval_notes`.

**Provider strategy (Phase 1 scaffolding)**
- Implement provider dispatcher with current support for `pexels`.
- Keep unsupported provider names non-fatal; log as "not implemented" and continue.
- This enables future addition of providers (e.g., Wikimedia, Pixabay, Unsplash-compatible adapters) without changing agent contracts.

**Done when**
- `image_sources=("source_a", "pexels")` still works via fallback to `pexels`.

## Step 4 — Candidate Quality Gate Before Download
**What to implement**
- Use alt-text relevance metadata (`metadata.relevance`) to filter candidates.
- Reject candidates that violate hard mismatch rules (example: WWI script beat + WWII alt conflict).
- Keep placeholder fallback if no acceptable candidate remains.

**Done when**
- Weak semantic matches are not selected over relevant matches.

## Step 5 — Keep Composition/Render Contracts Stable
**What to implement**
- Do not change `composition_agent` clip contract.
- Ensure selected assets still output `file_path` values compatible with existing `render_agent` behavior.

**Done when**
- Existing `renderspec` and `render` commands work unchanged with image-selected scenes.

## Step 6 — Validation and Regression Coverage
**What to implement**
- Add tests for:
  - script-image fixture → visual-manifest bridge,
  - multi-source fallback behavior,
  - quality-gate rejection/fallback,
  - deterministic candidate selection.
- Validate with one real topic fixture (World War 1 tanks) and inspect final MP4 scene relevance.

**Done when**
- Tests pass and at least one end-to-end run shows scene-appropriate images in rendered output.

---

## Recommended Delivery Order
1. Step 3 (multi-source scaffolding)
2. Step 1 (bridge)
3. Step 2 (pipeline wiring)
4. Step 4 (quality gate)
5. Step 6 (tests and run validation)

## Artifacts Produced by This Plan
- `script_image_manifest.json` (already available)
- `visual_manifest.json` (script-image driven)
- `render_spec.json`
- `final_video.mp4`
