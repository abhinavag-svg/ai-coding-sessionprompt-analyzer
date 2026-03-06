import json
import tempfile
import unittest
from pathlib import Path


from ai_dev.dedupe import dedupe_events
from ai_dev.parser import iter_normalized_events


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


class TestParserAndDedupe(unittest.TestCase):
    def test_parser_extracts_ids_and_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "session.jsonl"
            _write_jsonl(
                p,
                [
                    {
                        "type": "assistant",
                        "sessionId": "sess-1",
                        "uuid": "evt-1",
                        "parentUuid": "",
                        "timestamp": "2026-02-19T23:48:15.581Z",
                        "requestId": "req-1",
                        "message": {
                            "id": "msg-1",
                            "role": "assistant",
                            "model": "claude-sonnet-4-6",
                            "usage": {
                                "input_tokens": 2,
                                "output_tokens": 3,
                                "cache_read_input_tokens": 100,
                                "cache_creation_input_tokens": 10,
                            },
                            "content": [{"type": "text", "text": "ok"}],
                        },
                    }
                ],
            )

            events = list(iter_normalized_events(p))
            self.assertEqual(len(events), 1)
            e = events[0]
            self.assertEqual(e.session_id, "sess-1")
            self.assertEqual(e.uuid, "evt-1")
            self.assertEqual(e.parent_uuid, "")
            self.assertEqual(e.message_api_id, "msg-1")
            self.assertEqual(e.usage.incremental_tokens, 5)
            self.assertEqual(e.usage.cache_read_tokens, 100)
            self.assertEqual(e.usage.cache_write_tokens, 10)

    def test_subagent_agent_id_inferred_from_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sub = root / "subagents"
            sub.mkdir()
            p = sub / "agent-abc123.jsonl"
            _write_jsonl(
                p,
                [
                    {
                        "type": "assistant",
                        "sessionId": "sess-1",
                        "uuid": "evt-2",
                        "timestamp": "2026-02-19T23:48:16.000Z",
                        "message": {
                            "id": "msg-2",
                            "role": "assistant",
                            "model": "claude-sonnet-4-6",
                            "usage": {"cache_read_input_tokens": 1},
                            "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "x"}}],
                        },
                    }
                ],
            )
            e = list(iter_normalized_events(p))[0]
            self.assertEqual(e.agent_id, "agent-abc123")

    def test_dedupe_prefers_uuid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "session.jsonl"
            # Two identical events with same uuid should dedupe to 1.
            row = {
                "type": "assistant",
                "sessionId": "sess-1",
                "uuid": "evt-dup",
                "timestamp": "2026-02-19T23:48:15.581Z",
                "message": {
                    "id": "msg-dup",
                    "role": "assistant",
                    "model": "claude-sonnet-4-6",
                    "usage": {"cache_read_input_tokens": 1},
                    "content": [{"type": "text", "text": "ok"}],
                },
            }
            _write_jsonl(p, [row, row])
            events = list(iter_normalized_events(p))
            deduped, stats = dedupe_events(events)
            self.assertEqual(len(events), 2)
            self.assertEqual(len(deduped), 1)
            self.assertEqual(stats["duplicates_removed"], 1)

    def test_dedupe_keeps_richest_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "session.jsonl"
            # Same requestId+message.id => same dedupe key. The second copy has real text.
            thin = {
                "type": "user",
                "sessionId": "sess-1",
                "uuid": "evt-thin",
                "timestamp": "2026-02-19T23:48:15.000Z",
                "requestId": "req-1",
                "message": {"id": "msg-1", "role": "user", "model": "n/a", "usage": {"input_tokens": 1}, "content": []},
            }
            rich = {
                "type": "user",
                "sessionId": "sess-1",
                "uuid": "evt-rich",
                "timestamp": "2026-02-19T23:48:16.000Z",
                "requestId": "req-1",
                "message": {
                    "id": "msg-1",
                    "role": "user",
                    "model": "n/a",
                    "usage": {"input_tokens": 1},
                    "content": [{"type": "text", "text": "Please fix the bug in app/routes/app.tsx and add a unit test."}],
                },
            }
            _write_jsonl(p, [thin, rich])

            events = list(iter_normalized_events(p))
            deduped, stats = dedupe_events(events)
            self.assertEqual(len(deduped), 1)
            kept = deduped[0]
            # The kept payload should include the text content.
            msg = kept.payload.get("message")
            self.assertTrue(isinstance(msg, dict))
            content = msg.get("content")
            self.assertTrue(isinstance(content, list))
            self.assertTrue(any(isinstance(i, dict) and "Please fix the bug" in str(i.get("text", "")) for i in content))
            self.assertGreaterEqual(int(stats.get("duplicates_replaced", 0)), 1)


if __name__ == "__main__":
    unittest.main()
