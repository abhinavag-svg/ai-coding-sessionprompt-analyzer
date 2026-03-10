"""Tests for the Insights HTML injection feature."""

from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from ai_dev.reporter import inject_into_insights_html, _build_insights_injection_html


class TestInsightsInjection(unittest.TestCase):
    """Test suite for inject_into_insights_html functionality."""

    def setUp(self):
        """Create test fixtures."""
        self.minimal_html = """<!DOCTYPE html>
<html>
<head><title>Claude Code Insights</title></head>
<body>
<h1>Session Report</h1>
<p>Content here</p>
</body>
</html>"""

        self.test_report = {
            "total_cost_derived": 42.50,
            "session_features": {
                "estimated_cache_savings": 12.30,
            },
            "v2": {
                "project_rollup": {
                    "composite": 78.5,
                    "recoverable_cost_total_usd": 8.75,
                    "session_efficiency_distribution": [
                        {
                            "session_id": "session-001",
                            "composite": 85.0,
                            "cost": 15.00,
                            "shape": "Clean",
                            "recoverable_cost_total_usd": 2.50,
                        },
                        {
                            "session_id": "session-002",
                            "composite": 72.0,
                            "cost": 10.00,
                            "shape": "Correction-Heavy",
                            "recoverable_cost_total_usd": 3.25,
                        },
                    ],
                },
                "per_session_v2": [
                    {
                        "session_id": "session-001",
                        "flags": [
                            {
                                "flag_id": "file_thrash",
                                "recoverable_cost_usd": 2.50,
                                "occurrences": 3,
                            }
                        ],
                    },
                    {
                        "session_id": "session-002",
                        "flags": [
                            {
                                "flag_id": "convergence_gate1_miss",
                                "recoverable_cost_usd": 3.25,
                                "occurrences": 1,
                            }
                        ],
                    },
                ],
            },
        }

    def test_injection_creates_section(self):
        """Test that injection creates the ai-dev-token-economics section."""
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = Path(tmpdir) / "test.html"
            html_path.write_text(self.minimal_html)

            inject_into_insights_html(self.test_report, html_path)

            result = html_path.read_text()
            self.assertIn("ai-dev-token-economics", result)
            self.assertIn("Token Economics (via ai-dev)", result)

    def test_injection_preserves_original_content(self):
        """Test that original HTML content is preserved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = Path(tmpdir) / "test.html"
            html_path.write_text(self.minimal_html)

            inject_into_insights_html(self.test_report, html_path)

            result = html_path.read_text()
            self.assertIn("<h1>Session Report</h1>", result)
            self.assertIn("<p>Content here</p>", result)

    def test_injection_includes_metrics(self):
        """Test that spend metrics are included."""
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = Path(tmpdir) / "test.html"
            html_path.write_text(self.minimal_html)

            inject_into_insights_html(self.test_report, html_path)

            result = html_path.read_text()
            self.assertIn("$42.50", result)  # total spend
            self.assertIn("$8.75", result)   # recoverable
            self.assertIn("12", result)       # cache savings
            self.assertIn("78", result)       # efficiency score

    def test_injection_includes_antipatterns(self):
        """Test that top anti-patterns are included."""
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = Path(tmpdir) / "test.html"
            html_path.write_text(self.minimal_html)

            inject_into_insights_html(self.test_report, html_path)

            result = html_path.read_text()
            # Should include human-readable names
            self.assertIn("Top Cost Anti-Patterns", result)
            # file_thrash display name or default
            self.assertTrue(
                "Files Being Re-read Repeatedly" in result or "file_thrash" in result
            )

    def test_injection_includes_session_table(self):
        """Test that session efficiency table is included."""
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = Path(tmpdir) / "test.html"
            html_path.write_text(self.minimal_html)

            inject_into_insights_html(self.test_report, html_path)

            result = html_path.read_text()
            self.assertIn("Session Efficiency", result)
            self.assertIn("<table", result)
            self.assertIn("session-001", result)

    def test_injection_before_body_tag(self):
        """Test that injection is inserted before </body> tag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = Path(tmpdir) / "test.html"
            html_path.write_text(self.minimal_html)

            inject_into_insights_html(self.test_report, html_path)

            result = html_path.read_text()
            # Find positions
            economics_pos = result.find("ai-dev-token-economics")
            body_close_pos = result.find("</body>")

            self.assertGreater(economics_pos, 0, "Economics section should exist")
            self.assertGreater(body_close_pos, economics_pos, "Economics should be before </body>")

    def test_file_not_found_error(self):
        """Test that FileNotFoundError is raised for missing file."""
        nonexistent_path = Path("/tmp/nonexistent_file_xyz.html")
        with self.assertRaises(FileNotFoundError):
            inject_into_insights_html(self.test_report, nonexistent_path)

    def test_no_body_tag_error(self):
        """Test that ValueError is raised when </body> tag is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = Path(tmpdir) / "test.html"
            html_path.write_text("<html><body>No closing tag</html>")

            with self.assertRaises(ValueError):
                inject_into_insights_html(self.test_report, html_path)

    def test_build_html_empty_lists(self):
        """Test HTML builder handles empty flags and sessions."""
        html = _build_insights_injection_html(
            composite_score=0.0,
            total_cost=0.0,
            recoverable_cost=0.0,
            recoverable_pct=0.0,
            cache_savings=0.0,
            top_flags=[],
            top_sessions=[],
            per_session_v2=[],
        )

        self.assertIn("ai-dev-token-economics", html)
        self.assertIn("$0.00", html)
        self.assertIn("Total Spend", html)
        # Table and anti-patterns sections should be skipped
        self.assertNotIn("<table", html)
        self.assertNotIn("Top Cost Anti-Patterns", html)

    def test_build_html_css_classes(self):
        """Test that proper CSS classes are used."""
        html = _build_insights_injection_html(
            composite_score=80.0,
            total_cost=100.0,
            recoverable_cost=20.0,
            recoverable_pct=20.0,
            cache_savings=5.0,
            top_flags=[("file_thrash", (10.0, 2))],
            top_sessions=[
                {
                    "session_id": "test-session",
                    "composite": 75.0,
                    "cost": 50.0,
                    "recoverable_cost_total_usd": 10.0,
                }
            ],
            per_session_v2=[
                {
                    "session_id": "test-session",
                    "flags": [{"flag_id": "file_thrash", "recoverable_cost_usd": 10.0}],
                }
            ],
        )

        # Verify Insights CSS classes are used
        self.assertIn('class="stats-row"', html)
        self.assertIn('class="stat"', html)
        self.assertIn('class="stat-value"', html)
        self.assertIn('class="stat-label"', html)
        self.assertIn('class="friction-categories"', html)
        self.assertIn('class="friction-category"', html)
        self.assertIn('class="friction-title"', html)
        self.assertIn('class="friction-desc"', html)

    def test_score_colors_in_table(self):
        """Test that score colors are applied correctly in session table."""
        html = _build_insights_injection_html(
            composite_score=80.0,
            total_cost=100.0,
            recoverable_cost=20.0,
            recoverable_pct=20.0,
            cache_savings=5.0,
            top_flags=[],
            top_sessions=[
                {"session_id": "green-session", "composite": 90.0, "cost": 30.0, "recoverable_cost_total_usd": 5.0},
                {"session_id": "yellow-session", "composite": 75.0, "cost": 30.0, "recoverable_cost_total_usd": 5.0},
                {"session_id": "red-session", "composite": 60.0, "cost": 40.0, "recoverable_cost_total_usd": 10.0},
            ],
            per_session_v2=[],
        )

        # Check color application
        self.assertIn('color: green', html)
        self.assertIn('color: orange', html)
        self.assertIn('color: red', html)

    def test_antipattern_display_names(self):
        """Test that antipattern display names are used in injection."""
        html = _build_insights_injection_html(
            composite_score=80.0,
            total_cost=100.0,
            recoverable_cost=20.0,
            recoverable_pct=20.0,
            cache_savings=5.0,
            top_flags=[
                ("convergence_gate1_miss", (15.0, 5)),
                ("file_thrash", (5.0, 2)),
            ],
            top_sessions=[],
            per_session_v2=[],
        )

        # Should contain human-readable names, not flag IDs
        self.assertIn("Slow to Get Started", html)  # convergence_gate1_miss display name
        self.assertIn("Files Being Re-read Repeatedly", html)  # file_thrash display name


if __name__ == "__main__":
    unittest.main()
