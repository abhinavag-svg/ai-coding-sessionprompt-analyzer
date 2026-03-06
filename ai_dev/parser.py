from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterator, List, cast

from .models import NormalizedEvent, UsageBuckets


def find_jsonl_files(root: Path) -> List[Path]:
    jsonl_files: List[Path] = []
    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            if filename.endswith(".jsonl"):
                jsonl_files.append(Path(dirpath) / filename)
    return jsonl_files


def _parse_usage(payload: Dict) -> UsageBuckets:
    message = cast(Dict, payload.get("message")) if isinstance(payload.get("message"), dict) else {}
    usage = cast(Dict, payload.get("usage")) if isinstance(payload.get("usage"), dict) else {}
    if not usage and isinstance(message.get("usage"), dict):
        usage = message["usage"]

    return UsageBuckets(
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        output_tokens=int(usage.get("output_tokens", 0) or 0),
        cache_write_tokens=int(usage.get("cache_creation_input_tokens", 0) or 0),
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0) or 0),
    )


def _provider_cost(payload: Dict) -> float | None:
    for key in ("cost_usd", "cost", "total_cost", "price"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)

    message = cast(Dict, payload.get("message")) if isinstance(payload.get("message"), dict) else {}
    billing = cast(Dict, message.get("billing")) if isinstance(message.get("billing"), dict) else {}
    for key in ("cost_usd", "total_cost", "amount"):
        value = billing.get(key)
        if isinstance(value, (int, float)):
            return float(value)

    return None


def _is_billable(payload: Dict, usage: UsageBuckets) -> bool:
    if usage.total_tokens <= 0:
        return False

    event_type = str(payload.get("type", "")).lower()
    message = cast(Dict, payload.get("message")) if isinstance(payload.get("message"), dict) else {}
    message_role = str(message.get("role", "")).lower()

    request_id = payload.get("requestId") or payload.get("request_id")
    message_id = message.get("id") if isinstance(message, dict) else None

    if event_type == "assistant" and message_role == "assistant":
        return bool(request_id or message_id)

    if event_type in {"response.completed", "message.completed", "completion"}:
        return True

    return False


def iter_normalized_events(file_path: Path) -> Iterator[NormalizedEvent]:
    with file_path.open("r", encoding="utf-8") as handle:
        for line_num, raw_line in enumerate(handle, 1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            message = cast(Dict, payload.get("message")) if isinstance(payload.get("message"), dict) else {}
            usage = _parse_usage(payload)

            session_id = str(payload.get("sessionId") or payload.get("session_id") or "unknown")
            uuid = str(payload.get("uuid") or "")
            parent_uuid = str(payload.get("parentUuid") or "")
            tool_use_id = str(payload.get("toolUseID") or "")
            parent_tool_use_id = str(payload.get("parentToolUseID") or "")

            agent_id = "primary"
            if "subagents" in file_path.parts:
                # Example: subagents/agent-a11fd04.jsonl -> agent-a11fd04
                agent_id = file_path.stem
            data = payload.get("data")
            if isinstance(data, dict) and isinstance(data.get("agentId"), str) and data["agentId"]:
                agent_id = data["agentId"]

            request_id = str(payload.get("requestId") or payload.get("request_id") or "")
            response_id = str(payload.get("response_id") or "")
            message_api_id = str(message.get("id") or "")
            model = str(payload.get("model") or message.get("model") or "unknown")
            role = str(payload.get("role") or message.get("role") or "")
            event_type = str(payload.get("type") or "")
            timestamp = str(payload.get("timestamp") or "")

            yield NormalizedEvent(
                payload=payload,
                source_file=str(file_path),
                line_num=line_num,
                event_type=event_type,
                session_id=session_id,
                uuid=uuid,
                parent_uuid=parent_uuid,
                tool_use_id=tool_use_id,
                parent_tool_use_id=parent_tool_use_id,
                agent_id=agent_id,
                request_id=request_id,
                response_id=response_id,
                message_api_id=message_api_id,
                model=model,
                role=role,
                timestamp=timestamp,
                is_billable=_is_billable(payload, usage),
                usage=usage,
                provider_cost_usd=_provider_cost(payload),
            )


def load_events(root: Path, billable_only: bool = True) -> List[NormalizedEvent]:
    events: List[NormalizedEvent] = []
    for jsonl_file in find_jsonl_files(root):
        for event in iter_normalized_events(jsonl_file):
            if billable_only and not event.is_billable:
                continue
            events.append(event)
    return events
