"""Image alignment evaluator interface.

Phase 1 (issue 1.7): passthrough implementation that returns the first available candidate.
Phase 2 (issue 2.6): replace select_best() with a rubric-scored multi-axis evaluator
(subject match, setting match, style match, artifact penalty).
"""

from __future__ import annotations

from typing import Any


class ImageAlignmentEvaluator:
    """Selects the best image candidate for a scene.

    The passthrough implementation returns the first candidate, which is already
    ranked by ScriptImageRetrievalAgent's alt-text relevance scorer.

    Issue 2.6 will replace this with a scored rubric evaluator using a
    vision-capable model (local or API-backed).
    """

    def select_best(
        self,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Return the best candidate from the pool.

        Args:
            candidates: Candidate dicts, pre-ranked by relevance score
                (highest score first, as produced by ScriptImageRetrievalAgent).

        Returns:
            The first candidate, or None if the list is empty.
        """
        return candidates[0] if candidates else None
