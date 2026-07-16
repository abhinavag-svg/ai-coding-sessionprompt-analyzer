import tempfile
import unittest
from pathlib import Path

from ai_dev.reporter import inject_into_insights_html


class InsightsInjectionSmokeTest(unittest.TestCase):
    def test_runtime_augmentation_block_is_injected(self) -> None:
        source = "<!doctype html><html><body><h1>Insights Report</h1></body></html>"
        report = {
            "total_cost_derived": 42.50,
            "session_features": {"estimated_cache_savings": 12.30},
            "v2": {
                "project_rollup": {
                    "composite": 78.5,
                    "session_count": 1,
                    "recoverable_cost_total_usd": 8.75,
                },
                "per_session_v2": [],
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = Path(tmpdir) / "test.html"
            html_path.write_text(source, encoding="utf-8")
            inject_into_insights_html(report, html_path)
            result = html_path.read_text(encoding="utf-8")

        self.assertIn("<!-- ai-dev-runtime:start -->", result)
        self.assertIn('id="ai-dev-data"', result)
        self.assertIn('id="ai-dev-runtime"', result)
        self.assertIn("Token Economics", result)
        self.assertIn("</body>", result)
        self.assertIn("<h1>Insights Report</h1>", result)


if __name__ == "__main__":
    unittest.main()
