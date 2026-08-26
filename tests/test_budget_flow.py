import json
import tempfile
import unittest
import uuid
from pathlib import Path

import bound_codex_tokens as app


class BudgetFlowTest(unittest.TestCase):
    @staticmethod
    def token_record(last: int, cumulative: int) -> dict:
        return {"type": "event_msg", "payload": {"type": "token_count", "info": {
            "last_token_usage": {"total_tokens": last}, "total_token_usage": {"total_tokens": cumulative},
        }}}

    def test_ten_tokens_and_uuid_reach_the_bounded_bundle(self) -> None:
        """The UUID enters only through the watched session transcript."""
        marker = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "2026" / "08" / "25" / "rollout-test.jsonl"
            log.parent.mkdir(parents=True)
            records = [
                {"type": "session_meta", "payload": {"session_id": "root", "thread_source": "user"}},
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"text": marker}]}},
                self.token_record(10, 10),
            ]
            log.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")

            watch = app.SessionWatch(root, set(), deny_sol=False, require_none=False)
            watch.poll()
            self.assertEqual(watch.tokens, 10)

            bundle = app.write_bundle(root / "out", watch, "test cap", watch.tokens)
            selected = (bundle / "selected-transcript.md").read_text(encoding="utf-8")
            self.assertIn(marker, selected)

    def test_visible_budget_prompt_is_rendered(self) -> None:
        prompt = app.render_session_prompt(10, 30, 20, 2)
        self.assertIn("10 reported tokens", prompt)
        self.assertIn("30", prompt)
        self.assertIn("20", prompt)
        self.assertIn("2 automatic compacts", prompt)

    def test_subagent_lineage_counts_parent_and_child_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent_log = root / "2026" / "08" / "25" / "rollout-parent.jsonl"
            child_log = root / "2026" / "08" / "25" / "rollout-child.jsonl"
            parent_log.parent.mkdir(parents=True)
            parent_log.write_text("".join(json.dumps(record) + "\n" for record in [
                {"type": "session_meta", "payload": {"session_id": "parent", "thread_source": "user"}},
                self.token_record(7, 7),
            ]), encoding="utf-8")
            child_log.write_text("".join(json.dumps(record) + "\n" for record in [
                {"type": "session_meta", "payload": {
                    "session_id": "child", "parent_thread_id": "parent", "thread_source": "subagent",
                }},
                self.token_record(3, 3),
            ]), encoding="utf-8")

            watch = app.SessionWatch(root, set(), deny_sol=False, require_none=False)
            watch.poll()
            self.assertEqual(watch.tokens, 10)
            self.assertEqual(len(watch.related_paths()), 2)

            with child_log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(self.token_record(4, 7)) + "\n")
            watch.poll()
            self.assertEqual(watch.tokens, 14)


if __name__ == "__main__":
    unittest.main()
