from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple

from .scoring_config import ScoringConfig
from .v2_antipatterns import detect_antipatterns_v2
from .v2_convergence import compute_convergence_v2
from .v2_cost_rate import compute_cost_rate_usd_per_token
from .v2_scoring import compute_v2_scores


@dataclass(frozen=True)
class V2Analysis:
    scores: Dict[str, Any]
    dimensions: Dict[str, Any]
    flags: List[Dict[str, Any]]
    deductions: List[Dict[str, Any]]
    convergence: Dict[str, Any]
    cost_rate: Dict[str, Any]
    recoverable_cost_total_usd: float


def analyze_v2(
    turn_features: List[Dict[str, Any]],
    session_features: Dict[str, Any],
    config: Optional[ScoringConfig] = None,
) -> V2Analysis:
    cfg = config or ScoringConfig()

    cost_rate = compute_cost_rate_usd_per_token(turn_features, session_features, cfg)
    convergence = compute_convergence_v2(turn_features, cfg)
    flags = detect_antipatterns_v2(turn_features, session_features, convergence, cost_rate, cfg)
    dimensions, deductions, scores = compute_v2_scores(flags, convergence, cost_rate, cfg)

    return V2Analysis(
        scores=scores,
        dimensions=dimensions,
        flags=flags,
        deductions=deductions,
        convergence=convergence,
        cost_rate=cost_rate,
        recoverable_cost_total_usd=round(sum(float(f.get("recoverable_cost_usd", 0.0) or 0.0) for f in flags), 6),
    )
