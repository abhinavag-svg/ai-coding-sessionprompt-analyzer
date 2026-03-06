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


if __name__ == "__main__":
    unittest.main()
