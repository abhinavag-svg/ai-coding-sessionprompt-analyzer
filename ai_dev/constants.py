from __future__ import annotations

DEFAULT_MODEL_PRICING_PER_1K = {
    "claude-sonnet": {
        "input": 0.003,
        "output": 0.015,
        "cache_write": 0.00375,
        "cache_read": 0.0003,
    },
    "claude-opus": {
        "input": 0.015,
        "output": 0.075,
        "cache_write": 0.01875,
        "cache_read": 0.0015,
    },
    "gpt-4o": {
        "input": 0.005,
        "output": 0.015,
        "cache_write": 0.0,
        "cache_read": 0.0,
    },
    "gpt-4.1": {
        "input": 0.01,
        "output": 0.03,
        "cache_write": 0.0,
        "cache_read": 0.0,
    },
}

FALLBACK_MODEL_BLENDED_PER_1K = {
    "claude-sonnet": 0.012,
    "claude-opus": 0.03,
    "gpt-4": 0.03,
    "gpt-4o": 0.01,
    "gpt-4.1": 0.02,
    "o1": 0.06,
    "o3": 0.045,
}
