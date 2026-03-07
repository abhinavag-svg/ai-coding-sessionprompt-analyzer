from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from .scoring_config import ScoringConfig


DimensionId = str


DIMENSIONS: Dict[DimensionId, Dict[str, Any]] = {
    "specificity": {"max_points": 25.0, "label": "Specificity"},
    "context_scope": {"max_points": 30.0, "label": "Context Scope"},
    "correction_discipline": {"max_points": 15.0, "label": "Correction Discipline"},
    "model_stability": {"max_points": 10.0, "label": "Model Stability"},
    "session_convergence": {"max_points": 20.0, "label": "Session Convergence"},
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _dim_max(dim: str) -> float:
    return float(DIMENSIONS[dim]["max_points"])


def compute_v2_scores(
    flags: List[Dict[str, Any]],
    convergence: Dict[str, Any],
    cost_rate: Dict[str, Any],
    config: ScoringConfig | None = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """
    V2 scoring is deduction-driven: every point loss is traceable to an anti-pattern flag (cause_code).
    """
    _ = config or ScoringConfig()

    deductions: List[Dict[str, Any]] = []
    by_dim: Dict[str, List[Dict[str, Any]]] = {k: [] for k in DIMENSIONS}

    for flag in flags:
        total = float(flag.get("total_deduction_points", 0.0) or 0.0)
        if total <= 0:
            continue
        for alloc in (flag.get("allocations") or []):
            dim = str(alloc.get("dimension") or "")
            share = float(alloc.get("share", 0.0) or 0.0)
            if dim not in DIMENSIONS or share <= 0:
                continue
            pts = total * share
            d = {
                "dimension": dim,
                "points": round(pts, 3),
                "cause_code": str(alloc.get("cause_code") or flag.get("flag_id") or ""),
                "flag_id": str(flag.get("flag_id") or ""),
                "severity": str(flag.get("severity") or ""),
                "remedy": str(flag.get("remedy") or ""),
                "estimated_recoverable_usd": float(flag.get("recoverable_cost_usd", 0.0) or 0.0),
            }
            by_dim[dim].append(d)
            deductions.append(d)

    # Base dimension points at max, then apply deductions (clamp per dimension first).
    dimensions_out: Dict[str, Any] = {}
    dim_points: Dict[str, float] = {}
    for dim, meta in DIMENSIONS.items():
        max_pts = float(meta["max_points"])
        total_ded = sum(float(d.get("points", 0.0) or 0.0) for d in by_dim.get(dim, []))
        raw = max_pts - total_ded
        clamped = _clamp(raw, 0.0, max_pts)
        dim_points[dim] = clamped
        dimensions_out[dim] = {
            "label": meta["label"],
            "max_points": max_pts,
            "points": round(clamped, 2),
            "raw_points": round(raw, 3),
            "deductions": by_dim.get(dim, []),
        }

    composite = sum(dim_points.values())
    composite = _clamp(composite, 0.0, 100.0)

    scores_out = {
        "composite": round(composite, 2),
        "dimensions": {k: round(v, 2) for k, v in dim_points.items()},
        "session_shape": convergence.get("shape", "unknown"),
        "cost_rate_source": cost_rate.get("source", "unknown"),
    }

    return dimensions_out, deductions, scores_out

