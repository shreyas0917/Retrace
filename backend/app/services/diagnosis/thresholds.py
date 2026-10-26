"""Diagnosis aggregation thresholds (PRD diagnosis_thresholds.v2)."""

from __future__ import annotations

THRESHOLDS_VERSION = "diagnosis_thresholds.v2"

TAU_REL = 0.5
TAU_DISTRACTOR_FRAC = 0.7
TAU_FAITHFUL = 0.85
MIN_RELEVANT_CHUNKS_FOR_SUFFICIENT = 1

# v1.0: decisions whose (calibrated) confidence falls below this value are
# flagged `uncertain` and recommended for manual review. The primary code is
# still reported so metrics stay comparable; callers can choose to abstain.
TAU_UNCERTAIN = 0.5

# Band around TAU_FAITHFUL treated as "near the boundary" for uncertainty
# reporting and explanation text.
FAITHFUL_BOUNDARY_BAND = 0.05
