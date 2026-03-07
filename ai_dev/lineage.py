from __future__ import annotations

from collections import Counter, defaultdict, deque
from typing import Any, Dict, Iterable, List, Tuple


def _short_uuid(u: str, n: int = 8) -> str:
    u = u or ""
    return u[:n]


def group_by_session(turn_features: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in turn_features:
        grouped[str(t.get("session_id", "unknown"))].append(t)
    return grouped


def session_lineage_overview(turn_features: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Compute a compact per-session overview for Markdown reporting.
    """
    out: List[Dict[str, Any]] = []
    for session_id, turns in sorted(group_by_session(turn_features).items(), key=lambda kv: kv[0]):
        user_turns = [t for t in turns if t.get("is_user_turn")]
        assistant_turns = [t for t in turns if t.get("is_assistant_turn")]
        prompts = [t for t in user_turns if (t.get("text") or "").strip()]
        tool_use = sum(int(t.get("tool_use_count", 0) or 0) for t in turns)
        tool_result = sum(int(t.get("tool_result_count", 0) or 0) for t in turns)

        subagent_user = sum(1 for t in user_turns if "subagent_user" in (t.get("prompt_flags") or []))
        agent_meta = sum(1 for t in user_turns if "agent_generated_meta" in (t.get("prompt_flags") or []))
        tool_result_only = sum(1 for t in user_turns if "tool_result_only" in (t.get("prompt_flags") or []))

        top_tools: Counter[str] = Counter()
        for t in turns:
            for name in (t.get("tool_names") or []):
                if isinstance(name, str) and name:
                    top_tools[name] += 1

        out.append(
            {
                "session_id": session_id,
                "total_turns": len(turns),
                "user_turns": len(user_turns),
                "assistant_turns": len(assistant_turns),
                "prompts_non_empty": len(prompts),
                "tool_use_count": tool_use,
                "tool_result_count": tool_result,
                "subagent_user_turns": subagent_user,
                "agent_generated_meta_turns": agent_meta,
                "tool_result_only_user_turns": tool_result_only,
                "top_tools": top_tools.most_common(5),
            }
        )
    return out


def time_window_lineage(
    session_turns: List[Dict[str, Any]],
    prompt_uuid: str,
    max_events: int = 25,
) -> List[str]:
    """
    Build time-window lineage: prompt -> assistant/tool activity -> next user prompt.
    """
    by_uuid = {str(t.get("uuid", "")): t for t in session_turns if t.get("uuid")}
    start = by_uuid.get(prompt_uuid)
    if not start:
        return ["(prompt uuid not found in session turns)"]

    # Identify next user turn after start turn_index
    start_idx = int(start.get("turn_index", 0) or 0)
    ordered = sorted(session_turns, key=lambda t: int(t.get("turn_index", 0) or 0))
    next_user = None
    window: List[Dict[str, Any]] = []
    for t in ordered:
        idx = int(t.get("turn_index", 0) or 0)
        if idx <= start_idx:
            continue
        if t.get("is_user_turn"):
            next_user = t
            break
        if t.get("is_assistant_turn"):
            window.append(t)

    lines: List[str] = []
    flags = ",".join(start.get("prompt_flags") or [])
    lines.append(f"- start user uuid `{prompt_uuid}` flags=[{flags or 'none'}]")
    lines.append(f"  - prompt: {((start.get('text') or '').strip()[:200] + ('...' if len((start.get('text') or '').strip()) > 200 else '')) or '<empty>'}")

    for t in window[:max_events]:
        u = str(t.get("uuid") or "")
        tool_events = t.get("tool_events") or []
        if tool_events:
            for ev in tool_events[:6]:
                if ev.get("kind") == "tool_use":
                    name = ev.get("name") or "tool"
                    fp = ev.get("file_path") or ""
                    cmd = ev.get("command") or ""
                    tid = ev.get("tool_use_id") or ""
                    detail = fp or cmd or ""
                    lines.append(f"  - assistant `{_short_uuid(u)}` tool_use `{name}` id `{_short_uuid(tid)}` {detail}".rstrip())
                elif ev.get("kind") == "tool_result":
                    tid = ev.get("tool_use_id") or ""
                    snippet = ev.get("content_snippet") or ""
                    lines.append(f"  - tool_result id `{_short_uuid(tid)}` {snippet}".rstrip())
        else:
            lines.append(f"  - assistant `{_short_uuid(u)}` (no tools)")

    if next_user:
        u = str(next_user.get("uuid") or "")
        corr = bool(next_user.get("correction_language"))
        flags = ",".join(next_user.get("prompt_flags") or [])
        text = (next_user.get("text") or "").strip()
        lines.append(f"- next user uuid `{u}` correction={str(corr).lower()} flags=[{flags or 'none'}]")
        lines.append(f"  - prompt: {(text[:200] + ('...' if len(text) > 200 else '')) or '<empty>'}")
    else:
        lines.append("- next user: (none; end of session)")

    if len(lines) > (2 + max_events * 2):
        lines = lines[: (2 + max_events * 2)] + ["  - ... (truncated)"]
    return lines


def parent_graph_lineage(
    session_turns: List[Dict[str, Any]],
    prompt_uuid: str,
    max_events: int = 25,
    max_depth: int = 6,
) -> List[str]:
    """
    Build a best-effort lineage view using uuid/parent_uuid relationships plus tool_use links.
    """
    by_uuid: Dict[str, Dict[str, Any]] = {str(t.get("uuid", "")): t for t in session_turns if t.get("uuid")}
    children: Dict[str, List[str]] = defaultdict(list)
    for t in session_turns:
        u = str(t.get("uuid", "") or "")
        p = str(t.get("parent_uuid", "") or "")
        if u and p:
            children[p].append(u)

    # tool_use_id links (tool_use/tool_result within assistant turns)
    tool_uses: Dict[str, Tuple[str, str]] = {}  # tool_use_id -> (assistant_uuid, tool_name)
    tool_results: Dict[str, List[str]] = defaultdict(list)  # tool_use_id -> [assistant_uuid]
    for t in session_turns:
        u = str(t.get("uuid") or "")
        for ev in (t.get("tool_events") or []):
            tid = str(ev.get("tool_use_id") or "")
            if not tid:
                continue
            if ev.get("kind") == "tool_use":
                tool_uses[tid] = (u, str(ev.get("name") or "tool"))
            elif ev.get("kind") == "tool_result":
                tool_results[tid].append(u)

    if prompt_uuid not in by_uuid:
        return ["(prompt uuid not found in session turns)"]

    lines: List[str] = []
    start = by_uuid[prompt_uuid]
    flags = ",".join(start.get("prompt_flags") or [])
    lines.append(f"- start uuid `{prompt_uuid}` flags=[{flags or 'none'}]")

    # Ancestors
    cur = prompt_uuid
    for depth in range(max_depth):
        p = str(by_uuid.get(cur, {}).get("parent_uuid") or "")
        if not p:
            break
        parent = by_uuid.get(p)
        if not parent:
            lines.append(f"  - parent uuid `{p}` (not in dataset)")
            break
        who = "user" if parent.get("is_user_turn") else "assistant" if parent.get("is_assistant_turn") else "event"
        lines.append(f"  - parent[{depth+1}] {who} uuid `{p}`")
        cur = p

    # Descendants BFS
    q = deque([(prompt_uuid, 0)])
    seen = set([prompt_uuid])
    emitted = 0
    while q and emitted < max_events:
        node, depth = q.popleft()
        if depth >= max_depth:
            continue
        for child_uuid in children.get(node, []):
            if child_uuid in seen:
                continue
            seen.add(child_uuid)
            child = by_uuid.get(child_uuid)
            if not child:
                continue
            who = "user" if child.get("is_user_turn") else "assistant" if child.get("is_assistant_turn") else "event"
            lines.append(f"  - child[{depth+1}] {who} uuid `{child_uuid}`")
            emitted += 1

            # Tool link annotations
            for ev in (child.get("tool_events") or []):
                tid = str(ev.get("tool_use_id") or "")
                if tid and tid in tool_uses:
                    au, nm = tool_uses[tid]
                    lines.append(f"    - tool_link `{_short_uuid(tid)}` from `{_short_uuid(au)}` `{nm}`")
                    emitted += 1
                    break

            q.append((child_uuid, depth + 1))
            if emitted >= max_events:
                break

    if emitted >= max_events:
        lines.append("  - ... (truncated)")
    return lines

