"""Freshness classification for architectural decisions.

Per ARCHITECTURE.md section 10:
- Exposes exactly one function: classify(status, drift_count, threshold).
- Returns Literal['fresh', 'stale', 'superseded'].
"""

from typing import Literal


def classify(
    status: str, drift_count: int, threshold: int
) -> Literal["fresh", "stale", "superseded"]:
    """Classify the freshness status of an architectural decision.

    Why: Section 10 specifies:
    - If status == 'superseded': returns 'superseded'.
    - If drift_count >= threshold: returns 'stale'.
    - Otherwise returns 'fresh'.
    """
    if status == "superseded":
        return "superseded"
    return "stale" if drift_count >= threshold else "fresh"
