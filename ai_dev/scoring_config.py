from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass
class ScoringConfig:
    """Configuration for all scoring and feature extraction thresholds.

    All values match the current hardcoded defaults to preserve existing behavior.
    Adjust these to tune scoring sensitivity without modifying code.
    """

    # Context scope token band thresholds
    tokens_excellent_max: int = 8_000
    tokens_normal_max: int = 20_000
    tokens_heavy_max: int = 40_000

    # Context scope penalty multipliers
    avg_band_normal_penalty: float = 5.0  # applied over 8k-20k range
    avg_band_heavy_penalty: float = 8.0  # applied over 20k-40k range
    avg_band_over_penalty: float = 8.0  # applied beyond 40k
    median_penalty_multiplier: float = 5.0
    median_penalty_threshold: float = 12_000.0
    p90_penalty_multiplier: float = 7.0
    p90_penalty_threshold: float = 30_000.0
    over_40k_penalty_multiplier: float = 12.0
    file_explosion_penalty: float = 2.0
    tool_call_baseline: float = 3.0
    tool_call_penalty_per_extra: float = 1.5

    # Context scope hard caps
    over_40k_cap_ratio: float = 0.30
    over_40k_cap_score: float = 10.0
    p90_cap_threshold: float = 60_000.0
    p90_cap_score: float = 8.0

    # Correction score thresholds
    prompt_rework_multiplier: float = 60.0
    model_rework_multiplier: float = 80.0
    unknown_rework_multiplier: float = 40.0
    repeated_phrase_penalty: float = 0.5
    high_rework_cap_threshold: float = 0.40
    high_rework_cap_score: float = 10.0
    mid_rework_cap_threshold: float = 0.25
    mid_rework_cap_score: float = 15.0

    # Specificity score thresholds
    file_path_bonus_multiplier: float = 0.15
    file_path_bonus_max: float = 8.0
    function_bonus_multiplier: float = 0.2
    function_bonus_max: float = 7.0
    vague_penalty_multiplier: float = 20.0
    vague_penalty_max: float = 10.0
    specificity_base_score: float = 8.0

    # Feature extractor thresholds
    file_explosion_read_threshold: int = 5  # > this = explosion event
    expensive_turn_cost_threshold: float = 0.05  # >= this = expensive turn
    expensive_turn_token_threshold: int = 40_000  # >= this = expensive turn

    # V2 turn semantics
    new_info_user_lookback_turns: int = 3
    correction_reactive_tokens_high: int = 30
    correction_reactive_tokens_medium: int = 60
    correction_reactive_tokens_low: int = 100
    correction_explicit_dominant_first_n_tokens: int = 60
    correction_explicit_density_min_hits: int = 2
    correction_explicit_density_max_tokens: int = 100

    gate3_settlement_low_token_threshold: int = 30

    # V2 recoverable cost attribution caps
    recoverable_cost_max_turns: int = 5
    recoverable_cost_max_usd: float = 0.50
    recoverable_cost_floor_baseline_usd_per_token: float = 0.00001

    # V2 detector calibration constants
    prompt_duplication_min_block_chars: int = 20
    prompt_duplication_min_block_tokens: int = 4
    file_thrash_free_reads: int = 2

    error_dump_traceback_weight: float = 1.0
    error_dump_object_literal_weight: float = 0.7
    error_dump_punctuation_weight: float = 0.5
    error_dump_fire_ratio: float = 0.45

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ScoringConfig:
        """Create config from dict, using defaults for missing keys."""
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict (useful for serialization/logging)."""
        return asdict(self)


def load_scoring_config(path: Path) -> ScoringConfig:
    """Load scoring config from a JSON file.

    Missing keys use dataclass defaults. Unknown keys are silently ignored.

    Args:
        path: Path to JSON config file

    Returns:
        Populated ScoringConfig instance

    Raises:
        FileNotFoundError: If file does not exist
        json.JSONDecodeError: If JSON is malformed
    """
    if not path.exists():
        raise FileNotFoundError(f"Scoring config file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object (dict) in {path}, got {type(data).__name__}")

    return ScoringConfig.from_dict(data)
