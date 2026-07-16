from pathlib import Path

import pytest

from ai_dev.html_reports import (
    RUNTIME_END,
    RUNTIME_START,
    augment_insights_html,
    build_html_payload,
    build_standalone_html,
)
from ai_dev.instruction_candidates import build_instruction_candidates
from ai_dev.instruction_candidates import render_instruction_candidates_markdown
from ai_dev.feature_extractor import build_feature_bundle
from ai_dev.cli import _display_project_folder


def _report(project: str = "demo-project", snippet: str = "Use src/app.py") -> dict:
    return {
        "total_cost_derived": 4.0,
        "session_features": {"estimated_cache_savings": 1.0},
        "v2": {
            "project_rollup": {
                "composite": 76.0,
                "session_count": 1,
                "recoverable_cost_total_usd": 0.5,
            },
            "per_session_v2": [
                {
                    "session_id": "session-123",
                    "project_folder": project,
                    "session_features": {"total_cost": 4.0, "total_turns": 8, "total_tokens": 1200},
                    "scores": {"composite": 76.0},
                    "convergence": {"shape": "Clean"},
                    "recoverable_cost_total_usd": 0.5,
                    "flags": [
                        {
                            "flag_id": "file_thrash",
                            "severity": "medium",
                            "occurrences": 2,
                            "total_deduction_points": 4.0,
                            "recoverable_cost_usd": 0.5,
                            "description": "Repeated reads.",
                            "remedy": "Retain relevant context.",
                            "evidence": [{"turn_index": 3, "snippet": snippet, "note": "Read src/app.py"}],
                        }
                    ],
                }
            ],
        },
    }


def test_runtime_augmentation_preserves_original_markup_and_is_idempotent(tmp_path: Path) -> None:
    original = "<!doctype html><html><body><nav></nav><h2 id='section-friction'>Friction</h2></body></html>"
    path = tmp_path / "report.html"
    path.write_text(original, encoding="utf-8")

    augment_insights_html(_report(), path)
    first = path.read_text(encoding="utf-8")
    assert "<h2 id='section-friction'>Friction</h2>" in first
    assert first.count(RUNTIME_START) == 1
    assert first.count(RUNTIME_END) == 1
    assert "document.createElement" in first

    augment_insights_html(_report(project="updated-project"), path)
    second = path.read_text(encoding="utf-8")
    assert second.count(RUNTIME_START) == 1
    assert "updated-project" in second
    assert "demo-project" not in second


def test_runtime_payload_escapes_script_breakout(tmp_path: Path) -> None:
    path = tmp_path / "report.html"
    path.write_text("<html><body></body></html>", encoding="utf-8")
    attack = "</script><script>window.pwned=true</script>"
    augment_insights_html(_report(project=attack, snippet=attack), path)
    result = path.read_text(encoding="utf-8")
    assert attack not in result
    assert "\\u003c/script\\u003e" in result


def test_standalone_report_escapes_user_derived_html() -> None:
    attack = "<img src=x onerror=alert(1)>"
    result = build_standalone_html(_report(project=attack, snippet=attack))
    assert attack not in result
    assert "&lt;img src=x onerror=alert(1)&gt;" in result
    assert "Session evidence" in result


def test_reports_redact_common_credentials_before_export() -> None:
    secret = "ghp_1234567890abcdefghij1234567890"
    payload = build_html_payload(_report(snippet=f"Authorization: Bearer {secret}"))
    snippet = payload["sessions"][0]["flags"][0]["evidence"][0]["snippet"]
    assert secret not in snippet
    assert "Authorization: Bearer [REDACTED]" == snippet

    candidates = [{
        "title": "Secret",
        "instruction": f"Authorization: Bearer {secret}",
        "recommended_targets": ["AGENTS.md"],
        "sessions": 2,
        "occurrences": 2,
        "confidence": "high",
    }]
    markdown = render_instruction_candidates_markdown(candidates)
    assert secret not in markdown
    assert "Authorization: Bearer [REDACTED]" in markdown


def test_codex_report_uses_tokens_and_agents_md_when_cost_is_unavailable() -> None:
    report = _report()
    report["source"] = "codex"
    report["total_cost_derived"] = 0.0
    session = report["v2"]["per_session_v2"][0]
    session["session_features"]["total_cost"] = 0.0
    session["recoverable_cost_total_usd"] = 0.0
    report["v2"]["project_rollup"]["recoverable_cost_total_usd"] = 0.0
    html = build_standalone_html(report)
    assert "Codex Session Evidence Report" in html
    assert "Analyzed tokens" in html
    assert "Total spend" not in html

    second = dict(session)
    second["session_id"] = "session-456"
    report["v2"]["per_session_v2"].append(second)
    candidates = build_instruction_candidates(report)
    markdown = render_instruction_candidates_markdown(candidates)
    assert "`AGENTS.md`" in markdown
    assert "CLAUDE.md" not in markdown


def test_legacy_structural_injection_requires_fresh_report(tmp_path: Path) -> None:
    path = tmp_path / "legacy.html"
    path.write_text("<html><body><!-- ai-dev-token-economics-injected --></body></html>", encoding="utf-8")
    with pytest.raises(ValueError, match="legacy structural injection"):
        augment_insights_html(_report(), path)


def test_instruction_candidates_require_cross_session_evidence_for_generic_rules() -> None:
    report = _report()
    assert build_instruction_candidates(report) == []
    second = dict(report["v2"]["per_session_v2"][0])
    second["session_id"] = "session-456"
    report["v2"]["per_session_v2"].append(second)
    candidates = build_instruction_candidates(report)
    assert [row["candidate_id"] for row in candidates] == ["avoid-unnecessary-rereads"]


def test_instruction_candidates_are_partitioned_by_project() -> None:
    report = _report(project="project-a")
    second = dict(report["v2"]["per_session_v2"][0])
    second["session_id"] = "session-a2"
    report["v2"]["per_session_v2"].append(second)
    other = dict(second)
    other["session_id"] = "session-b1"
    other["project_folder"] = "project-b"
    report["v2"]["per_session_v2"].append(other)

    candidates = build_instruction_candidates(report)

    assert len(candidates) == 1
    assert candidates[0]["project"] == "project-a"
    markdown = render_instruction_candidates_markdown(candidates)
    assert "## Project: project-a" in markdown
    assert "Project: project-b" not in markdown


def test_skill_expansion_and_task_notification_are_not_authored_prompts() -> None:
    records = [
        {
            "type": "user",
            "role": "user",
            "sessionId": "s",
            "timestamp": "1",
            "text": "Base directory for this skill: /tmp/example\nDo not edit generated files.",
            "tokens": 20,
            "tokens_effective": 20,
            "cost": 0.0,
            "tool_calls": [],
        },
        {
            "type": "user",
            "role": "user",
            "sessionId": "s",
            "timestamp": "2",
            "text": "<task-notification><task-id>123</task-id></task-notification>",
            "tokens": 10,
            "tokens_effective": 10,
            "cost": 0.0,
            "tool_calls": [],
        },
    ]
    turns = build_feature_bundle(records)["turn_features"]
    assert all(not turn["v2_prompt_detector_eligible"] for turn in turns)

    subagent = dict(records[0])
    subagent["text"] = "Review the transcript and approve the command."
    subagent["_agent_type"] = "subagent"
    subagent["_agent_id"] = "guardian"
    subagent_turn = build_feature_bundle([subagent])["turn_features"][0]
    assert "subagent_user" in subagent_turn["prompt_flags"]
    assert not subagent_turn["v2_prompt_detector_eligible"]


def test_is_meta_skill_payload_is_not_an_authored_prompt() -> None:
    records = [
        {
            "type": "user",
            "role": "user",
            "sessionId": "s",
            "timestamp": "1",
            "text": "# Update Config Skill\nOnly available for tool events: PreToolUse.",
            "isMeta": True,
            "tokens": 20,
            "tokens_effective": 20,
            "cost": 0.0,
            "tool_calls": [],
        }
    ]
    turn = build_feature_bundle(records)["turn_features"][0]
    assert "agent_generated_meta" in turn["prompt_flags"]
    assert not turn["v2_prompt_detector_eligible"]


def test_claude_project_directory_is_rendered_as_a_readable_name() -> None:
    source = "/tmp/-Users-alex-projects-git-demo-app/session.jsonl"
    assert _display_project_folder(source) == "demo-app"
    worktree = "/tmp/-Users-alex-projects-git-demo-app--claude-worktrees-fix-one/session.jsonl"
    assert _display_project_folder(worktree) == "demo-app (worktree: fix-one)"
