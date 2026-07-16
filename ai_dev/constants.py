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

BUNDLED_CONSERVATIVE_MODEL_PRICING_PER_1K = {
    "claude-sonnet": {
        "input": 0.0025,
        "output": 0.0125,
        "cache_write": 0.003,
        "cache_read": 0.0002,
    },
    "claude-opus": {
        "input": 0.012,
        "output": 0.06,
        "cache_write": 0.015,
        "cache_read": 0.0012,
    },
    "gpt-4o": {
        "input": 0.004,
        "output": 0.012,
        "cache_write": 0.0,
        "cache_read": 0.0,
    },
    "gpt-4.1": {
        "input": 0.008,
        "output": 0.024,
        "cache_write": 0.0,
        "cache_read": 0.0,
    },
}

BUNDLED_CONSERVATIVE_BLENDED_PER_1K = {
    "claude-sonnet": 0.010,
    "claude-opus": 0.025,
    "gpt-4": 0.025,
    "gpt-4o": 0.008,
    "gpt-4.1": 0.016,
    "o1": 0.05,
    "o3": 0.038,
}

BUNDLED_AGGRESSIVE_MODEL_PRICING_PER_1K = {
    "claude-sonnet": {
        "input": 0.0035,
        "output": 0.0175,
        "cache_write": 0.0045,
        "cache_read": 0.0004,
    },
    "claude-opus": {
        "input": 0.018,
        "output": 0.09,
        "cache_write": 0.022,
        "cache_read": 0.0018,
    },
    "gpt-4o": {
        "input": 0.006,
        "output": 0.018,
        "cache_write": 0.0,
        "cache_read": 0.0,
    },
    "gpt-4.1": {
        "input": 0.012,
        "output": 0.036,
        "cache_write": 0.0,
        "cache_read": 0.0,
    },
}

BUNDLED_AGGRESSIVE_BLENDED_PER_1K = {
    "claude-sonnet": 0.014,
    "claude-opus": 0.036,
    "gpt-4": 0.036,
    "gpt-4o": 0.012,
    "gpt-4.1": 0.024,
    "o1": 0.07,
    "o3": 0.052,
}
