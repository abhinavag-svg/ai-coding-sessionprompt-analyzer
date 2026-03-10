# Insights HTML Injection Usage Guide

## Overview

The `--insights-html` flag allows you to inject ai-dev's token economics analysis directly into your Claude Code Insights HTML report. This embeds cost metrics, anti-patterns analysis, and session efficiency data using Insights' native CSS styling.

## Basic Usage

```bash
# Analyze sessions and inject into Insights HTML
python -m ai_dev.cli analyze ~/path/to/sessions --insights-html ~/path/to/insights.html
```

## Complete Example

```bash
# If you have Claude Code Insights reports at ~/.claude/usage-data/
python -m ai_dev.cli analyze ~/.claude/projects/my-project \
  --insights-html ~/.claude/usage-data/report.html \
  --export report.md
```

This will:
1. Analyze all JSONL files under `~/.claude/projects/my-project`
2. Inject token economics section into the Insights HTML
3. Also export a markdown report for reference

## What Gets Injected

### 1. Spend Metrics Panel
Shows five key metrics:
- **Total Spend**: All API costs for the analyzed sessions
- **Recoverable Waste**: Estimated cost of avoidable inefficiencies
- **Waste %**: Percentage of total spend that could have been prevented
- **Saved by Caching**: Prompt caching savings (already applied)
- **Efficiency Score**: Overall efficiency rating (0-100)

Example output:
```
Total Spend: $42.50
Recoverable Waste: $8.75
Waste %: 20%
Saved by Caching: $12.30
Efficiency Score: 78
```

### 2. Top Cost Anti-Patterns
Lists the 5 most expensive issues found, ranked by recoverable cost:

Example:
```
Slow to Get Started
  5 occurrences • $3.50 recoverable

Files Being Re-read Repeatedly
  2 occurrences • $2.75 recoverable

Work Interrupted by Corrections
  1 occurrences • $2.50 recoverable
```

Each anti-pattern shows:
- **Display name** (human-readable issue description)
- **Occurrences**: How many times this pattern was detected
- **Recoverable cost**: How much you could have saved by avoiding this issue

### 3. Session Efficiency Table
Compact table showing top 10 sessions by cost, with:

| Session ID | Score | Top Issue | Cost | Recoverable |
|---|---|---|---|---|
| session-abc1 | 85 | File Thrash | $15.00 | $2.50 |
| session-xyz2 | 72 | Gate1 Miss | $10.00 | $3.25 |
| ... | ... | ... | ... | ... |

- **Score**: Efficiency rating (color-coded: green ≥85, orange ≥70, red <70)
- **Top Issue**: Highest-impact problem in that session
- **Cost**: Total API spend for the session
- **Recoverable**: How much of that session's cost was avoidable

## Integration with Insights Workflow

The injected section appears at the bottom of your Insights HTML report, before the `</body>` tag. It uses Insights' native CSS classes for consistent styling:

- `.stats-row` and `.stat` for the spend metrics panel
- `.friction-categories` and `.friction-category` for anti-patterns list
- Native `<table>` styling for the efficiency table

Open the modified HTML file in your browser to see the formatted report:

```bash
open ~/.claude/usage-data/report.html
```

## Advanced Options

Combine with other ai-dev flags:

```bash
# Use custom pricing file
python -m ai_dev.cli analyze ~/projects \
  --insights-html ~/report.html \
  --pricing-file ~/pricing-conservative.json

# Get recommendations too
python -m ai_dev.cli analyze ~/projects \
  --insights-html ~/report.html \
  --export ~/report.md \
  --llm-recommendations

# Use only billable events
python -m ai_dev.cli analyze ~/projects \
  --insights-html ~/report.html \
  --billable-only

# Disable deduplication
python -m ai_dev.cli analyze ~/projects \
  --insights-html ~/report.html \
  --no-dedupe
```

## Verification

Check that injection was successful:

```bash
# Verify the section exists
grep "ai-dev-token-economics" ~/path/to/report.html

# Count how many metrics were injected
grep -c "stat-value" ~/path/to/report.html  # Should be 5 or more
```

## Troubleshooting

### FileNotFoundError: Insights HTML file not found
**Solution**: Make sure the path to your Insights HTML file is correct and the file exists.

```bash
# Check if file exists
ls -la ~/.claude/usage-data/report.html
```

### ValueError: Could not find </body> tag
**Solution**: The HTML file doesn't have a closing `</body>` tag. Verify you're using a valid HTML file from Claude Code Insights.

### No visible changes in browser
**Solution**:
1. Hard refresh the browser (Cmd+Shift+R on Mac, Ctrl+Shift+R on Windows/Linux)
2. Check browser developer tools console for errors
3. Verify the file was actually modified: `tail ~/path/to/report.html`

## Performance Notes

- Injection is fast (sub-second) for typical reports
- HTML file is modified in place (creates backup if needed)
- No external dependencies required beyond ai-dev's existing stack

## Data Privacy

The injected data includes:
- API cost metrics (derived from your session logs)
- Session IDs and efficiency scores
- Issue patterns (no actual prompt text included)

All data comes from your local session files. Nothing is sent externally.

## Real-World Example

After optimizing your coding workflow:

**Before:**
- Total Spend: $127.50
- Recoverable Waste: $45.30 (35%)
- Efficiency Score: 62

**After (after implementing recommendations):**
- Total Spend: $85.00
- Recoverable Waste: $12.00 (14%)
- Efficiency Score: 85

You can track this progress by repeatedly injecting into Insights reports over time.

## Scripting

Use in automated workflows:

```bash
#!/bin/bash
# Analyze all projects and inject into Insights

PROJECTS_DIR="$HOME/.claude/projects"
INSIGHTS_DIR="$HOME/.claude/usage-data"

for project in "$PROJECTS_DIR"/*; do
    if [ -d "$project" ]; then
        project_name=$(basename "$project")
        insights_file="$INSIGHTS_DIR/${project_name}-report.html"

        if [ -f "$insights_file" ]; then
            echo "Processing: $project_name"
            python -m ai_dev.cli analyze "$project" \
              --insights-html "$insights_file"
        fi
    fi
done
```

## FAQ

**Q: Will this overwrite my original Insights report?**
A: Yes, the HTML file is modified in place. If you want to preserve the original, make a copy first:
```bash
cp ~/.claude/usage-data/report.html ~/.claude/usage-data/report-backup.html
python -m ai_dev.cli analyze ~/projects --insights-html ~/.claude/usage-data/report.html
```

**Q: Can I inject into multiple HTML files at once?**
A: No, you need to run the command separately for each file. You could script this with a bash loop.

**Q: Does injection work with all HTML files?**
A: Only with valid HTML files that contain a `</body>` tag. Claude Code Insights reports should work fine.

**Q: What if the report has no sessions or data?**
A: The injection will still work. It will show zero metrics and empty anti-pattern/session lists.

**Q: Can I customize what gets injected?**
A: The current version includes all available metrics. Future versions may support customization via config files.
