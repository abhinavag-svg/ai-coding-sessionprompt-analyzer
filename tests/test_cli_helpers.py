from pathlib import Path
from types import SimpleNamespace

from ai_dev.cli import _encode_claude_project_path, _event_matches_project_root, _resolve_pricing_inputs
from ai_dev.models import PricingProfile, SessionSource


def test_event_matches_codex_project_root_for_nested_cwd() -> None:
    event = SimpleNamespace(
        payload={"_project_cwd": "/tmp/work/demo/subdir"},
        source_file="/tmp/ignored.jsonl",
    )
    assert _event_matches_project_root(event, SessionSource.CODEX, Path("/tmp/work/demo"))
    assert not _event_matches_project_root(event, SessionSource.CODEX, Path("/tmp/work/other"))


def test_event_matches_claude_project_root_and_worktree() -> None:
    root = Path("/Users/alex/projects/git/demo-app")
    encoded = _encode_claude_project_path(root)
    direct = SimpleNamespace(payload={}, source_file=f"/tmp/{encoded}/session.jsonl")
    worktree = SimpleNamespace(payload={}, source_file=f"/tmp/{encoded}--claude-worktrees-fix-one/session.jsonl")
    other = SimpleNamespace(payload={}, source_file="/tmp/-Users-alex-projects-git-other-app/session.jsonl")
    assert _event_matches_project_root(direct, SessionSource.CLAUDE, root)
    assert _event_matches_project_root(worktree, SessionSource.CLAUDE, root)
    assert not _event_matches_project_root(other, SessionSource.CLAUDE, root)


def test_resolve_pricing_inputs_uses_bundled_profile() -> None:
    split_rates, blended_rates, label = _resolve_pricing_inputs(None, PricingProfile.AGGRESSIVE)
    assert label == "bundled:aggressive"
    assert split_rates is not None
    assert blended_rates is not None
    assert "gpt-4.1" in split_rates
    assert blended_rates["o3"] > 0
