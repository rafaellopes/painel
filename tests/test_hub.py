"""The hub (M9, docs/SPEC.md §13): lists every live instance from the §6.6
registry as a clickable card, re-reading the registry on every request (no
caching). Follows the same fake-HOME pattern as
tests.test_main.DiscoverRunningBoardsTest so real ~/.painel state is never
touched."""
import json
import os
import socket
import tempfile
import unittest

from painel import __main__ as cli
from painel import hub as hub_mod
from painel.server import save_board


class _FakeHomeMixin:
    def setUp(self):
        self._tmp_home = tempfile.TemporaryDirectory()
        self._orig_expanduser = os.path.expanduser
        home = self._tmp_home.name

        def fake_expanduser(path):
            return path.replace("~", home, 1) if path.startswith("~") else self._orig_expanduser(path)

        os.path.expanduser = fake_expanduser
        self.addCleanup(setattr, os.path, "expanduser", self._orig_expanduser)
        self.addCleanup(self._tmp_home.cleanup)


def _occupy_port():
    """Returns (socket, port) -- caller must keep the socket alive to keep
    the port occupied, and close it when done. A larger backlog than the
    single-connect-attempt tests elsewhere in this suite use, since these
    tests call _discover_running_boards() (which probes the port with
    connect_ex) more than once per socket -- backlog=1 gets exhausted after
    one probe and the port then looks spuriously free."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(16)
    return s, s.getsockname()[1]


class HubListingTest(_FakeHomeMixin, unittest.TestCase):
    def test_empty_registry_renders_empty_but_valid_page(self):
        html = hub_mod.render_hub(cli._discover_running_boards())
        self.assertIn("<html", html)
        self.assertIn("</html>", html)
        self.assertIn("Nenhum pAInel a correr", html)

    def test_lists_a_live_board_with_title_project_and_pending_badge(self):
        with tempfile.TemporaryDirectory() as d:
            board_path = os.path.join(d, "board.json")
            save_board(board_path, {
                "title": "O Meu Board",
                "meta": {"project": "meu-projeto", "agent_status": "working"},
                "blocks": [
                    {"id": "q1", "type": "question", "prompt": "?", "answer": None},
                ],
            })
            s, port = _occupy_port()
            try:
                cli._write_registry(os.getpid(), port, board_path, kind="board")
                instances = cli._discover_running_boards()
                html = hub_mod.render_hub(instances)
                self.assertIn("O Meu Board", html)
                self.assertIn("meu-projeto", html)
                self.assertIn(f"http://localhost:{port}/", html)
                self.assertIn("a trabalhar", html)  # agent_status=working chip
            finally:
                s.close()
                cli._remove_registry(port)

    def test_pending_badge_reflects_needs_user(self):
        with tempfile.TemporaryDirectory() as d:
            answered_path = os.path.join(d, "answered.json")
            save_board(answered_path, {
                "title": "Sem pendentes",
                "meta": {},
                "blocks": [{"id": "q1", "type": "question", "prompt": "?", "answer": "sim"}],
            })
            pending_path = os.path.join(d, "pending.json")
            save_board(pending_path, {
                "title": "Com pendentes",
                "meta": {},
                "blocks": [{"id": "q1", "type": "question", "prompt": "?", "answer": None}],
            })
            s1, p1 = _occupy_port()
            s2, p2 = _occupy_port()
            try:
                cli._write_registry(os.getpid(), p1, answered_path, kind="board")
                cli._write_registry(os.getpid(), p2, pending_path, kind="board")
                html = hub_mod.render_hub(cli._discover_running_boards())
                self.assertIn("À espera de ti", html)
                self.assertIn("Agente offline", html)  # answered board, no pending, status default
            finally:
                s1.close()
                s2.close()
                cli._remove_registry(p1)
                cli._remove_registry(p2)

    def test_reflects_registry_changes_without_caching(self):
        with tempfile.TemporaryDirectory() as d:
            board_path = os.path.join(d, "board.json")
            save_board(board_path, {"title": "Aparece e Desaparece", "meta": {}, "blocks": []})
            s, port = _occupy_port()
            try:
                html_before = hub_mod.render_hub(cli._discover_running_boards())
                self.assertNotIn("Aparece e Desaparece", html_before)

                cli._write_registry(os.getpid(), port, board_path, kind="board")
                html_during = hub_mod.render_hub(cli._discover_running_boards())
                self.assertIn("Aparece e Desaparece", html_during)

                cli._remove_registry(port)
                s.close()
                html_after = hub_mod.render_hub(cli._discover_running_boards())
                self.assertNotIn("Aparece e Desaparece", html_after)
            finally:
                try:
                    s.close()
                except OSError:
                    pass
                cli._remove_registry(port)

    def test_hub_entries_excluded_from_board_listing(self):
        """The hub's own listing must not list itself -- _discover_running_boards
        is called with kind='board' by the hub's HTTP handler."""
        s, port = _occupy_port()
        try:
            cli._write_registry(os.getpid(), port, board=None, kind="hub")
            boards_only = cli._discover_running_boards(kind="board")
            self.assertEqual(boards_only, [])
            everything = cli._discover_running_boards()
            self.assertEqual(len(everything), 1)
            self.assertEqual(everything[0]["kind"], "hub")
        finally:
            s.close()
            cli._remove_registry(port)


class RegistryKindBackwardCompatTest(_FakeHomeMixin, unittest.TestCase):
    def test_old_format_entry_without_kind_defaults_to_board(self):
        s, port = _occupy_port()
        try:
            path = cli._registry_path(port)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"pid": os.getpid(), "port": port, "board": "/tmp/x/.painel-board.json"}, fh)
            found = cli._discover_running_boards()
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["kind"], "board")
        finally:
            s.close()
            cli._remove_registry(port)

    def test_write_registry_defaults_kind_to_board(self):
        s, port = _occupy_port()
        try:
            cli._write_registry(os.getpid(), port, "/tmp/x/.painel-board.json")
            found = cli._discover_running_boards()
            self.assertEqual(found[0]["kind"], "board")
        finally:
            s.close()
            cli._remove_registry(port)


class RestartAllHubVsBoardTest(_FakeHomeMixin, unittest.TestCase):
    def test_restart_all_distinguishes_hub_and_board_via_spawn_calls(self):
        """Exercise the dispatch logic in cmd_restart_all directly (without
        actually spawning real subprocesses) by monkeypatching _spawn/_spawn_hub
        and feeding a synthetic instance list through the same code path."""
        calls = []

        def fake_spawn(board, port):
            calls.append(("board", board, port))
            return 12345

        def fake_spawn_hub(port):
            calls.append(("hub", port))
            return 54321

        orig_discover = cli._discover_running_boards
        orig_spawn = cli._spawn
        orig_spawn_hub = cli._spawn_hub
        orig_pid_alive = cli._pid_alive
        orig_wait = cli._wait_until_listening
        orig_wait_free = cli._wait_until_listening_free

        cli._spawn = fake_spawn
        cli._spawn_hub = fake_spawn_hub
        cli._pid_alive = lambda pid: False  # pretend every old pid is already dead -- skip the kill/wait loop
        cli._wait_until_listening = lambda port, tries=50: None
        cli._wait_until_listening_free = lambda port, tries=50: None
        cli._discover_running_boards = lambda: [
            {"pid": 1, "board": "/tmp/b.json", "port": 9001, "kind": "board"},
            {"pid": 2, "board": None, "port": 9002, "kind": "hub"},
        ]
        try:
            cli.cmd_restart_all()
        finally:
            cli._discover_running_boards = orig_discover
            cli._spawn = orig_spawn
            cli._spawn_hub = orig_spawn_hub
            cli._pid_alive = orig_pid_alive
            cli._wait_until_listening = orig_wait
            cli._wait_until_listening_free = orig_wait_free

        self.assertIn(("board", "/tmp/b.json", 9001), calls)
        self.assertIn(("hub", 9002), calls)


if __name__ == "__main__":
    unittest.main()
