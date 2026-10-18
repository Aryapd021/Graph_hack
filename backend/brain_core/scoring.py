"""Expertise scoring formulas for contributor knowledge ranking.

Per ARCHITECTURE.md section 10:
- Constants W_PR = 1, W_THREAD = 2, W_DECISION = 3.
- Function compute_score(prs, threads, decisions) returns the combined expertise score.
"""

# Why: Weight assigned to authored pull requests touching affected modules
W_PR = 1

# Why: Weight assigned to discussions in threads mentioning affected modules
W_THREAD = 2

# Why: Weight assigned to architectural decisions authored affecting the modules
W_DECISION = 3


def compute_score(prs: int, threads: int, decisions: int) -> int:
    """Calculate the composite who_knows expertise score for a contributor.

    Formula: 1 * prs + 2 * threads + 3 * decisions.
    """
    return (W_PR * prs) + (W_THREAD * threads) + (W_DECISION * decisions)
