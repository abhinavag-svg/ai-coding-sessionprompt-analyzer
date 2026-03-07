import unittest


from ai_dev.feature_extractor import build_feature_bundle


class TestPromptWindows(unittest.TestCase):
    def test_most_expensive_prompt_downstream_cost(self) -> None:
        records = [
            {"type": "user", "role": "user", "timestamp": "t1", "sessionId": "s", "model": "n/a", "tokens": 0, "tokens_effective": 0, "cost": 0.0, "tool_calls": [], "text": "Please update app/routes/app.tsx and add a test."},
            {"type": "assistant", "role": "assistant", "timestamp": "t2", "sessionId": "s", "model": "m", "tokens": 100, "tokens_effective": 100, "cache_read_tokens": 0, "cache_write_tokens": 0, "cost": 0.10, "tool_calls": [{"type": "tool_use", "name": "Edit", "input": {}}]},
            {"type": "assistant", "role": "assistant", "timestamp": "t3", "sessionId": "s", "model": "m", "tokens": 50, "tokens_effective": 50, "cache_read_tokens": 0, "cache_write_tokens": 0, "cost": 0.05, "tool_calls": [{"type": "tool_use", "name": "Bash", "input": {"command": "pytest"}}]},
            {"type": "user", "role": "user", "timestamp": "t4", "sessionId": "s", "model": "n/a", "tokens": 0, "tokens_effective": 0, "cost": 0.0, "tool_calls": [], "text": "Looks good."},
        ]
        features = build_feature_bundle(records)["session_features"]
        prompts = features.get("most_expensive_prompts") or []
        self.assertTrue(prompts)
        self.assertAlmostEqual(float(prompts[0]["downstream_cost"]), 0.15, places=6)
        self.assertTrue(str(prompts[0].get("prompt_uuid", "")) == "" or isinstance(prompts[0].get("prompt_uuid", ""), str))
        self.assertEqual(int(prompts[0]["downstream_edits"]), 1)
        self.assertEqual(int(prompts[0]["downstream_tests"]), 1)

    def test_synthetic_user_prompt_does_not_break_window_and_is_excluded(self) -> None:
        records = [
            {"_uuid": "u1", "type": "user", "role": "user", "timestamp": "2026-01-01T00:00:00Z", "sessionId": "s", "model": "n/a", "tokens": 0, "tokens_effective": 0, "cost": 0.0, "tool_calls": [], "text": "Please update app/routes/app.tsx and add a test."},
            {"_uuid": "a1", "type": "assistant", "role": "assistant", "timestamp": "2026-01-01T00:00:01Z", "sessionId": "s", "model": "m", "tokens": 100, "tokens_effective": 100, "cache_read_tokens": 0, "cache_write_tokens": 0, "cost": 0.10, "tool_calls": [{"type": "tool_use", "name": "Edit", "input": {}}]},
            {"_uuid": "u_meta", "type": "user", "role": "user", "timestamp": "2026-01-01T00:00:02Z", "sessionId": "s", "model": "n/a", "tokens": 0, "tokens_effective": 0, "cost": 0.0, "tool_calls": [], "text": "Your task is to create a detailed summary of the conversation so far. Return bullets."},
            {"_uuid": "a2", "type": "assistant", "role": "assistant", "timestamp": "2026-01-01T00:00:03Z", "sessionId": "s", "model": "m", "tokens": 200, "tokens_effective": 200, "cache_read_tokens": 0, "cache_write_tokens": 0, "cost": 0.20, "tool_calls": [{"type": "tool_use", "name": "Bash", "input": {"command": "pytest"}}]},
            {"_uuid": "u2", "type": "user", "role": "user", "timestamp": "2026-01-01T00:00:04Z", "sessionId": "s", "model": "n/a", "tokens": 0, "tokens_effective": 0, "cost": 0.0, "tool_calls": [], "text": "Looks good."},
        ]
        features = build_feature_bundle(records)["session_features"]
        prompts = features.get("most_expensive_prompts") or []
        self.assertTrue(prompts)
        self.assertEqual(str(prompts[0].get("prompt_uuid") or ""), "u1")
        self.assertAlmostEqual(float(prompts[0]["downstream_cost"]), 0.30, places=6)
        synth = prompts[0].get("synthetic_user_turns_in_window") or []
        self.assertEqual(len(synth), 1)
        self.assertEqual(str(synth[0].get("uuid") or ""), "u_meta")

        excluded = features.get("excluded_user_prompts") or []
        self.assertTrue(excluded)
        self.assertEqual(str(excluded[0].get("prompt_uuid") or ""), "u_meta")
        self.assertEqual(str(excluded[0].get("trigger_prompt_uuid") or ""), "u1")
        self.assertIn("agent_generated_meta", excluded[0].get("reasons") or [])


if __name__ == "__main__":
    unittest.main()
