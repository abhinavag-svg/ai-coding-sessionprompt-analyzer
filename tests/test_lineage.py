import unittest


from ai_dev.lineage import parent_graph_lineage, session_lineage_overview, time_window_lineage


class TestLineage(unittest.TestCase):
    def test_time_window_lineage_links_next_user(self) -> None:
        turns = [
            {"turn_index": 1, "uuid": "u1", "session_id": "s", "is_user_turn": True, "is_assistant_turn": False, "text": "Do X", "prompt_flags": []},
            {"turn_index": 2, "uuid": "a1", "session_id": "s", "is_user_turn": False, "is_assistant_turn": True, "tool_events": [{"kind": "tool_use", "tool_use_id": "t1", "name": "Edit", "file_path": "a.py", "command": ""}]},
            {"turn_index": 3, "uuid": "u2", "session_id": "s", "is_user_turn": True, "is_assistant_turn": False, "text": "Still failing", "correction_language": True, "prompt_flags": []},
        ]
        lines = time_window_lineage(turns, "u1", max_events=25)
        self.assertTrue(any("next user uuid `u2`" in l for l in lines))

    def test_parent_graph_lineage_traverses_parent(self) -> None:
        turns = [
            {"turn_index": 1, "uuid": "u1", "parent_uuid": "", "session_id": "s", "is_user_turn": True, "is_assistant_turn": False, "prompt_flags": []},
            {"turn_index": 2, "uuid": "a1", "parent_uuid": "u1", "session_id": "s", "is_user_turn": False, "is_assistant_turn": True, "tool_events": []},
        ]
        lines = parent_graph_lineage(turns, "a1", max_events=25, max_depth=6)
        self.assertTrue(any("parent[1]" in l and "uuid `u1`" in l for l in lines))

    def test_session_overview_counts(self) -> None:
        turns = [
            {"uuid": "u1", "session_id": "s", "is_user_turn": True, "is_assistant_turn": False, "text": "x", "tool_use_count": 0, "tool_result_count": 0, "prompt_flags": []},
            {"uuid": "a1", "session_id": "s", "is_user_turn": False, "is_assistant_turn": True, "tool_use_count": 1, "tool_result_count": 0, "tool_names": ["Edit"]},
        ]
        ov = session_lineage_overview(turns)
        self.assertEqual(len(ov), 1)
        self.assertEqual(ov[0]["assistant_turns"], 1)
        self.assertEqual(ov[0]["tool_use_count"], 1)


if __name__ == "__main__":
    unittest.main()

