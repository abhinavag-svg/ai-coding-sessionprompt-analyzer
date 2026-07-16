from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List

from .models import NormalizedEvent, UsageBuckets


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: List[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        value = item.get("text")
        if isinstance(value, str) and item.get("type") in {"input_text", "output_text", "text"}:
            parts.append(value)
    return "\n".join(parts).strip()


def _tool_name(payload: Dict[str, Any]) -> str:
    raw_name = str(payload.get("name") or payload.get("type") or "tool")
    probe = f"{raw_name}\n{payload.get('arguments') or payload.get('input') or ''}".lower()
    if "apply_patch" in probe or raw_name.lower() in {"edit", "multiedit"}:
        return "Edit"
    if "exec_command" in probe or "write_stdin" in probe or raw_name.lower() in {"bash", "shell"}:
        return "Bash"
    if raw_name.lower() in {"write", "create_file"}:
        return "Write"
    if raw_name.lower() in {"read", "view_image"}:
        return "Read"
    return raw_name


def _tool_input(payload: Dict[str, Any]) -> Dict[str, Any]:
    value = payload.get("arguments") if payload.get("arguments") is not None else payload.get("input")
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        return {"command": value}
    return {}


def _usage_from_token_count(payload: Dict[str, Any]) -> UsageBuckets:
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    last = info.get("last_token_usage") if isinstance(info.get("last_token_usage"), dict) else {}
    input_tokens = int(last.get("input_tokens", 0) or 0)
    cached = min(input_tokens, int(last.get("cached_input_tokens", 0) or 0))
    return UsageBuckets(
        input_tokens=max(0, input_tokens - cached),
        output_tokens=int(last.get("output_tokens", 0) or 0),
        cache_write_tokens=0,
        cache_read_tokens=cached,
    )


def iter_codex_events(file_path: Path) -> Iterator[NormalizedEvent]:
    """Normalize one Codex rollout into authored messages and model rounds.

    Codex rollout JSONL is local product state rather than a stable public API.
    Keeping its interpretation here prevents schema details from leaking into
    scoring and reporting.
    """
    rows: List[tuple[int, Dict[str, Any]]] = []
    with file_path.open("r", encoding="utf-8") as handle:
        for line_num, raw_line in enumerate(handle, 1):
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append((line_num, row))

    session_id = file_path.stem.removeprefix("rollout-")
    project_cwd = ""
    current_model = "unknown"
    agent_id = "primary"
    parent_thread_id = ""
    round_text: List[str] = []
    round_tools: List[Dict[str, Any]] = []
    round_start_line = 0
    round_timestamp = ""
    last_total_usage_signature: tuple[int, int, int, int] | None = None

    def event(
        *,
        line_num: int,
        timestamp: str,
        role: str,
        text: str = "",
        tool_calls: List[Dict[str, Any]] | None = None,
        usage: UsageBuckets | None = None,
        message_id: str = "",
    ) -> NormalizedEvent:
        content: List[Dict[str, Any]] = []
        if text:
            content.append({"type": "text", "text": text})
        content.extend(tool_calls or [])
        normalized_payload: Dict[str, Any] = {
            "type": role,
            "role": role,
            "sessionId": session_id,
            "timestamp": timestamp,
            "message": {
                "id": message_id or f"codex-{session_id}-{line_num}",
                "role": role,
                "model": current_model,
                "content": content,
            },
            "_source_kind": "codex",
            "_agent_type": "subagent" if parent_thread_id else "primary",
            "_agent_id": agent_id,
            "_project_cwd": project_cwd,
            "_project_folder": Path(project_cwd).name if project_cwd else "unknown",
        }
        if text:
            normalized_payload["text"] = text
        return NormalizedEvent(
            payload=normalized_payload,
            source_file=str(file_path),
            line_num=line_num,
            event_type=role,
            session_id=session_id,
            uuid=message_id or f"codex-{session_id}-{line_num}",
            parent_uuid="",
            tool_use_id="",
            parent_tool_use_id="",
            agent_id=agent_id,
            request_id="",
            response_id="",
            message_api_id=message_id or f"codex-{session_id}-{line_num}",
            model=current_model,
            role=role,
            timestamp=timestamp,
            is_billable=bool(usage and usage.total_tokens > 0),
            usage=usage or UsageBuckets(),
            provider_cost_usd=None,
        )

    for line_num, row in rows:
        row_type = str(row.get("type") or "")
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        timestamp = str(row.get("timestamp") or "")

        if row_type == "session_meta":
            child_session_id = str(payload.get("session_id") or payload.get("id") or session_id)
            project_cwd = str(payload.get("cwd") or project_cwd)
            parent_thread_id = str(payload.get("parent_thread_id") or "")
            if parent_thread_id:
                agent_id = child_session_id
                session_id = parent_thread_id
            else:
                session_id = child_session_id
            continue
        if row_type == "turn_context":
            current_model = str(payload.get("model") or current_model)
            project_cwd = str(payload.get("cwd") or project_cwd)
            continue
        if row_type == "response_item":
            item_type = str(payload.get("type") or "")
            role = str(payload.get("role") or "")
            if item_type == "message" and role == "user":
                text = _text_content(payload.get("content"))
                if text:
                    yield event(
                        line_num=line_num,
                        timestamp=timestamp,
                        role="user",
                        text=text,
                        message_id=str(payload.get("id") or f"codex-user-{line_num}"),
                    )
                continue
            if item_type == "message" and role == "assistant":
                text = _text_content(payload.get("content"))
                if text:
                    round_text.append(text)
                    round_start_line = round_start_line or line_num
                    round_timestamp = round_timestamp or timestamp
                continue
            if item_type in {"function_call", "custom_tool_call", "web_search_call", "tool_search_call"}:
                call_id = str(payload.get("call_id") or payload.get("id") or f"codex-tool-{line_num}")
                round_tools.append(
                    {
                        "type": "tool_use",
                        "id": call_id,
                        "name": _tool_name(payload),
                        "input": _tool_input(payload),
                    }
                )
                round_start_line = round_start_line or line_num
                round_timestamp = round_timestamp or timestamp
                continue
        if row_type == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
            total = info.get("total_token_usage") if isinstance(info.get("total_token_usage"), dict) else {}
            total_signature = (
                int(total.get("input_tokens", 0) or 0),
                int(total.get("cached_input_tokens", 0) or 0),
                int(total.get("output_tokens", 0) or 0),
                int(total.get("reasoning_output_tokens", 0) or 0),
            )
            if any(total_signature) and total_signature == last_total_usage_signature:
                round_text = []
                round_tools = []
                round_start_line = 0
                round_timestamp = ""
                continue
            if any(total_signature):
                last_total_usage_signature = total_signature
            usage = _usage_from_token_count(payload)
            if usage.total_tokens > 0:
                yield event(
                    line_num=round_start_line or line_num,
                    timestamp=round_timestamp or timestamp,
                    role="assistant",
                    text="\n".join(round_text).strip(),
                    tool_calls=list(round_tools),
                    usage=usage,
                    message_id=f"codex-round-{session_id}-{line_num}",
                )
            round_text = []
            round_tools = []
            round_start_line = 0
            round_timestamp = ""

    if round_text or round_tools:
        last_line = rows[-1][0] if rows else 0
        last_timestamp = str(rows[-1][1].get("timestamp") or "") if rows else ""
        yield event(
            line_num=round_start_line or last_line,
            timestamp=round_timestamp or last_timestamp,
            role="assistant",
            text="\n".join(round_text).strip(),
            tool_calls=list(round_tools),
            message_id=f"codex-round-{session_id}-final",
        )
