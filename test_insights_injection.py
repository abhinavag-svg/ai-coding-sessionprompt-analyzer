#!/usr/bin/env python3
"""Quick test for insights HTML injection feature."""

from pathlib import Path
import tempfile
from ai_dev.reporter import inject_into_insights_html

# Create a minimal test HTML file
test_html = """<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
<h1>Insights Report</h1>
<p>Some content here.</p>
</body>
</html>"""

# Create a test report
test_report = {
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
                    "session_id": "sess-001",
                    "composite": 85.0,
                    "cost": 15.00,
                    "recoverable_cost_total_usd": 2.50,
                },
                {
                    "session_id": "sess-002",
                    "composite": 72.0,
                    "cost": 10.00,
                    "recoverable_cost_total_usd": 3.25,
                },
            ],
        },
        "per_session_v2": [
            {
                "session_id": "sess-001",
                "flags": [
                    {
                        "flag_id": "file_thrash",
                        "recoverable_cost_usd": 2.50,
                        "occurrences": 3,
                    }
                ],
            },
            {
                "session_id": "sess-002",
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

# Test in a temporary directory
with tempfile.TemporaryDirectory() as tmpdir:
    html_path = Path(tmpdir) / "test.html"
    html_path.write_text(test_html)

    print(f"Created test HTML at {html_path}")
    print(f"Original HTML size: {len(test_html)} bytes")

    # Inject
    inject_into_insights_html(test_report, html_path)

    result = html_path.read_text()
    print(f"Modified HTML size: {len(result)} bytes")

    # Verify injection
    checks = [
        ("ai-dev-token-economics" in result, "Has ai-dev-token-economics section"),
        ("Token Economics (via ai-dev)" in result, "Has title"),
        ("$42.50" in result, "Has total spend"),
        ("$8.75" in result, "Has recoverable cost"),
        ("78" in result or "79" in result, "Has efficiency score"),
        ("file_thrash" in result or "Files Being Re-read Repeatedly" in result, "Has anti-pattern"),
        ("sess-001" in result, "Has session ID"),
        ("</body>" in result, "Has closing body tag"),
    ]

    print("\n=== Injection Verification ===")
    all_passed = True
    for check, description in checks:
        status = "✓" if check else "✗"
        print(f"{status} {description}")
        if not check:
            all_passed = False

    if all_passed:
        print("\n✓ All checks passed!")

        # Print a snippet of the injected content
        print("\n=== Sample of Injected Content ===")
        start = result.find("<!-- ai-dev Token Economics Section -->")
        if start >= 0:
            end = result.find("</section>", start) + len("</section>")
            print(result[start:end][:500] + "...")
    else:
        print("\n✗ Some checks failed")
        print("\n=== Full Result ===")
        print(result)
