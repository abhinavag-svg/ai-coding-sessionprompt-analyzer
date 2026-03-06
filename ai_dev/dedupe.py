from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any, Dict, List, Tuple

from .models import NormalizedEvent


def _payload_text_len(payload: Dict[str, Any]) -> int:
    # Favor events that preserve user/assistant text content over thin duplicates.
    total = 0
    if isinstance(payload.get("text"), str):
        total += len(payload["text"])

    message = payload.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                if isinstance(item.get("text"), str):
                    total += len(item["text"])
                # Tool blocks sometimes carry relevant string context (paths/commands).
                inp = item.get("input")
                if isinstance(inp, dict):
                    for k in ("file_path", "path", "command", "cmd"):
                        v = inp.get(k)
                        if isinstance(v, str):
                            total += len(v)
    return total


def _tool_block_count(payload: Dict[str, Any]) -> int:
    count = 0
    message = payload.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), list):
        for item in message["content"]:
            if isinstance(item, dict) and item.get("type") in {"tool_use", "tool_result"}:
                count += 1
    if isinstance(payload.get("tool_calls"), list):
        count += len(payload["tool_calls"])
    return count


def _richness(event: NormalizedEvent) -> tuple[int, int, int, int, int]:
    """
    Richness heuristic for duplicate events: higher is better.

    Primary goal: keep the copy that preserves human-readable content.
    """
    payload = event.payload or {}
    text_len = _payload_text_len(payload)
    tool_blocks = _tool_block_count(payload)
    usage_present = 1 if getattr(event, "usage", None) and event.usage.effective_tokens > 0 else 0
    msg_present = 1 if isinstance(payload.get("message"), dict) else 0
    payload_keys = len(payload) if isinstance(payload, dict) else 0
    return (text_len, msg_present, tool_blocks, usage_present, payload_keys)


def _event_key(event: NormalizedEvent) -> str:
    # Prefer stable identity fields from the log payload. Claude JSONL includes a
    # top-level uuid per event record; progress/tool events also include tool ids.
    agent = event.agent_id or "primary"

    # Assistant/user messages: requestId + message.id is the most stable cross-file key
    # (the same message can appear in multiple JSONLs/subagent streams).
    if event.request_id and event.message_api_id:
        return f"req-msg:{event.session_id}:{event.request_id}:{event.message_api_id}"

    if event.message_api_id:
        return f"msg:{event.session_id}:{event.message_api_id}"

    if event.tool_use_id:
        return f"tool:{event.session_id}:{event.tool_use_id}"

    if event.uuid:
        return f"uuid:{event.session_id}:{event.uuid}"

    if event.request_id and event.response_id:
        return f"req-resp:{event.session_id}:{event.request_id}:{event.response_id}"

    for candidate in (event.response_id, event.request_id):
        if candidate:
            return f"id:{event.session_id}:{candidate}"

    # Last resort: hash stable metadata; do not include tokens (cache-heavy and non-identity).
    signature = "|".join(
        [
            event.session_id,
            agent,
            event.event_type,
            event.model,
            event.role,
            event.timestamp,
            event.source_file,
            str(event.line_num),
        ]
    )
    return "sig:" + hashlib.sha1(signature.encode("utf-8")).hexdigest()


def dedupe_events(events: List[NormalizedEvent]) -> Tuple[List[NormalizedEvent], Dict[str, Any]]:
    deduped: List[NormalizedEvent] = []
    seen: Dict[str, int] = {}
    duplicates = 0
    replaced = 0
    dup_by_type: Counter[str] = Counter()
    dup_by_agent: Counter[str] = Counter()

    for event in events:
        key = _event_key(event)
        if key in seen:
            duplicates += 1
            dup_by_type[str(event.event_type or "unknown")] += 1
            dup_by_agent[str(event.agent_id or "primary")] += 1
            existing_idx = seen[key]
            existing = deduped[existing_idx]
            if _richness(event) > _richness(existing):
                deduped[existing_idx] = event
                replaced += 1
            continue
        seen[key] = len(deduped)
        deduped.append(event)

    stats = {
        "input_events": len(events),
        "output_events": len(deduped),
        "duplicates_removed": duplicates,
        "duplicates_replaced": replaced,
        "duplicates_by_event_type": dict(dup_by_type),
        "duplicates_by_agent": dict(dup_by_agent),
    }
    return deduped, stats
