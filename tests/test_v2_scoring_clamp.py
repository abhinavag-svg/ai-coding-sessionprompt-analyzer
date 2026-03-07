import unittest


from ai_dev.v2_scoring import compute_v2_scores


class TestV2ScoringClamp(unittest.TestCase):
    def test_overlapping_flags_do_not_drive_dimension_negative(self) -> None:
        flags = [
            {
                "flag_id": "repeated_constraint",
                "severity": "high",
                "remedy": "x",
                "total_deduction_points": 10.0,
                "allocations": [
                    {"dimension": "correction_discipline", "share": 0.75, "cause_code": "repeated_constraint"},
                    {"dimension": "context_scope", "share": 0.25, "cause_code": "repeated_constraint"},
                ],
                "recoverable_cost_usd": 0.0,
            },
            {
                "flag_id": "correction_spiral",
                "severity": "high",
                "remedy": "y",
                "total_deduction_points": 10.0,
                "allocations": [
                    {"dimension": "correction_discipline", "share": 0.30, "cause_code": "correction_spiral"},
                    {"dimension": "session_convergence", "share": 0.70, "cause_code": "correction_spiral"},
                ],
                "recoverable_cost_usd": 0.0,
            },
        ]
        dims, _deductions, scores = compute_v2_scores(flags, convergence={"shape": "Correction-Heavy"}, cost_rate={"source": "hardcoded_fallback"})
        cd = dims["correction_discipline"]
        self.assertGreaterEqual(float(cd["points"]), 0.0)
        self.assertLessEqual(float(cd["points"]), float(cd["max_points"]))
        composite = float(scores["composite"])
        self.assertGreaterEqual(composite, 0.0)
        self.assertLessEqual(composite, 100.0)

    def test_convergence_gate_budget_clamps_correctly(self) -> None:
        flags = [
            {
                "flag_id": "convergence_gate1_miss",
                "severity": "high",
                "remedy": "x",
                "total_deduction_points": 6.0,
                "allocations": [{"dimension": "session_convergence", "share": 1.0, "cause_code": "convergence_gate1_miss"}],
                "recoverable_cost_usd": 0.0,
            },
            {
                "flag_id": "convergence_gate2_failure",
                "severity": "high",
                "remedy": "y",
                "total_deduction_points": 8.0,
                "allocations": [{"dimension": "session_convergence", "share": 1.0, "cause_code": "convergence_gate2_failure"}],
                "recoverable_cost_usd": 0.0,
            },
        ]
        dims, _deductions, _scores = compute_v2_scores(flags, convergence={"shape": "Correction-Heavy"}, cost_rate={"source": "hardcoded_fallback"})
        self.assertEqual(float(dims["session_convergence"]["points"]), 6.0)

        flags.append(
            {
                "flag_id": "abandoned_session",
                "severity": "high",
                "remedy": "z",
                "total_deduction_points": 8.0,
                "allocations": [{"dimension": "session_convergence", "share": 1.0, "cause_code": "abandoned_session"}],
                "recoverable_cost_usd": 0.0,
            }
        )
        dims, _deductions, _scores = compute_v2_scores(flags, convergence={"shape": "Abandoned"}, cost_rate={"source": "hardcoded_fallback"})
        self.assertEqual(float(dims["session_convergence"]["points"]), 0.0)


if __name__ == "__main__":
    unittest.main()
