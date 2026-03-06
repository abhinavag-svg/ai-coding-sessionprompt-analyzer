from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict


class CostSource(str, Enum):
    REPORTED = "reported"
    DERIVED_SPLIT = "derived_split"
    DERIVED_FALLBACK = "derived_fallback"
    UNKNOWN = "unknown"


class CostMode(str, Enum):
    AUTO = "auto"
    REPORTED_ONLY = "reported-only"
    DERIVED_ONLY = "derived-only"


@dataclass
class UsageBuckets:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def incremental_tokens(self) -> int:
        """Tokens produced/consumed in this step excluding cache reads/writes."""
        return self.input_tokens + self.output_tokens

    @property
    def cache_tokens(self) -> int:
        """Tokens attributable to cache read/write mechanisms (provider-specific)."""
        return self.cache_write_tokens + self.cache_read_tokens

    @property
    def effective_tokens(self) -> int:
        """Total tokens that impacted billing/throughput (incremental + cached)."""
        return self.incremental_tokens + self.cache_tokens

    @property
    def total_tokens(self) -> int:
        # Backwards-compatible alias. Prefer `incremental_tokens` or `effective_tokens`
        # depending on metric intent.
        return self.effective_tokens


@dataclass
class NormalizedEvent:
    payload: Dict[str, Any]
    source_file: str
    line_num: int
    event_type: str
    session_id: str
    uuid: str
    parent_uuid: str
    tool_use_id: str
    parent_tool_use_id: str
    agent_id: str
    request_id: str
    response_id: str
    message_api_id: str
    model: str
    role: str
    timestamp: str
    is_billable: bool
    usage: UsageBuckets
    provider_cost_usd: float | None
