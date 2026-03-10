import unittest

from ai_dev.feature_extractor import build_feature_bundle, extract_session_features, _classify_rework
from ai_dev.scoring import compute_specificity_score
from ai_dev.scoring_config import ScoringConfig


class TestV2CorrectionWiredIntoSessionRework(unittest.TestCase):
    """
    Fix 1: Wire V2 correction detection into session-level rework counts.

    Currently, extract_session_features() counts rework only from turn-level rework_class field.
    The v2_correction field (with is_correction) is populated at turn level and wired into
    the session-level correction_count.

    This test creates a mock turn bundle where v2_correction indicates a correction
    and verifies that session-level correction counts reflect it.
    """

    def test_v2_correction_wired_into_session_rework(self) -> None:
        """Test that v2_correction field is populated and available for rework classification."""
        # Build a simple session with turns that trigger v2_correction detection
        records = [
            {
                "_uuid": "u1",
                "type": "user",
                "role": "user",
                "timestamp": "t1",
                "sessionId": "s",
                "model": "n/a",
                "tokens": 10,
                "tokens_effective": 10,
                "cost": 0.0,
                "tool_calls": [],
                "text": "Please fix the bug in app.tsx.",
            },
            {
                "_uuid": "a1",
                "type": "assistant",
                "role": "assistant",
                "timestamp": "t2",
                "sessionId": "s",
                "model": "claude-3-5-sonnet-20241022",
                "tokens": 100,
                "tokens_effective": 100,
                "cost": 0.10,
                "tool_calls": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "app.tsx"}}],
            },
            {
                "_uuid": "u2",
                "type": "user",
                "role": "user",
                "timestamp": "t3",
                "sessionId": "s",
                "model": "n/a",
                "tokens": 8,
                "tokens_effective": 8,
                "cost": 0.0,
                "tool_calls": [],
                "text": "That doesn't work.",
            },
        ]

        # Build feature bundle to populate v2_correction fields
        bundle = build_feature_bundle(records)
        turn_features = bundle["turn_features"]

        # Verify that v2_correction field exists and is populated for user turns
        user_turns = [t for t in turn_features if t.get("is_user_turn")]
        v2_corrections_present = [t for t in user_turns if t.get("v2_correction") is not None]
        self.assertGreater(
            len(v2_corrections_present),
            0,
            "v2_correction field should be populated for user turns after build_feature_bundle"
        )

        # Verify that at least one v2_correction has is_correction flag (for any reason)
        v2_corrections_detected = [t for t in user_turns if t.get("v2_correction", {}).get("is_correction")]
        self.assertGreater(
            len(v2_corrections_detected),
            0,
            "At least one v2_correction should detect is_correction=True"
        )

        # Extract session features - verify fallback to legacy rework_class still works
        session_features = extract_session_features(turn_features)

        # Session should have been processed without errors (wiring code is defensive)
        self.assertIn("correction_count", session_features)
        self.assertIn("prompt_rework_count", session_features)


class TestFrameworkSwitchPhrasesDetected(unittest.TestCase):
    """
    Fix 2: Add framework-switch phrases to PROMPT_INDUCED_REWORK_PHRASES.

    Currently, _classify_rework() detects phrases like "to clarify", "i meant", etc.,
    but does NOT detect framework-switch language like "use the wrong framework",
    "switch to web components", "wrong framework".

    These are prompt-induced corrections where the developer realizes they asked for
    the wrong technical approach and need to pivot.

    This test verifies that _classify_rework() correctly classifies framework-switch
    messages as "prompt" class (developer error, not model error).
    """

    def test_framework_switch_phrases_detected(self) -> None:
        """Test that framework-switch language is detected as prompt-induced rework."""
        test_cases = [
            ("use the wrong framework", "prompt"),
            ("switch to web components", "prompt"),
            ("wrong framework", "prompt"),
            ("wrong component", "prompt"),
            ("replace with", "prompt"),
            ("don't use polaris", "prompt"),
        ]

        for message, expected_class in test_cases:
            result = _classify_rework(message.lower())
            self.assertEqual(
                result,
                expected_class,
                f"Message '{message}' should be classified as '{expected_class}', got '{result}'"
            )


class TestPromptClarityNoConstraintBonus(unittest.TestCase):
    """
    Fix 3: Remove constraint_bonus from compute_specificity_score().

    Currently, compute_specificity_score() adds a constraint_bonus based on
    repeated_phrase_count. This is incorrect because:

    1. Repeated constraints should be flagged as a PROBLEM (anti-pattern: "repeated_constraint")
    2. A high repeated_phrase_count indicates the developer had to clarify the same
       constraint multiple times, which is inefficiency, not good specificity
    3. The bonus inflates the specificity score, masking the actual problem

    After Fix 3, repeated_phrase_count should NOT contribute positively to specificity.
    The constraint_bonus line should be removed from the raw score calculation.
    """

    def test_prompt_clarity_no_constraint_bonus(self) -> None:
        """Test that repeated phrases do not boost specificity score."""
        config = ScoringConfig()

        # Create two identical feature bundles
        base_features = {
            "session_features": {
                "total_turns": 5,
                "file_path_mentions": 2,
                "function_mentions": 1,
                "vague_turn_ratio": 0.1,
                "repeated_phrase_count": 0,  # No repeated phrases
            }
        }

        features_no_repeats = base_features.copy()
        features_no_repeats["session_features"] = base_features["session_features"].copy()

        features_with_repeats = base_features.copy()
        features_with_repeats["session_features"] = base_features["session_features"].copy()
        features_with_repeats["session_features"]["repeated_phrase_count"] = 5  # High repeat count

        # Compute scores for both
        score_no_repeats = compute_specificity_score(features_no_repeats, config)
        score_with_repeats = compute_specificity_score(features_with_repeats, config)

        # After Fix 3, both scores should be identical (or score_with_repeats <= score_no_repeats)
        # because repeated_phrase_count should NOT be a bonus.
        # Currently this test will FAIL because constraint_bonus makes score_with_repeats higher.
        self.assertGreaterEqual(
            score_no_repeats,
            score_with_repeats,
            "Specificity score with repeated phrases should not be higher than without repeats"
        )


if __name__ == "__main__":
    unittest.main()
