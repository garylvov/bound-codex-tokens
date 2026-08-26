import json
import tempfile
import unittest
import uuid
from pathlib import Path

import bound_codex_tokens as app


class BudgetFlowTest(unittest.TestCase):
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
                {"type": "event_msg", "payload": {"type": "token_count", "info": {
                    "last_token_usage": {"total_tokens": 10}, "total_token_usage": {"total_tokens": 10},
                }}},
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


if __name__ == "__main__":
    unittest.main()
