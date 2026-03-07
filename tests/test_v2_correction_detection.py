import unittest


from ai_dev.feature_extractor import build_feature_bundle


class TestV2CorrectionDetection(unittest.TestCase):
    def test_tool_result_only_turns_do_not_break_prev_scorable(self) -> None:
        records = [
            {"_uuid": "u1", "type": "user", "role": "user", "timestamp": "t1", "sessionId": "s", "model": "n/a", "tokens": 10, "tokens_effective": 10, "cost": 0.0, "tool_calls": [], "text": "Please fix app/routes/app.tsx."},
            {"_uuid": "a1", "type": "assistant", "role": "assistant", "timestamp": "t2", "sessionId": "s", "model": "m", "tokens": 100, "tokens_effective": 100, "cost": 0.10, "tool_calls": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "app/routes/app.tsx"}}]},
            # Synthetic user prompt: tool_result-only, should be non-scorable for V2 purposes.
            {"_uuid": "u_meta", "type": "user", "role": "user", "timestamp": "t3", "sessionId": "s", "model": "n/a", "tokens": 5, "tokens_effective": 5, "cost": 0.0, "tool_calls": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}], "text": ""},
            {"_uuid": "u2", "type": "user", "role": "user", "timestamp": "t4", "sessionId": "s", "model": "n/a", "tokens": 20, "tokens_effective": 20, "cost": 0.0, "tool_calls": [], "text": "Still failing."},
        ]
        bundle = build_feature_bundle(records)
        turns = bundle["turn_features"]
        u2 = next(t for t in turns if t.get("uuid") == "u2")
        self.assertTrue(bool(u2.get("v2_prev_was_assistant_with_tool_use")))
        corr = u2.get("v2_correction") or {}
        self.assertTrue(bool(corr.get("is_correction")))
        self.assertIn(str(corr.get("confidence") or ""), {"high", "medium", "low"})

    def test_long_feature_request_with_broken_late_is_not_correction(self) -> None:
        long_text = (
            "Please add a new feature in app/routes/new_feature.tsx that supports the edge case where X happens. "
            "Include unit tests and update the README. "
            + ("more details " * 120)
            + "By the way the app is broken in production."
        )
        records = [
            {"_uuid": "u1", "type": "user", "role": "user", "timestamp": "t1", "sessionId": "s", "model": "n/a", "tokens": 50, "tokens_effective": 50, "cost": 0.0, "tool_calls": [], "text": "Fix app/routes/app.tsx."},
            {"_uuid": "a1", "type": "assistant", "role": "assistant", "timestamp": "t2", "sessionId": "s", "model": "m", "tokens": 200, "tokens_effective": 200, "cost": 0.20, "tool_calls": [{"type": "tool_use", "name": "Bash", "input": {"command": "pytest"}}]},
            {"_uuid": "u2", "type": "user", "role": "user", "timestamp": "t3", "sessionId": "s", "model": "n/a", "tokens": 500, "tokens_effective": 500, "cost": 0.0, "tool_calls": [], "text": long_text},
        ]
        bundle = build_feature_bundle(records)
        turns = bundle["turn_features"]
        u2 = next(t for t in turns if t.get("uuid") == "u2")
        corr = u2.get("v2_correction") or {}
        self.assertFalse(bool(corr.get("is_correction")))
        self.assertEqual(str(corr.get("confidence") or ""), "none")

    def test_ide_dominated_turn_still_participates_in_correction_detection(self) -> None:
        records = [
            {"_uuid": "u1", "type": "user", "role": "user", "timestamp": "t1", "sessionId": "s", "model": "n/a", "tokens": 12, "tokens_effective": 12, "cost": 0.0, "tool_calls": [], "text": "Fix app/routes/app.tsx."},
            {"_uuid": "a1", "type": "assistant", "role": "assistant", "timestamp": "t2", "sessionId": "s", "model": "m", "tokens": 100, "tokens_effective": 100, "cost": 0.10, "tool_calls": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "app/routes/app.tsx"}}]},
            {
                "_uuid": "u2",
                "type": "user",
                "role": "user",
                "timestamp": "t3",
                "sessionId": "s",
                "model": "n/a",
                "tokens": 40,
                "tokens_effective": 40,
                "cost": 0.0,
                "tool_calls": [],
                "text": "<ide_opened_file>The user opened the file /tmp/x.py</ide_opened_file>\n<ide_selection>broken broken broken</ide_selection>\nthis is broken again",
            },
        ]
        bundle = build_feature_bundle(records)
        u2 = next(t for t in bundle["turn_features"] if t.get("uuid") == "u2")
        self.assertEqual(u2.get("v2_prompt_origin_class"), "ide_context_injection")
        self.assertFalse(bool(u2.get("v2_prompt_detector_eligible")))
        corr = u2.get("v2_correction") or {}
        self.assertTrue(bool(corr.get("is_correction")))
        self.assertIn(str(corr.get("confidence") or ""), {"high", "medium", "low"})


if __name__ == "__main__":
    unittest.main()
