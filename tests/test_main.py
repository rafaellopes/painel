"""CLI-level tests: M5 (SPEC.md §10.3) -- painel open/serve set
meta.agent_status="idle" on first run when the key is absent, best-effort."""
import json
import os
import socket
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
    """restart-all's discovery (Rafael's request: whenever a new painel
    version ships, restart every running instance so it's picked up
    everywhere, not just the project being worked on).

    Discovery reads a central per-port registry (~/.painel/instances/) that
    _spawn() writes -- NOT `ps` output. An earlier version parsed `ps`
    command lines and broke on any board path containing a space (e.g.
    Google Drive's "Meu Drive", which is where most of Rafael's real
    projects live) -- printed argv has no reliable boundary between "a
    space inside one argument" and "a space between two arguments" once the
    kernel's original argv array is gone. These tests use a real (but truly
    idle, never-actually-alive) pid -- os.getpid() is alive but its
    "port" is deliberately left occupied/free as needed per test -- to
    exercise the actual registry-reading code path, not a mock."""

    def setUp(self):
        self._tmp_home = tempfile.TemporaryDirectory()
        self._orig_expanduser = os.path.expanduser
        home = self._tmp_home.name

        def fake_expanduser(path):
            return path.replace("~", home, 1) if path.startswith("~") else self._orig_expanduser(path)

        os.path.expanduser = fake_expanduser
        self.addCleanup(setattr, os.path, "expanduser", self._orig_expanduser)
        self.addCleanup(self._tmp_home.cleanup)

    def test_no_instances_returns_empty(self):
        self.assertEqual(cli._discover_running_boards(), [])

    def test_finds_a_genuinely_alive_registered_instance(self):
        # Use our own pid (definitely alive) and a port we bind ourselves
        # (definitely occupied) so _discover_running_boards' liveness check
        # (pid alive AND port not free) is exercised for real, not mocked.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            port = s.getsockname()[1]
            board_path = "/Users/x/Meu Drive/proj/.painel-board.json"  # deliberately has a space
            cli._write_registry(os.getpid(), port, board_path)
            found = cli._discover_running_boards()
            self.assertEqual(found, [{"pid": os.getpid(), "board": board_path, "port": port}])

    def test_stale_entry_self_heals_and_is_removed(self):
        # A registry entry whose port is free again (process gone) must not
        # be reported, and its file should be cleaned up automatically.
        port = cli._find_free_port(start=39001)
        cli._write_registry(os.getpid(), port, "/tmp/gone/.painel-board.json")
        self.assertEqual(cli._discover_running_boards(), [])
        self.assertFalse(os.path.exists(cli._registry_path(port)))

    def test_dead_pid_with_occupied_port_is_not_reported(self):
        # Extremely unlikely real pid, port genuinely occupied by us --
        # must not be reported since the *pid* is the one that's dead.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            port = s.getsockname()[1]
            cli._write_registry(999999999, port, "/tmp/x/.painel-board.json")
            self.assertEqual(cli._discover_running_boards(), [])

    def test_remove_registry_is_idempotent(self):
        cli._remove_registry(39999)  # never existed -- must not raise
        port = cli._find_free_port(start=39002)
        cli._write_registry(os.getpid(), port, "/tmp/x/.painel-board.json")
        cli._remove_registry(port)
        cli._remove_registry(port)  # second call, file already gone -- must not raise
        self.assertFalse(os.path.exists(cli._registry_path(port)))


if __name__ == "__main__":
    unittest.main()
