import unittest

from ai_dev.llm_recommendations import (
    RecommendationConfig,
    build_project_recommendation_input,
    build_session_recommendation_input,
    enrich_report_with_recommendations,
    _extract_bullets,
    _extract_project_sections,
)
from ai_dev.reporter import build_markdown_report


def _sample_report() -> dict:
    session_one = {
        "session_id": "s1",
        "session_features": {
            "estimated_no_cache_cost": 4.0,
            "estimated_cache_savings": 1.0,
            "no_cache_estimate_turns": 3,
            "assistant_turn_count": 4,
            "most_expensive_prompts": [
                {
                    "prompt_uuid": "p1",
                    "downstream_cost": 1.8,
                    "downstream_file_reads": 4,
                    "reasons": ["repeated file reads", "vague opener"],
                }
            ],
            "total_cost": 2.2,
            "total_turns": 6,
            "total_tokens": 300,
        },
        "scores": {"composite": 64.0},
        "dimensions": {
            "context_scope": {
                "label": "Context Scope",
                "points": 18.0,
                "max_points": 30.0,
                "deductions": [
                    {"cause_code": "file_thrash", "points": 6.0, "flag_id": "file_thrash"},
                    {"cause_code": "repeated_constraint", "points": 3.0, "flag_id": "repeated_constraint"},
                ],
            },
            "session_convergence": {
                "label": "Session Convergence",
                "points": 9.0,
                "max_points": 20.0,
                "deductions": [
                    {"cause_code": "correction_spiral", "points": 7.0, "flag_id": "correction_spiral"}
                ],
            },
        },
        "flags": [
            {
                "flag_id": "repeated_constraint",
                "description": "Constraint repeated across user turns.",
                "remedy": "Move stable rules into the project prompt.",
                "occurrences": 2,
                "recoverable_cost_usd": 0.7,
                "evidence": [{"turn_index": 2, "uuid": "u2", "snippet": "Do not touch payments", "note": ""}],
            },
            {
                "flag_id": "file_thrash",
                "description": "Same file was re-read multiple times.",
                "remedy": "Summarize file state after the first read.",
                "occurrences": 3,
                "recoverable_cost_usd": 1.3,
                "evidence": [{"turn_index": 4, "uuid": "a4", "snippet": "Read app/routes/app.tsx again", "note": ""}],
            },
        ],
        "convergence": {"shape": "Correction-Heavy"},
        "cost_rate": {"usd_per_token": 0.001, "source": "derived_split", "confidence": "high"},
        "recoverable_cost_total_usd": 2.0,
    }
    session_two = {
        "session_id": "s2",
        "session_features": {
            "estimated_no_cache_cost": 2.0,
            "estimated_cache_savings": 0.2,
            "no_cache_estimate_turns": 2,
            "assistant_turn_count": 2,
            "most_expensive_prompts": [],
            "total_cost": 1.0,
            "total_turns": 3,
            "total_tokens": 120,
        },
        "scores": {"composite": 79.0},
        "dimensions": {
            "correction_discipline": {
                "label": "Correction Discipline",
                "points": 11.0,
                "max_points": 15.0,
                "deductions": [
                    {"cause_code": "repeated_constraint", "points": 4.0, "flag_id": "repeated_constraint"}
                ],
            }
        },
        "flags": [
            {
                "flag_id": "repeated_constraint",
                "description": "Constraint repeated across user turns.",
                "remedy": "Move stable rules into the project prompt.",
                "occurrences": 1,
                "recoverable_cost_usd": 0.4,
                "evidence": [{"turn_index": 1, "uuid": "u9", "snippet": "Never edit billing", "note": ""}],
            }
        ],
        "convergence": {"shape": "Settling"},
        "cost_rate": {"usd_per_token": 0.001, "source": "derived_split", "confidence": "high"},
        "recoverable_cost_total_usd": 0.4,
    }
    return {
        "session_features": {
            "estimated_no_cache_cost": 10.0,
            "estimated_cache_savings": 3.0,
            "no_cache_estimate_turns": 5,
            "assistant_turn_count": 6,
            "cost_confidence": {"level": "estimated"},
            "total_turns": 9,
            "total_tokens": 420,
            "total_effective_tokens": 420,
            "total_cache_read_tokens": 0,
            "total_cache_write_tokens": 0,
            "tokens_per_turn_avg": 46,
            "tokens_per_turn_median": 40,
            "tokens_per_turn_p90": 90,
            "effective_tokens_per_turn_avg": 46,
            "effective_tokens_per_turn_median": 40,
            "effective_tokens_per_turn_p90": 90,
            "over_40k_turn_ratio": 0.0,
            "total_cost": 3.2,
            "cost_per_turn": 0.35,
            "correction_ratio": 0.22,
            "prompt_rework_count": 1,
            "prompt_rework_ratio": 0.11,
            "model_rework_count": 1,
            "model_rework_ratio": 0.11,
            "unknown_rework_count": 0,
            "unknown_rework_ratio": 0.0,
            "user_turn_count": 3,
            "file_explosion_events": 0,
        },
        "turn_features": [],
        "rule_violations": [],
        "scores": {"composite": 73.0},
        "v2": {
            "scores": {"composite": 73.0},
            "project_rollup": {
                "session_count": 2,
                "dimensions": {
                    "specificity": 22.0,
                    "context_scope": 19.0,
                    "correction_discipline": 12.0,
                    "model_stability": 10.0,
                    "session_convergence": 11.0,
                },
                "composite": 74.0,
                "recoverable_cost_total_usd": 2.4,
                "flag_frequency": {"repeated_constraint": 3, "file_thrash": 3},
                "session_efficiency_distribution": [],
            },
            "per_session_v2": [session_one, session_two],
        },
        "multi_agent": False,
    }


class _ReadyProvider:
    def __init__(self) -> None:
        self.scopes = []

    def availability(self) -> dict:
        return {"status": "ready", "message": "ok"}

    def generate(self, scope: str, findings: dict) -> dict:
        self.scopes.append((scope, findings.get("scope"), findings.get("session_id")))
        bullet = f"{scope} recommendation for {findings.get('session_id', 'project')}"
        if scope == "project":
            return {
                "status": "ready",
                "message": "ok",
                "sections": {
                    "you_did_well": ["You kept one instruction set stable across sessions."],
                    "absolutely_must_do": [bullet],
                    "nice_to_do": ["Document the stable prompt rules once."],
                },
                "bullets": [bullet],
                "scope": scope,
            }
        return {"status": "ready", "message": "ok", "bullets": [bullet], "scope": scope}


class _UnavailableProvider:
    def availability(self) -> dict:
        return {"status": "model_missing", "message": "Run: ollama pull llama3.2:3b"}

    def generate(self, scope: str, findings: dict) -> dict:
        raise AssertionError("generate should not be called when unavailable")


class TestLLMRecommendations(unittest.TestCase):
    def test_build_project_recommendation_input_aggregates_cross_session_flags(self) -> None:
        findings = build_project_recommendation_input(_sample_report())
        self.assertEqual(findings["scope"], "project")
        self.assertEqual(findings["session_count"], 2)
        self.assertTrue(findings["weak_dimensions"])
        self.assertEqual(findings["top_flags"][0]["flag_id"], "file_thrash")
        self.assertNotIn("caching_health", findings)
        repeated = next(item for item in findings["top_flags"] if item["flag_id"] == "repeated_constraint")
        self.assertEqual(repeated["session_count"], 2)

    def test_build_session_recommendation_input_filters_project_theme_when_possible(self) -> None:
        report = _sample_report()
        row = report["v2"]["per_session_v2"][0]
        findings = build_session_recommendation_input(row, recurring_project_flags=["repeated_constraint"])
        self.assertEqual(findings["scope"], "session")
        self.assertEqual(findings["session_id"], "s1")
        self.assertEqual(findings["top_flags"][0]["flag_id"], "file_thrash")
        self.assertEqual(findings["most_expensive_prompt"]["prompt_uuid"], "p1")
        self.assertNotIn("caching_health", findings)

    def test_enrich_report_with_recommendations_defaults_to_project_only(self) -> None:
        report = _sample_report()
        provider = _ReadyProvider()
        enriched = enrich_report_with_recommendations(report, RecommendationConfig(), provider=provider)
        recs = enriched["recommendations"]
        self.assertEqual(recs["project"]["status"], "ready")
        self.assertFalse(recs["session_enabled"])
        self.assertEqual(recs["per_session"], [])
        self.assertIn("project", [scope for scope, _, _ in provider.scopes])
        self.assertNotIn("session", [scope for scope, _, _ in provider.scopes])

    def test_enrich_report_with_recommendations_populates_sessions_when_enabled(self) -> None:
        report = _sample_report()
        provider = _ReadyProvider()
        enriched = enrich_report_with_recommendations(
            report,
            RecommendationConfig(include_session_recommendations=True),
            provider=provider,
        )
        recs = enriched["recommendations"]
        self.assertTrue(recs["session_enabled"])
        self.assertEqual(len(recs["per_session"]), 2)
        self.assertIn("session", [scope for scope, _, _ in provider.scopes])

    def test_enrich_report_with_recommendations_handles_unavailable_ollama(self) -> None:
        report = _sample_report()
        enriched = enrich_report_with_recommendations(report, RecommendationConfig(), provider=_UnavailableProvider())
        self.assertEqual(enriched["recommendations"]["project"]["status"], "model_missing")
        self.assertEqual(enriched["recommendations"]["per_session"], [])

    def test_enrich_report_with_recommendations_marks_session_recommendations_skipped_when_unavailable(self) -> None:
        report = _sample_report()
        enriched = enrich_report_with_recommendations(
            report,
            RecommendationConfig(include_session_recommendations=True),
            provider=_UnavailableProvider(),
        )
        self.assertEqual(enriched["recommendations"]["per_session"][0]["status"], "skipped")

    def test_extract_helpers_filter_cache_language(self) -> None:
        bullets = _extract_bullets("- Fix the repeated file reads.\n- Improve cache usage.")
        self.assertEqual(bullets, ["Fix the repeated file reads."])

        sections = _extract_project_sections(
            '{"you_did_well": ["Kept changes scoped."], "absolutely_must_do": ["Fix cache handling."], "nice_to_do": ["Write one reusable task brief."]}'
        )
        self.assertEqual(sections["absolutely_must_do"], [])
        self.assertEqual(sections["you_did_well"], ["Kept changes scoped."])

    def test_markdown_report_renders_project_and_session_recommendations(self) -> None:
        report = _sample_report()
        report["recommendations"] = {
            "project": {
                "status": "ready",
                "sections": {
                    "you_did_well": ["Project-level praise."],
                    "absolutely_must_do": ["Project-level must do."],
                    "nice_to_do": ["Project-level nice to do."],
                },
            },
            "per_session": [
                {"session_id": "s1", "status": "ready", "bullets": ["Session-one advice."]},
                {"session_id": "s2", "status": "ready", "bullets": ["Session-two advice."]},
            ],
        }
        markdown = build_markdown_report(report)
        self.assertIn("## Project Recommendations (LLM)", markdown)
        self.assertIn("### You did well", markdown)
        self.assertIn("Project-level must do.", markdown)
        self.assertIn("recommendations (LLM)", markdown)
        self.assertIn("Session-one advice.", markdown)


if __name__ == "__main__":
    unittest.main()