import unittest
from collections import Counter


from ai_dev.analyzer_v2 import analyze_v2
from ai_dev.cli import _build_report
from ai_dev.feature_extractor import build_feature_bundle


class TestV2Antipatterns(unittest.TestCase):
    def test_ide_context_turn_is_excluded_from_prompt_duplication(self) -> None:
        prompt = (
            "<ide_selection>"
            + ("Open `shopify.app.toml` and add the GDPR webhooks configuration. " * 12)
            + "</ide_selection>"
        )
        records = [
            {"_uuid": "u1", "type": "user", "role": "user", "timestamp": "t1", "sessionId": "s1", "model": "n/a", "tokens": 60, "tokens_effective": 60, "cost": 0.0, "tool_calls": [], "text": prompt},
        ]
        bundle = build_feature_bundle(records)
        turn = bundle["turn_features"][0]
        self.assertEqual(turn.get("v2_prompt_origin_class"), "ide_context_injection")
        self.assertFalse(bool(turn.get("v2_prompt_detector_eligible")))
        analysis = analyze_v2(bundle["turn_features"], bundle["session_features"])
        ids = {f["flag_id"] for f in analysis.flags}
        self.assertNotIn("prompt_duplication", ids)

    def test_prompt_duplication_fires_on_repeated_blocks(self) -> None:
        block = (
            "1. Open `shopify.app.toml` and add the GDPR webhooks configuration.\n"
            "2. Ensure the billing section uses isTest=true.\n"
        )
        prompt = f"{block}\n{block}"
        records = [
            {"_uuid": "u1", "type": "user", "role": "user", "timestamp": "t1", "sessionId": "s1", "model": "n/a", "tokens": 60, "tokens_effective": 60, "cost": 0.0, "tool_calls": [], "text": prompt},
        ]
        bundle = build_feature_bundle(records)
        analysis = analyze_v2(bundle["turn_features"], bundle["session_features"])
        ids = {f["flag_id"] for f in analysis.flags}
        self.assertIn("prompt_duplication", ids)
        flag = next(f for f in analysis.flags if f["flag_id"] == "prompt_duplication")
        self.assertGreater(float(flag["recoverable_cost_usd"]), 0.0)

    def test_prompt_duplication_ignores_ide_wrappers_but_keeps_true_user_duplicates(self) -> None:
        ide_dup_1 = (
            "<ide_selection>The user selected the lines 9 to 17 from /Users/abhinav/projects/git/app-bloat-auditor/PROMPTS.md: "
            "Refer to PRD.md Section 5 and follow all rules in CLAUDE.md Do exactly 3 things.</ide_selection>\n\n"
            "<ide_selection>The user selected the lines 9 to 17 from /Users/abhinav/projects/git/app-bloat-auditor/PROMPTS.md: "
            "Refer to PRD.md Section 5 and follow all rules in CLAUDE.md Do exactly 3 things.</ide_selection>\n\n"
            "Please continue implementing the selected prompt."
        )
        ide_dup_2 = (
            "<ide_opened_file>The user opened the file /Users/abhinav/projects/git/app-bloat-auditor/app/models/analyzeScripts.ts in the IDE. "
            "This may or may not be related to the current task.</ide_opened_file>\n\n"
            "<ide_opened_file>The user opened the file /Users/abhinav/projects/git/app-bloat-auditor/app/models/analyzeScripts.ts in the IDE. "
            "This may or may not be related to the current task.</ide_opened_file>\n\n"
            "The file already has the KNOWN_APPS dictionary."
        )
        ide_dup_3 = (
            "<ide_selection>The user selected the lines 74 to 78 from /Users/abhinav/projects/git/app-bloat-auditor/PROMPTS.md: "
            "After checking KNOWN_APPS dictionary, if domain is still unmatched, check prisma ScriptDomain.</ide_selection>\n\n"
            "<ide_selection>The user selected the lines 74 to 78 from /Users/abhinav/projects/git/app-bloat-auditor/PROMPTS.md: "
            "After checking KNOWN_APPS dictionary, if domain is still unmatched, check prisma ScriptDomain.</ide_selection>\n\n"
            "Use that as reference."
        )
        ide_dup_4 = (
            "<ide_opened_file>The user opened the file /Users/abhinav/projects/git/app-bloat-auditor/app/models/analyzeScripts.ts in the IDE. "
            "This may or may not be related to the current task.</ide_opened_file>\n\n"
            "<ide_opened_file>The user opened the file /Users/abhinav/projects/git/app-bloat-auditor/app/models/analyzeScripts.ts in the IDE. "
            "This may or may not be related to the current task.</ide_opened_file>\n\n"
            "Open app/models/analyzeScripts.ts and debug analyzeScripts."
        )
        ide_dup_5 = (
            "<ide_opened_file>The user opened the file /Users/abhinav/projects/git/app-bloat-auditor/.react-router/types/app/routes/+types/app._index.ts in the IDE. "
            "This may or may not be related to the current task.</ide_opened_file>\n\n"
            "<ide_opened_file>The user opened the file /Users/abhinav/projects/git/app-bloat-auditor/.react-router/types/app/routes/+types/app._index.ts in the IDE. "
            "This may or may not be related to the current task.</ide_opened_file>\n\n"
            "Refer to PRD.md Section 6."
        )
        ide_dup_6 = (
            "<ide_opened_file>The user opened the file /Users/abhinav/projects/git/app-bloat-auditor/app/routes/app._index.tsx in the IDE. "
            "This may or may not be related to the current task.</ide_opened_file>\n\n"
            "<ide_opened_file>The user opened the file /Users/abhinav/projects/git/app-bloat-auditor/app/routes/app._index.tsx in the IDE. "
            "This may or may not be related to the current task.</ide_opened_file>\n\n"
            "I started the server and hit p."
        )
        true_user_dup_7 = (
            "my terminal is logging no errors. Last 2 lines stay as Preview URL and GraphiQL URL. hitting g works and loads the app.\n\n"
            "my terminal is logging no errors. Last 2 lines stay as Preview URL and GraphiQL URL. hitting g works and loads the app."
        )
        ide_dup_8 = (
            "<ide_opened_file>The user opened the file /Users/abhinav/projects/git/app-bloat-auditor/.react-router/types/app/routes/+types/app._index.ts in the IDE. "
            "This may or may not be related to the current task.</ide_opened_file>\n\n"
            "<ide_opened_file>The user opened the file /Users/abhinav/projects/git/app-bloat-auditor/.react-router/types/app/routes/+types/app._index.ts in the IDE. "
            "This may or may not be related to the current task.</ide_opened_file>\n\n"
            "ok I think here is whats happening."
        )
        ide_dup_9 = (
            "<ide_opened_file>The user opened the file /Users/abhinav/projects/git/app-bloat-auditor/shopify.app.toml in the IDE. "
            "This may or may not be related to the current task.</ide_opened_file>\n\n"
            "<ide_opened_file>The user opened the file /Users/abhinav/projects/git/app-bloat-auditor/shopify.app.toml in the IDE. "
            "This may or may not be related to the current task.</ide_opened_file>\n\n"
            "I got this now from shopify-app-dev."
        )
        true_user_10 = (
            "getting tons of errors now. one example is PrismaClientValidationError: Invalid prisma.session.upsert() getting called."
        )

        records = [
            {"_uuid": "fc634926-a471-420c-942c-43039284e7a5", "type": "user", "role": "user", "timestamp": "2026-02-19T23:03:25.604Z", "sessionId": "db154eb2-1b1a-4f2f-9d5c-5c2affa12bc1", "model": "n/a", "tokens": 80, "tokens_effective": 80, "cost": 0.0, "tool_calls": [], "text": ide_dup_1},
            {"_uuid": "3134a027-725b-4085-9481-9f10a19b20e4", "type": "user", "role": "user", "timestamp": "2026-02-19T23:31:39.462Z", "sessionId": "38d2a2a9-8955-41e0-8cd0-516e6f599598", "model": "n/a", "tokens": 120, "tokens_effective": 120, "cost": 0.0, "tool_calls": [], "text": ide_dup_2},
            {"_uuid": "18b058c0-3739-4915-85fa-18e0d856909a", "type": "user", "role": "user", "timestamp": "2026-02-19T23:35:00.855Z", "sessionId": "38d2a2a9-8955-41e0-8cd0-516e6f599598", "model": "n/a", "tokens": 80, "tokens_effective": 80, "cost": 0.0, "tool_calls": [], "text": ide_dup_3},
            {"_uuid": "15d85817-d487-4a13-b8f6-40172c86692d", "type": "user", "role": "user", "timestamp": "2026-02-19T23:48:13.455Z", "sessionId": "069352d6-ff67-41ce-92c2-006d1aa78b2e", "model": "n/a", "tokens": 100, "tokens_effective": 100, "cost": 0.0, "tool_calls": [], "text": ide_dup_4},
            {"_uuid": "94681214-b361-4e86-80ac-1221cca4cf3a", "type": "user", "role": "user", "timestamp": "2026-02-20T14:29:55.343Z", "sessionId": "46068018-c6dd-4863-9307-455e8b35eb9d", "model": "n/a", "tokens": 90, "tokens_effective": 90, "cost": 0.0, "tool_calls": [], "text": ide_dup_5},
            {"_uuid": "b8a8c91f-b6fd-477a-aaf3-e635b53749d8", "type": "user", "role": "user", "timestamp": "2026-02-20T14:36:39.058Z", "sessionId": "46068018-c6dd-4863-9307-455e8b35eb9d", "model": "n/a", "tokens": 70, "tokens_effective": 70, "cost": 0.0, "tool_calls": [], "text": ide_dup_6},
            {"_uuid": "652f88ba-da96-4269-822f-95ffd68d77ca", "type": "user", "role": "user", "timestamp": "2026-02-20T14:39:50.078Z", "sessionId": "46068018-c6dd-4863-9307-455e8b35eb9d", "model": "n/a", "tokens": 90, "tokens_effective": 90, "cost": 0.0, "tool_calls": [], "text": true_user_dup_7},
            {"_uuid": "9ca7959c-2deb-4d9e-b64f-551b8c193e88", "type": "user", "role": "user", "timestamp": "2026-02-20T15:01:48.543Z", "sessionId": "46068018-c6dd-4863-9307-455e8b35eb9d", "model": "n/a", "tokens": 100, "tokens_effective": 100, "cost": 0.0, "tool_calls": [], "text": ide_dup_8},
            {"_uuid": "a5e6f52d-d2ae-4b36-bae0-538447619e3c", "type": "user", "role": "user", "timestamp": "2026-02-20T15:04:01.510Z", "sessionId": "46068018-c6dd-4863-9307-455e8b35eb9d", "model": "n/a", "tokens": 100, "tokens_effective": 100, "cost": 0.0, "tool_calls": [], "text": ide_dup_9},
            {"_uuid": "8cefeca9-2f69-47fc-9da3-8f8fc7c19307", "type": "user", "role": "user", "timestamp": "2026-02-20T15:21:07.460Z", "sessionId": "46068018-c6dd-4863-9307-455e8b35eb9d", "model": "n/a", "tokens": 90, "tokens_effective": 90, "cost": 0.0, "tool_calls": [], "text": true_user_10},
        ]

        bundle = build_feature_bundle(records)
        analysis = analyze_v2(bundle["turn_features"], bundle["session_features"])
        flag = next((f for f in analysis.flags if f["flag_id"] == "prompt_duplication"), None)
        self.assertIsNotNone(flag)

        evidence_uuids = {str(row.get("uuid") or "") for row in (flag.get("evidence") or [])}
        false_positive_uuids = {
            "fc634926-a471-420c-942c-43039284e7a5",
            "3134a027-725b-4085-9481-9f10a19b20e4",
            "18b058c0-3739-4915-85fa-18e0d856909a",
            "15d85817-d487-4a13-b8f6-40172c86692d",
            "94681214-b361-4e86-80ac-1221cca4cf3a",
            "b8a8c91f-b6fd-477a-aaf3-e635b53749d8",
            "9ca7959c-2deb-4d9e-b64f-551b8c193e88",
            "a5e6f52d-d2ae-4b36-bae0-538447619e3c",
        }
        self.assertFalse(false_positive_uuids & evidence_uuids)
        self.assertIn("652f88ba-da96-4269-822f-95ffd68d77ca", evidence_uuids)

    def test_agent_generated_meta_is_ineligible_for_prompt_content_detectors(self) -> None:
        text = "Your task is to create a detailed summary of the conversation so far.\nwrong wrong wrong\nwrong wrong wrong"
        records = [
            {"_uuid": "u1", "type": "user", "role": "user", "timestamp": "t1", "sessionId": "s1", "model": "n/a", "tokens": 80, "tokens_effective": 80, "cost": 0.0, "tool_calls": [], "text": text},
        ]
        bundle = build_feature_bundle(records)
        turn = bundle["turn_features"][0]
        self.assertEqual(turn.get("v2_prompt_origin_class"), "agent_generated_meta")
        self.assertFalse(bool(turn.get("v2_prompt_detector_eligible")))
        analysis = analyze_v2(bundle["turn_features"], bundle["session_features"])
        ids = {f["flag_id"] for f in analysis.flags}
        self.assertFalse({"prompt_duplication", "repeated_constraint", "vague_opener", "error_dump"} & ids)

    def test_error_dump_fires_on_object_literal_blob(self) -> None:
        blob = """
new error
Error: Unexpected Server Error
'x-frame-options': 'DENY',
'content-security-policy': "default-src 'self'",
'x-content-type-options': 'nosniff',
headers: Headers {
  'x-request-id': 'abc',
  'cf-ray': '123',
  'report-to': '{"endpoints":[{"url":"https://example.com"}],"group":"cf-nel"}',
},
response: Response {
  status: 200,
  statusText: 'OK',
  headers: Headers {
    'content-type': 'application/json; charset=utf-8',
    'strict-transport-security': 'max-age=7889238',
    'x-request-id': 'abc',
    'content-security-policy': "default-src 'self'",
  }
}
"""
        records = [
            {"_uuid": "u1", "type": "user", "role": "user", "timestamp": "t1", "sessionId": "s1", "model": "n/a", "tokens": 220, "tokens_effective": 220, "cost": 0.0, "tool_calls": [], "text": blob},
        ]
        bundle = build_feature_bundle(records)
        analysis = analyze_v2(bundle["turn_features"], bundle["session_features"])
        ids = {f["flag_id"] for f in analysis.flags}
        self.assertIn("error_dump", ids)
        flag = next(f for f in analysis.flags if f["flag_id"] == "error_dump")
        self.assertGreater(float(flag["recoverable_cost_usd"]), 0.0)

    def test_mixed_turn_sets_mixed_content_and_stays_eligible(self) -> None:
        ide = "<ide_selection>" + ("x" * 120) + "</ide_selection>"
        authored = "Please fix app/routes/app.tsx and verify tests pass." + (" y" * 80)
        text = f"{ide}\n{authored}"
        records = [
            {"_uuid": "u1", "type": "user", "role": "user", "timestamp": "t1", "sessionId": "s1", "model": "n/a", "tokens": 90, "tokens_effective": 90, "cost": 0.0, "tool_calls": [], "text": text},
        ]
        bundle = build_feature_bundle(records)
        turn = bundle["turn_features"][0]
        self.assertIn(turn.get("v2_prompt_origin_class"), {"user_prompt", "user_continuation"})
        self.assertTrue(bool(turn.get("v2_mixed_content")))
        self.assertTrue(bool(turn.get("v2_prompt_detector_eligible")))

    def test_file_thrash_and_constraint_scaffold_get_recoverable_cost(self) -> None:
        records = [
            {"_uuid": "u1", "type": "user", "role": "user", "timestamp": "t1", "sessionId": "s1", "model": "n/a", "tokens": 30, "tokens_effective": 30, "cost": 0.0, "tool_calls": [], "text": "Update app/routes/app.tsx action() and verify tests pass."},
            {"_uuid": "a1", "type": "assistant", "role": "assistant", "timestamp": "t2", "sessionId": "s1", "model": "m", "tokens": 100, "tokens_effective": 100, "cost": 1.0, "tool_calls": [{"type": "tool_use", "name": "Read", "input": {"file_path": "app/routes/app.tsx"}}]},
            {"_uuid": "a2", "type": "assistant", "role": "assistant", "timestamp": "t3", "sessionId": "s1", "model": "m", "tokens": 120, "tokens_effective": 120, "cost": 1.0, "tool_calls": [{"type": "tool_use", "name": "Read", "input": {"file_path": "app/routes/app.tsx"}}]},
            {"_uuid": "a3", "type": "assistant", "role": "assistant", "timestamp": "t4", "sessionId": "s1", "model": "m", "tokens": 140, "tokens_effective": 140, "cost": 1.0, "tool_calls": [{"type": "tool_use", "name": "Read", "input": {"file_path": "app/routes/app.tsx"}}]},
            {"_uuid": "u2", "type": "user", "role": "user", "timestamp": "t5", "sessionId": "s1", "model": "n/a", "tokens": 20, "tokens_effective": 20, "cost": 0.0, "tool_calls": [], "text": "Still failing."},
        ]
        bundle = build_feature_bundle(records)
        analysis = analyze_v2(bundle["turn_features"], bundle["session_features"])
        flags = {f["flag_id"]: f for f in analysis.flags}
        self.assertGreater(float(flags["file_thrash"]["recoverable_cost_usd"]), 0.0)
        self.assertGreater(float(flags["constraint_missing_scaffold"]["recoverable_cost_usd"]), 0.0)

    def test_convergence_synthetic_flags_fire(self) -> None:
        records = [
            {"_uuid": "u1", "type": "user", "role": "user", "timestamp": "t1", "sessionId": "s1", "model": "n/a", "tokens": 10, "tokens_effective": 10, "cost": 0.0, "tool_calls": [], "text": "help"},
            {"_uuid": "u2", "type": "user", "role": "user", "timestamp": "t2", "sessionId": "s1", "model": "n/a", "tokens": 18, "tokens_effective": 18, "cost": 0.0, "tool_calls": [], "text": "still wrong"},
            {"_uuid": "u3", "type": "user", "role": "user", "timestamp": "t3", "sessionId": "s1", "model": "n/a", "tokens": 18, "tokens_effective": 18, "cost": 0.0, "tool_calls": [], "text": "try again"},
            {"_uuid": "u4", "type": "user", "role": "user", "timestamp": "t4", "sessionId": "s1", "model": "n/a", "tokens": 18, "tokens_effective": 18, "cost": 0.0, "tool_calls": [], "text": "nope"},
        ]
        bundle = build_feature_bundle(records)
        analysis = analyze_v2(bundle["turn_features"], bundle["session_features"])
        ids = {f["flag_id"] for f in analysis.flags}
        self.assertIn("convergence_gate1_miss", ids)

    def test_build_report_v2_creates_per_session_rollup(self) -> None:
        records = [
            {"_uuid": "u1", "type": "user", "role": "user", "timestamp": "t1", "sessionId": "s1", "model": "n/a", "tokens": 12, "tokens_effective": 12, "cost": 0.0, "tool_calls": [], "text": "Fix app/routes/app.tsx."},
            {"_uuid": "a1", "type": "assistant", "role": "assistant", "timestamp": "t2", "sessionId": "s1", "model": "m", "tokens": 100, "tokens_effective": 100, "cost": 1.0, "tool_calls": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "app/routes/app.tsx"}}]},
            {"_uuid": "u2", "type": "user", "role": "user", "timestamp": "t3", "sessionId": "s2", "model": "n/a", "tokens": 12, "tokens_effective": 12, "cost": 0.0, "tool_calls": [], "text": "Fix app/routes/other.tsx."},
            {"_uuid": "a2", "type": "assistant", "role": "assistant", "timestamp": "t4", "sessionId": "s2", "model": "m", "tokens": 120, "tokens_effective": 120, "cost": 2.0, "tool_calls": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "app/routes/other.tsx"}}]},
        ]
        report = _build_report(
            records,
            multi_agent=True,
            dedupe_stats={"input_events": 4, "output_events": 4, "duplicates_removed": 0},
            cost_sources=Counter({"derived_split": 2}),
            pricing_mode="auto",
            pricing_file="default",
        )
        self.assertIn("per_session_v2", report["v2"])
        self.assertEqual(len(report["v2"]["per_session_v2"]), 2)
        self.assertEqual(int(report["v2"]["project_rollup"]["session_count"]), 2)


if __name__ == "__main__":
    unittest.main()
