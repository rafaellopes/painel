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


class DiscoverRunningBoardsTest(unittest.TestCase):
    """restart-all's process-table parsing (Rafael's request: whenever a new
    painel version ships, restart every running instance so it's picked up
    everywhere, not just the project being worked on)."""

    def test_parses_absolute_board_path(self):
        line = "12345 /usr/bin/python3 -m painel serve /Users/x/proj/.painel-board.json --port 8766"
        found = cli._parse_ps_serve_lines(line)
        self.assertEqual(found, [
            {"pid": 12345, "board": "/Users/x/proj/.painel-board.json", "port": 8766}
        ])

    def test_resolves_relative_board_path_via_cwd_resolver(self):
        line = "999 python3 -m painel serve .painel-board.json --port 8770"
        found = cli._parse_ps_serve_lines(line, cwd_resolver=lambda pid: "/Users/x/other-proj")
        self.assertEqual(found, [
            {"pid": 999, "board": "/Users/x/other-proj/.painel-board.json", "port": 8770}
        ])

    def test_skips_relative_path_when_cwd_unresolvable(self):
        line = "999 python3 -m painel serve .painel-board.json --port 8770"
        found = cli._parse_ps_serve_lines(line, cwd_resolver=lambda pid: None)
        self.assertEqual(found, [])

    def test_ignores_unrelated_processes(self):
        ps_output = "\n".join([
            "1 /sbin/launchd",
            "42 python3 -m http.server 8000",
            "77 python3 -m painel serve board.json --port 8765",
        ])
        found = cli._parse_ps_serve_lines(ps_output, cwd_resolver=lambda pid: "/tmp/proj")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["pid"], 77)

    def test_multiple_running_instances_all_found(self):
        ps_output = "\n".join([
            "10 python3 -m painel serve /a/.painel-board.json --port 8765",
            "20 python3 -m painel serve /b/.painel-board.json --port 8766",
            "30 python3 -m painel serve /c/.painel-board.json --port 8767",
        ])
        found = cli._parse_ps_serve_lines(ps_output)
        self.assertEqual({f["port"] for f in found}, {8765, 8766, 8767})
        self.assertEqual({f["pid"] for f in found}, {10, 20, 30})

    def test_missing_port_flag_is_skipped(self):
        line = "5 python3 -m painel serve /a/.painel-board.json"
        found = cli._parse_ps_serve_lines(line)
        self.assertEqual(found, [])

    def test_no_running_instances_returns_empty(self):
        self.assertEqual(cli._parse_ps_serve_lines(""), [])

    def test_dedupes_same_port_keeping_highest_pid(self):
        # Only one process can really own a port -- two process-table entries
        # for the same port (stale/orphaned duplicate, e.g. from a crashed
        # restart) must collapse to one, or restart-all would race to rebind
        # the port twice and silently orphan a process outside any pidfile.
        ps_output = "\n".join([
            "100 python3 -m painel serve /a/.painel-board.json --port 8791",
            "999 python3 -m painel serve /a/.painel-board.json --port 8791",
        ])
        found = cli._parse_ps_serve_lines(ps_output)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["pid"], 999)


if __name__ == "__main__":
    unittest.main()
