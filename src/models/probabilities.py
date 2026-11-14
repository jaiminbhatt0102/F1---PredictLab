"""Make per-driver probabilities consistent within one race.

Each race has exactly one winner and exactly three podium finishers, so the chances across
the whole field must add up to 1 (win) and 3 (podium). Models score each driver on their
own and do not guarantee that; these helpers fix it per race.
"""
from __future__ import annotations

import numpy as np


def normalize_win(p: np.ndarray) -> np.ndarray:
    """Scale so the field's win chances add up to exactly 1."""
    p = np.clip(np.asarray(p, dtype=float), 0.0, 1.0)
    total = p.sum()
    return p / total if total > 0 else p


def normalize_podium(p: np.ndarray, places: int = 3) -> np.ndarray:
    """Scale so podium chances add up to `places`, with no driver above 100%."""
    p = np.clip(np.asarray(p, dtype=float), 0.0, 1.0)
    if len(p) <= places:
        return np.ones_like(p)
    if p.sum() <= 0:
        return np.full_like(p, places / len(p))
    lo, hi = 0.0, 1.0
    while np.minimum(1.0, hi * p).sum() < places:
        hi *= 2.0
        if hi > 1e9:
            break
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if np.minimum(1.0, mid * p).sum() < places:
            lo = mid
        else:
            hi = mid
    return np.minimum(1.0, hi * p)
