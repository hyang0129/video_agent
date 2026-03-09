"""ScreenplayReviewer: heuristic pre-flight validation. No external API calls."""

from __future__ import annotations

from typing import Any

from ..artifacts.screenplay import new_feasibility_report

_WORDS_PER_MINUTE = 150.0

_GENERIC_VISUAL_PHRASES = frozenset([
    "people talking",
    "person thinking",
    "group of people",
    "people discussing",
    "someone thinking",
    "a person",
    "people working",
    "background",
    "generic background",
    "abstract background",
])


def _estimated_speech_seconds(vo_line: str) -> float:
    words = len(vo_line.split())
    return (words / _WORDS_PER_MINUTE) * 60.0


def _is_generic_visual(description: str) -> bool:
    desc_lower = description.strip().lower()
    if desc_lower in _GENERIC_VISUAL_PHRASES:
        return True
    for phrase in _GENERIC_VISUAL_PHRASES:
        if desc_lower == phrase:
            return True
        # flag if description is *only* a generic phrase (not embedded in richer text)
        if len(desc_lower) <= len(phrase) + 5 and phrase in desc_lower:
            return True
    return False


class ScreenplayReviewer:
    def review(self, screenplay: dict[str, Any]) -> dict[str, Any]:
        """Validate a Screenplay heuristically. No external API calls.

        Returns a FeasibilityReport dict.
        """
        screenplay_id = str(screenplay.get("screenplay_id") or "")
        target_duration_s = float(screenplay.get("target_duration_s") or 45)
        scenes = screenplay.get("scenes") or []

        issues: list[dict[str, Any]] = []
        error_count = 0
        scene_error_ids: set[str] = set()

        # Check 1: empty scenes
        if not scenes:
            issues.append({
                "scene_id": "ALL",
                "issue": "no_scenes",
                "detail": "Screenplay has no scenes",
                "suggestion": "Re-generate the screenplay",
                "severity": "error",
            })
            return new_feasibility_report(
                screenplay_ref=screenplay_id,
                overall_score=0.0,
                scene_issues=issues,
                recommended_action="reject",
            )

        # Per-scene checks
        for scene in scenes:
            if not isinstance(scene, dict):
                continue

            scene_id = str(scene.get("scene_id") or "unknown")
            vo = str(scene.get("vo_line") or "").strip()
            visual = scene.get("visual") or {}
            description = str(visual.get("description") or "").strip()
            on_screen = str(scene.get("on_screen_text") or "").strip()
            target_dur = float(scene.get("target_duration_s") or 5.0)

            # Check: empty required fields
            if not vo:
                issues.append({
                    "scene_id": scene_id,
                    "issue": "empty_vo_line",
                    "detail": "vo_line is empty",
                    "suggestion": "Write narration text for this scene",
                    "severity": "error",
                })
                error_count += 1
                scene_error_ids.add(scene_id)

            if not description:
                issues.append({
                    "scene_id": scene_id,
                    "issue": "empty_visual_description",
                    "detail": "visual.description is empty",
                    "suggestion": "Describe what the camera literally sees",
                    "severity": "error",
                })
                error_count += 1
                scene_error_ids.add(scene_id)

            if not on_screen:
                issues.append({
                    "scene_id": scene_id,
                    "issue": "empty_on_screen_text",
                    "detail": "on_screen_text is empty",
                    "suggestion": "Add a brief caption for this scene",
                    "severity": "error",
                })
                error_count += 1
                scene_error_ids.add(scene_id)

            # Check: VO timing fit
            if vo and target_dur > 0:
                estimated = _estimated_speech_seconds(vo)
                if estimated > target_dur * 1.15:
                    word_count = len(vo.split())
                    target_words = int((target_dur * _WORDS_PER_MINUTE) / 60)
                    issues.append({
                        "scene_id": scene_id,
                        "issue": "vo_too_long",
                        "detail": (
                            f"VO estimated {estimated:.1f}s at {_WORDS_PER_MINUTE} WPM "
                            f"vs target {target_dur:.1f}s ({word_count} words)"
                        ),
                        "suggestion": f"Shorten vo_line from {word_count} words to ~{target_words} words",
                        "severity": "warn",
                    })

            # Check: visual specificity
            if description and _is_generic_visual(description):
                issues.append({
                    "scene_id": scene_id,
                    "issue": "visual_too_generic",
                    "detail": f"visual.description is too generic: '{description}'",
                    "suggestion": (
                        "Replace with a concrete, specific description of what the camera sees. "
                        "E.g. 'close-up of a WWII tank turret with battle damage' not 'people talking'."
                    ),
                    "severity": "warn",
                })

        # Check 2: total duration
        scene_total = sum(float(sc.get("target_duration_s") or 0) for sc in scenes if isinstance(sc, dict))
        if target_duration_s > 0 and abs(scene_total - target_duration_s) / target_duration_s > 0.15:
            issues.append({
                "scene_id": "ALL",
                "issue": "timing_mismatch",
                "detail": (
                    f"Scene durations sum to {scene_total:.1f}s, "
                    f"screenplay target is {target_duration_s:.1f}s "
                    f"({abs(scene_total - target_duration_s) / target_duration_s * 100:.0f}% off)"
                ),
                "suggestion": "Adjust scene target_duration_s values to sum to the screenplay target",
                "severity": "warn",
            })

        # Scoring and recommended action
        n_scenes = len([sc for sc in scenes if isinstance(sc, dict)])
        warn_count = sum(1 for i in issues if i.get("severity") == "warn")

        if n_scenes > 0:
            scene_error_ratio = len(scene_error_ids) / n_scenes
        else:
            scene_error_ratio = 1.0

        # Score: start at 1.0, deduct for issues
        score = 1.0
        score -= error_count * 0.2
        score -= warn_count * 0.05
        score = max(0.0, min(1.0, score))

        if scene_error_ratio > 0.5:
            action = "reject"
        elif error_count > 0 or warn_count >= 2:
            action = "revise_scenes"
        else:
            action = "approve"

        return new_feasibility_report(
            screenplay_ref=screenplay_id,
            overall_score=round(score, 2),
            scene_issues=issues,
            recommended_action=action,
        )
