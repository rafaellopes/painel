"""CLI-level tests: M5 (SPEC.md §10.3) -- painel open/serve set
meta.agent_status="idle" on first run when the key is absent, best-effort."""
import json
import os
import tempfile
import unittest

from painel import __main__ as cli
from painel.server import load_board, save_board


class DefaultAgentStatusTest(unittest.TestCase):
    def test_sets_idle_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            save_board(path, {"title": "T", "meta": {}, "blocks": []})
            cli._default_agent_status_if_absent(path)
            board = load_board(path)
            self.assertEqual(board["meta"]["agent_status"], "idle")

    def test_does_not_overwrite_existing_value(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            save_board(path, {"title": "T", "meta": {"agent_status": "working"}, "blocks": []})
            cli._default_agent_status_if_absent(path)
            board = load_board(path)
            self.assertEqual(board["meta"]["agent_status"], "working")

    def test_missing_meta_key_entirely(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            save_board(path, {"title": "T", "blocks": []})
            cli._default_agent_status_if_absent(path)
            board = load_board(path)
            self.assertEqual(board["meta"]["agent_status"], "idle")

    def test_best_effort_missing_board_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "does-not-exist.json")
            # load_board creates the file on demand, so this should succeed
            # and set idle -- not crash. Guards the "best-effort" contract.
            cli._default_agent_status_if_absent(path)
            self.assertTrue(os.path.exists(path))
            board = load_board(path)
            self.assertEqual(board["meta"]["agent_status"], "idle")

    def test_best_effort_malformed_json_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{not valid json")
            # Should not raise -- best-effort per SPEC.md §10.3.
            cli._default_agent_status_if_absent(path)

    def test_demo_board_has_explicit_agent_status(self):
        board = cli._demo_board()
        self.assertIn("agent_status", board["meta"])


if __name__ == "__main__":
    unittest.main()
