from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List

from .redaction import redact_sensitive_text


_CONSTRAINT_NOTE_RE = re.compile(r"^`(?P<constraint>.+)` \(x(?P<count>\d+)\)$")


def _aggregate_flags(report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    aggregated: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"occurrences": 0, "sessions": set(), "evidence": [], "recoverable_cost_usd": 0.0}
    )
    for session in ((report.get("v2") or {}).get("per_session_v2") or []):
        session_id = str(session.get("session_id") or "unknown")
        session_flags = session.get("flags") or []
        raw_recoverable = sum(float(flag.get("recoverable_cost_usd", 0.0) or 0.0) for flag in session_flags)
        capped_recoverable = float(session.get("recoverable_cost_total_usd", 0.0) or 0.0)
        scale = min(1.0, capped_recoverable / raw_recoverable) if raw_recoverable > 0 else 1.0
        for flag in session_flags:
            flag_id = str(flag.get("flag_id") or "")
            if not flag_id:
                continue
            row = aggregated[flag_id]
            row["occurrences"] += int(flag.get("occurrences", 0) or 0)
            row["sessions"].add(session_id)
            row["recoverable_cost_usd"] += float(flag.get("recoverable_cost_usd", 0.0) or 0.0) * scale
            row["evidence"].extend((flag.get("evidence") or [])[:3])
    return aggregated


def build_instruction_candidates(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build conservative, human-approved project-instruction candidates.

    These are proposals only. The analyzer never edits CLAUDE.md or AGENTS.md
    automatically because generated instructions can conflict or inflate context.
    """

    sessions = ((report.get("v2") or {}).get("per_session_v2") or [])
    projects = sorted({str(row.get("project_folder") or "unknown") for row in sessions})
    if len(projects) > 1:
        partitioned: List[Dict[str, Any]] = []
        for project in projects:
            project_report = {
                "source": report.get("source"),
                "v2": {
                    "per_session_v2": [
                        row for row in sessions if str(row.get("project_folder") or "unknown") == project
                    ]
                },
            }
            partitioned.extend(
                {**candidate, "project": project}
                for candidate in build_instruction_candidates(project_report)
            )
        return sorted(
            partitioned,
            key=lambda row: (
                str(row.get("project") or ""),
                0 if row.get("confidence") == "high" else 1,
                -int(row.get("sessions", 0) or 0),
                str(row.get("candidate_id") or ""),
            ),
        )

    flags = _aggregate_flags(report)
    candidates: List[Dict[str, Any]] = []
    targets = ["AGENTS.md"] if report.get("source") == "codex" else ["AGENTS.md", "CLAUDE.md"]

    repeated = flags.get("repeated_constraint")
    if repeated:
        constraints: List[str] = []
        for evidence in repeated["evidence"]:
            match = _CONSTRAINT_NOTE_RE.match(str(evidence.get("note") or ""))
            if match:
                constraint = match.group("constraint").strip()
                if constraint and constraint not in constraints:
                    constraints.append(constraint)
        for index, constraint in enumerate(constraints[:3], 1):
            candidates.append(
                {
                    "candidate_id": f"repeated-constraint-{index}",
                    "title": "Promote a repeated project constraint",
                    "instruction": constraint,
                    "recommended_scope": "project",
                    "recommended_targets": targets,
                    "confidence": "high",
                    "reason": "The same constraint was stated at least three times in session prompts.",
                    "sessions": len(repeated["sessions"]),
                    "occurrences": repeated["occurrences"],
                    "recoverable_cost_usd": round(repeated["recoverable_cost_usd"], 6),
                }
            )

    templates = {
        "file_thrash": {
            "candidate_id": "avoid-unnecessary-rereads",
            "title": "Retain relevant file context",
            "instruction": (
                "After reading a file, retain and reuse the relevant findings. Re-read it only when it may have "
                "changed or when exact content is required for a safe edit."
            ),
            "reason": "Repeated reads of the same files appeared across multiple sessions.",
        },
        "constraint_missing_scaffold": {
            "candidate_id": "request-missing-scaffolding",
            "title": "Resolve missing implementation scaffolding",
            "instruction": (
                "Before implementing, identify missing acceptance criteria, expected output, or verification steps. "
                "Ask a focused question when a missing choice would materially change the result."
            ),
            "reason": "Specific prompts still produced corrections in multiple sessions.",
        },
        "convergence_gate1_miss": {
            "candidate_id": "engage-with-a-bounded-plan",
            "title": "Start with bounded execution",
            "instruction": (
                "Translate the request into a concrete goal, affected files, and verification target before broad "
                "exploration. Begin execution once those are clear."
            ),
            "reason": "Multiple sessions took too long to reach productive execution.",
        },
        "convergence_gate2_failure": {
            "candidate_id": "reset-after-repeated-corrections",
            "title": "Reset after repeated corrections",
            "instruction": (
                "After two related corrections, stop patching incrementally. Restate the complete intent, current "
                "evidence, constraints, and verification plan before continuing."
            ),
            "reason": "Repeated corrections interrupted productive work across multiple sessions.",
        },
    }

    for flag_id, template in templates.items():
        row = flags.get(flag_id)
        if not row or len(row["sessions"]) < 2:
            continue
        candidates.append(
            {
                **template,
                "recommended_scope": "project",
                "recommended_targets": targets,
                "confidence": "medium" if len(row["sessions"]) == 2 else "high",
                "sessions": len(row["sessions"]),
                "occurrences": row["occurrences"],
                "recoverable_cost_usd": round(row["recoverable_cost_usd"], 6),
            }
        )

    return sorted(
        candidates,
        key=lambda row: (
            0 if row.get("confidence") == "high" else 1,
            -int(row.get("sessions", 0) or 0),
            str(row.get("candidate_id") or ""),
        ),
    )


def render_instruction_candidates_markdown(candidates: List[Dict[str, Any]]) -> str:
    targets = sorted({target for row in candidates for target in row.get("recommended_targets", [])})
    target_text = " or ".join(f"`{target}`" for target in targets) or "a project instruction file"
    lines = [
        "# Suggested Agent Instructions",
        "",
        f"These are evidence-backed proposals. Review them before copying any item into {target_text}.",
        "",
    ]
    if not candidates:
        lines.append("No instruction candidate met the promotion threshold.")
        return "\n".join(lines) + "\n"

    project_names = sorted({str(row.get("project") or "") for row in candidates if row.get("project")})
    groups = (
        [(project, [row for row in candidates if row.get("project") == project]) for project in project_names]
        if project_names
        else [("", candidates)]
    )
    for project, rows in groups:
        if project:
            lines.extend([f"## Project: {redact_sensitive_text(project)}", ""])
        heading = "###" if project else "##"
        for candidate in rows:
            lines.extend(
                [
                    f"{heading} {redact_sensitive_text(str(candidate['title']))}",
                    "",
                    redact_sensitive_text(str(candidate["instruction"])),
                    "",
                    (
                        f"Evidence: {candidate['sessions']} session(s), {candidate['occurrences']} occurrence(s); "
                        f"confidence {candidate['confidence']}."
                    ),
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"
