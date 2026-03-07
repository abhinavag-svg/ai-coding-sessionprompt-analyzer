from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List
from urllib import error, request

from .v2_scoring import DIMENSIONS


_BULLET_RE = re.compile(r"^(?:[-*•]\s+|\d+[.)]\s+)(.+)$")


@dataclass(frozen=True)
class RecommendationConfig:
    endpoint: str = "http://localhost:11434"
    model: str = "llama3.2:3b"
    timeout_sec: float = 30.0
    include_session_recommendations: bool = False


class OllamaRecommendationProvider:
    def __init__(self, config: RecommendationConfig) -> None:
        self._config = config

    @property
    def config(self) -> RecommendationConfig:
        return self._config

    def availability(self) -> Dict[str, Any]:
        try:
            payload = self._request_json("/api/tags", None)
        except RuntimeError as exc:
            return {
                "status": "unavailable",
                "message": str(exc),
                "provider": "ollama",
                "model": self._config.model,
                "endpoint": self._config.endpoint,
            }

        raw_models = payload.get("models") if isinstance(payload, dict) else []
        models: List[Dict[str, Any]] = [item for item in raw_models if isinstance(item, dict)] if isinstance(raw_models, list) else []
        names = {
            str(item.get("name") or item.get("model") or "")
            for item in models
        }
        if self._config.model not in names:
            return {
                "status": "model_missing",
                "message": (
                    f"Ollama is reachable, but model '{self._config.model}' is not installed. "
                    f"Run: ollama pull {self._config.model}"
                ),
                "provider": "ollama",
                "model": self._config.model,
                "endpoint": self._config.endpoint,
            }

        return {
            "status": "ready",
            "message": "Ollama is reachable and the requested model is installed.",
            "provider": "ollama",
            "model": self._config.model,
            "endpoint": self._config.endpoint,
        }

    def generate(self, scope: str, findings: Dict[str, Any]) -> Dict[str, Any]:
        prompt = _build_prompt(scope, findings)
        try:
            payload = self._request_json(
                "/api/generate",
                {
                    "model": self._config.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "top_p": 0.9,
                        "num_predict": 320,
                    },
                },
            )
        except RuntimeError as exc:
            return {
                "status": "error",
                "message": str(exc),
                "bullets": [],
                "provider": "ollama",
                "model": self._config.model,
                "scope": scope,
            }

        raw = str(payload.get("response") or "").strip() if isinstance(payload, dict) else ""
        if scope == "project":
            sections = _extract_project_sections(raw)
            if not any(sections.values()):
                return {
                    "status": "empty",
                    "message": "The model returned no actionable project recommendations.",
                    "sections": sections,
                    "bullets": [],
                    "raw": raw,
                    "provider": "ollama",
                    "model": self._config.model,
                    "scope": scope,
                }
            return {
                "status": "ready",
                "message": "ok",
                "sections": sections,
                "bullets": _flatten_project_sections(sections),
                "raw": raw,
                "provider": "ollama",
                "model": self._config.model,
                "scope": scope,
            }

        bullets = _extract_bullets(raw)
        if not bullets:
            return {
                "status": "empty",
                "message": "The model returned no actionable bullet points.",
                "bullets": [],
                "raw": raw,
                "provider": "ollama",
                "model": self._config.model,
                "scope": scope,
            }

        return {
            "status": "ready",
            "message": "ok",
            "bullets": bullets[:6],
            "raw": raw,
            "provider": "ollama",
            "model": self._config.model,
            "scope": scope,
        }

    def _request_json(self, path: str, payload: Dict[str, Any] | None) -> Dict[str, Any]:
        url = self._config.endpoint.rstrip("/") + path
        data = None
        headers = {"Accept": "application/json"}
        method = "GET"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
            method = "POST"

        req = request.Request(url, data=data, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=self._config.timeout_sec) as response:
                charset = response.headers.get_content_charset("utf-8")
                body = response.read().decode(charset)
        except error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(
                f"Could not reach Ollama at {self._config.endpoint}. Start it with: ollama serve"
            ) from exc
        except TimeoutError as exc:
            raise RuntimeError(
                f"Timed out waiting for Ollama at {self._config.endpoint}."
            ) from exc

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Ollama returned invalid JSON.") from exc

        if isinstance(parsed, dict) and parsed.get("error"):
            raise RuntimeError(str(parsed.get("error")))
        return parsed if isinstance(parsed, dict) else {}


def enrich_report_with_recommendations(
    report: Dict[str, Any],
    config: RecommendationConfig,
    provider: OllamaRecommendationProvider | None = None,
) -> Dict[str, Any]:
    v2 = report.get("v2") or {}
    project_rollup = v2.get("project_rollup") or {}
    per_session_v2 = list(v2.get("per_session_v2") or [])
    provider = provider or OllamaRecommendationProvider(config)

    recommendation_block: Dict[str, Any] = {
        "enabled": True,
        "provider": "ollama",
        "model": config.model,
        "endpoint": config.endpoint,
        "project_enabled": True,
        "session_enabled": config.include_session_recommendations,
        "project": {},
        "per_session": [],
    }

    availability = provider.availability()
    recommendation_block["availability"] = availability
    if availability.get("status") != "ready":
        recommendation_block["project"] = {
            "status": availability.get("status", "unavailable"),
            "message": availability.get("message", "Recommendations unavailable."),
            "sections": _empty_project_sections(),
            "bullets": [],
        }
        if config.include_session_recommendations:
            recommendation_block["per_session"] = [
                {
                    "session_id": str(row.get("session_id", "unknown")),
                    "status": "skipped",
                    "message": availability.get("message", "Recommendations unavailable."),
                    "bullets": [],
                }
                for row in per_session_v2
            ]
        report["recommendations"] = recommendation_block
        return report

    project_findings = build_project_recommendation_input(report)
    recurring_project_flags = [
        str(item.get("flag_id") or "")
        for item in (project_findings.get("top_flags") or [])
        if int(item.get("session_count", 0) or 0) > 1
    ]

    if _has_actionable_findings(project_findings):
        recommendation_block["project"] = provider.generate("project", project_findings)
    else:
        recommendation_block["project"] = {
            "status": "skipped",
            "message": "No actionable project-level findings.",
            "sections": _empty_project_sections(),
            "bullets": [],
            "scope": "project",
        }

    if not config.include_session_recommendations:
        report["recommendations"] = recommendation_block
        return report

    per_session_results: List[Dict[str, Any]] = []
    for row in per_session_v2:
        findings = build_session_recommendation_input(row, recurring_project_flags=recurring_project_flags)
        session_result: Dict[str, Any]
        if _has_actionable_findings(findings):
            session_result = provider.generate("session", findings)
        else:
            session_result = {
                "status": "skipped",
                "message": "No actionable session-level findings.",
                "bullets": [],
                "scope": "session",
            }
        session_result["session_id"] = str(row.get("session_id", "unknown"))
        per_session_results.append(session_result)

    recommendation_block["per_session"] = per_session_results
    report["recommendations"] = recommendation_block
    return report


def build_project_recommendation_input(report: Dict[str, Any]) -> Dict[str, Any]:
    v2 = report.get("v2") or {}
    project_rollup = v2.get("project_rollup") or {}
    per_session_v2 = list(v2.get("per_session_v2") or [])
    session_features = report.get("session_features") or {}

    top_flags = _aggregate_project_flags(per_session_v2)
    weak_dimensions = _dimension_gaps_from_rollup(project_rollup.get("dimensions") or {})
    high_cost_sessions = []
    for row in sorted(
        per_session_v2,
        key=lambda item: (
            float(item.get("recoverable_cost_total_usd", 0.0) or 0.0),
            float((item.get("session_features") or {}).get("total_cost", 0.0) or 0.0),
        ),
        reverse=True,
    )[:3]:
        high_cost_sessions.append(
            {
                "session_id": str(row.get("session_id", "unknown")),
                "composite": float((row.get("scores") or {}).get("composite", 0.0) or 0.0),
                "recoverable_cost_usd": float(row.get("recoverable_cost_total_usd", 0.0) or 0.0),
                "shape": str((row.get("convergence") or {}).get("shape", "unknown")),
            }
        )

    return {
        "scope": "project",
        "session_count": int(project_rollup.get("session_count", 0) or 0),
        "composite_score": float(project_rollup.get("composite", 0.0) or 0.0),
        "recoverable_cost_total_usd": float(project_rollup.get("recoverable_cost_total_usd", 0.0) or 0.0),
        "weak_dimensions": weak_dimensions,
        "top_flags": top_flags,
        "high_cost_sessions": high_cost_sessions,
        "cost_confidence": str((session_features.get("cost_confidence") or {}).get("level", "unknown")),
    }


def build_session_recommendation_input(
    row: Dict[str, Any],
    recurring_project_flags: List[str] | None = None,
) -> Dict[str, Any]:
    session_features = row.get("session_features") or {}
    top_flags = _session_top_flags(row)
    recurring = set(recurring_project_flags or [])
    local_flags = [flag for flag in top_flags if str(flag.get("flag_id") or "") not in recurring]
    if local_flags:
        top_flags = local_flags

    most_expensive = None
    prompts = list(session_features.get("most_expensive_prompts") or [])
    if prompts:
        prompt = prompts[0]
        most_expensive = {
            "prompt_uuid": str(prompt.get("prompt_uuid", "")),
            "downstream_cost": float(prompt.get("downstream_cost", 0.0) or 0.0),
            "downstream_reads": int(prompt.get("downstream_file_reads", 0) or 0),
            "reasons": list(prompt.get("reasons") or [])[:3],
        }

    return {
        "scope": "session",
        "session_id": str(row.get("session_id", "unknown")),
        "composite_score": float((row.get("scores") or {}).get("composite", 0.0) or 0.0),
        "recoverable_cost_total_usd": float(row.get("recoverable_cost_total_usd", 0.0) or 0.0),
        "shape": str((row.get("convergence") or {}).get("shape", "unknown")),
        "weak_dimensions": _dimension_gaps_from_dimensions(row.get("dimensions") or {}),
        "top_flags": top_flags,
        "most_expensive_prompt": most_expensive,
        "project_themes_already_covered": list(recurring_project_flags or []),
    }


def _aggregate_project_flags(per_session_v2: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in per_session_v2:
        session_id = str(row.get("session_id", "unknown"))
        for flag in (row.get("flags") or []):
            flag_id = str(flag.get("flag_id") or "")
            if not flag_id:
                continue
            current = grouped.setdefault(
                flag_id,
                {
                    "flag_id": flag_id,
                    "description": str(flag.get("description") or ""),
                    "remedy": str(flag.get("remedy") or ""),
                    "occurrences": 0,
                    "session_count": 0,
                    "recoverable_cost_usd": 0.0,
                    "evidence": [],
                    "_sessions": set(),
                },
            )
            current["occurrences"] += int(flag.get("occurrences", 0) or 0)
            current["recoverable_cost_usd"] += float(flag.get("recoverable_cost_usd", 0.0) or 0.0)
            if session_id not in current["_sessions"]:
                current["_sessions"].add(session_id)
                current["session_count"] += 1
            evidence = list(flag.get("evidence") or [])
            if evidence and len(current["evidence"]) < 3:
                current["evidence"].append(_compact_evidence(evidence[0]))

    out = []
    for item in grouped.values():
        item = dict(item)
        item.pop("_sessions", None)
        item["recoverable_cost_usd"] = round(float(item.get("recoverable_cost_usd", 0.0) or 0.0), 4)
        out.append(item)

    out.sort(
        key=lambda item: (
            float(item.get("recoverable_cost_usd", 0.0) or 0.0),
            int(item.get("session_count", 0) or 0),
            int(item.get("occurrences", 0) or 0),
        ),
        reverse=True,
    )
    return out[:3]


def _session_top_flags(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    flags = []
    for flag in list(row.get("flags") or []):
        flags.append(
            {
                "flag_id": str(flag.get("flag_id") or ""),
                "description": str(flag.get("description") or ""),
                "remedy": str(flag.get("remedy") or ""),
                "occurrences": int(flag.get("occurrences", 0) or 0),
                "recoverable_cost_usd": round(float(flag.get("recoverable_cost_usd", 0.0) or 0.0), 4),
                "evidence": [_compact_evidence(item) for item in list(flag.get("evidence") or [])[:2]],
            }
        )
    flags.sort(
        key=lambda item: (
            float(item.get("recoverable_cost_usd", 0.0) or 0.0),
            int(item.get("occurrences", 0) or 0),
        ),
        reverse=True,
    )
    return flags[:3]


def _dimension_gaps_from_rollup(dimensions: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for dim_id, points in dimensions.items():
        meta = DIMENSIONS.get(dim_id)
        if not meta:
            continue
        max_points = float(meta.get("max_points", 0.0) or 0.0)
        pts = float(points or 0.0)
        if pts >= max_points:
            continue
        out.append(
            {
                "dimension": dim_id,
                "label": str(meta.get("label") or dim_id),
                "points": round(pts, 2),
                "max_points": max_points,
                "lost_points": round(max_points - pts, 2),
            }
        )
    out.sort(key=lambda item: float(item.get("lost_points", 0.0) or 0.0), reverse=True)
    return out[:3]


def _dimension_gaps_from_dimensions(dimensions: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for dim_id, data in dimensions.items():
        if not isinstance(data, dict):
            continue
        points = float(data.get("points", 0.0) or 0.0)
        max_points = float(data.get("max_points", 0.0) or 0.0)
        if points >= max_points:
            continue
        grouped_causes: Dict[str, float] = defaultdict(float)
        for deduction in list(data.get("deductions") or [])[:6]:
            grouped_causes[str(deduction.get("cause_code") or deduction.get("flag_id") or "unknown")] += float(deduction.get("points", 0.0) or 0.0)
        out.append(
            {
                "dimension": dim_id,
                "label": str(data.get("label") or dim_id),
                "points": round(points, 2),
                "max_points": max_points,
                "lost_points": round(max_points - points, 2),
                "top_causes": [
                    {"cause_code": key, "points": round(value, 2)}
                    for key, value in sorted(grouped_causes.items(), key=lambda item: item[1], reverse=True)[:3]
                ],
            }
        )
    out.sort(key=lambda item: float(item.get("lost_points", 0.0) or 0.0), reverse=True)
    return out[:3]


def _compact_evidence(evidence: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "turn_index": int(evidence.get("turn_index", 0) or 0),
        "uuid": str(evidence.get("uuid", "")),
        "note": str(evidence.get("note", "")),
        "snippet": str(evidence.get("snippet", "")),
    }


def _has_actionable_findings(findings: Dict[str, Any]) -> bool:
    return bool(findings.get("top_flags") or findings.get("weak_dimensions") or float(findings.get("recoverable_cost_total_usd", 0.0) or 0.0) > 0.0)


def _build_prompt(scope: str, findings: Dict[str, Any]) -> str:
    if scope == "project":
        header = (
            "You are analyzing a Claude coding project post-mortem.\n"
            "Use only the structured findings below.\n"
            "Return valid JSON only, with exactly these keys: you_did_well, absolutely_must_do, nice_to_do.\n"
            "Each value must be an array of 0-3 short strings.\n"
            "Every string must be specific, actionable, and tied to the evidence.\n"
            "Do not mention caching, cache hits, cache savings, or cache configuration.\n"
            "Prioritize repeated cross-session patterns and highest recoverable waste.\n"
            "If a bucket has no strong evidence, return an empty array for it.\n"
        )
    else:
        header = (
            "You are analyzing a Claude coding session post-mortem.\n"
            "Given these structured findings, write 4-6 bullet points for the developer.\n"
            "Each bullet must be specific, actionable, and reference the actual evidence.\n"
            "Never write generic advice. If a finding has no clear action, omit it.\n"
            "Do not mention caching, cache hits, cache savings, or cache configuration.\n"
            "Tone: direct, practical, no filler.\n"
            "Output only markdown bullet points. No heading, no intro, no conclusion.\n"
            "Focus only on the specific session. If project-wide themes are already covered, avoid restating them unless this session has unique evidence.\n"
        )
    return header + "\nStructured findings:\n" + json.dumps(findings, indent=2, sort_keys=True)


def _extract_bullets(text: str) -> List[str]:
    bullets: List[str] = []
    seen = set()
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _BULLET_RE.match(line)
        if match:
            line = match.group(1).strip()
        elif bullets:
            bullets[-1] = bullets[-1] + " " + line
            continue
        else:
            continue
        key = " ".join(line.lower().split())
        if not line or not _is_actionable_text(line):
            continue
        if key and key not in seen:
            seen.add(key)
            bullets.append(line)
    return bullets


def _extract_project_sections(text: str) -> Dict[str, List[str]]:
    payload = _parse_json_object(text)
    if not isinstance(payload, dict):
        return _empty_project_sections()

    sections = _empty_project_sections()
    for key in sections:
        raw_items = payload.get(key)
        if isinstance(raw_items, list):
            sections[key] = _normalize_text_items(raw_items, max_items=3)
    return sections


def _parse_json_object(text: str) -> Dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    candidate = fenced.group(1) if fenced else raw
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None


def _normalize_text_items(items: List[Any], max_items: int) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        if not isinstance(item, str):
            continue
        text = " ".join(item.split()).strip()
        key = text.lower()
        if not text or not _is_actionable_text(text) or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= max_items:
            break
    return out


def _is_actionable_text(text: str) -> bool:
    return "cache" not in text.lower()


def _empty_project_sections() -> Dict[str, List[str]]:
    return {
        "you_did_well": [],
        "absolutely_must_do": [],
        "nice_to_do": [],
    }


def _flatten_project_sections(sections: Dict[str, List[str]]) -> List[str]:
    bullets: List[str] = []
    for key in ("you_did_well", "absolutely_must_do", "nice_to_do"):
        bullets.extend(list(sections.get(key) or []))
    return bullets