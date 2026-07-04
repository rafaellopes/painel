"""Server-level tests: board load/save, event dispatch, HTTP endpoints,
protocol field, and the escaping regression test (§8 of SPEC.md)."""
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from painel import server as srv
from painel.__main__ import _default_agent_status_if_absent

XSS = '"<script>alert(1)</script>'


class BoardIOTest(unittest.TestCase):
    def test_load_board_creates_file_with_protocol(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            board = srv.load_board(path)
            self.assertEqual(board["protocol"], 1)
            with open(path, encoding="utf-8") as fh:
                saved = json.load(fh)
            self.assertEqual(saved["protocol"], 1)

    def test_load_board_defaults_protocol_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"title": "x", "blocks": []}, fh)
            board = srv.load_board(path)
            self.assertEqual(board["protocol"], 1)

    def test_load_board_preserves_explicit_protocol(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"protocol": 1, "title": "x", "blocks": []}, fh)
            board = srv.load_board(path)
            self.assertEqual(board["protocol"], 1)

    def test_save_board_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            board = {"title": "T", "meta": {}, "blocks": [{"id": "a", "type": "heading", "text": "x"}]}
            srv.save_board(path, board)
            loaded = srv.load_board(path)
            self.assertEqual(loaded["title"], "T")
            self.assertEqual(loaded["blocks"][0]["id"], "a")
            self.assertEqual(loaded["protocol"], 1)


class UnknownBlockRenderTest(unittest.TestCase):
    def test_unknown_type_renders_fallback(self):
        board = {"blocks": [{"id": "x", "type": "totally_unknown"}]}
        html = srv.render(board)
        self.assertIn("bloco desconhecido", html)
        self.assertIn("totally_unknown", html)


class EventDispatchTest(unittest.TestCase):
    def _handler_apply(self, board_path, data):
        srv._Handler.board_path = board_path
        h = srv._Handler.__new__(srv._Handler)
        return h._apply(data)

    def test_unknown_event_no_mutation_no_crash(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            srv.save_board(path, {"blocks": [{"id": "q1", "type": "question", "prompt": "?", "answer": None}]})
            silent = self._handler_apply(path, {"event": "nonsense_event", "block": "q1"})
            board = srv.load_board(path)
            self.assertIsNone(board["blocks"][0]["answer"])
            self.assertFalse(silent)

    def test_event_to_missing_block_no_crash(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            srv.save_board(path, {"blocks": []})
            # Should not raise.
            silent = self._handler_apply(path, {"event": "answer", "block": "missing", "value": "x"})
            self.assertFalse(silent)

    def test_plan_seen_is_silent(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            srv.save_board(path, {"blocks": [{"id": "pl", "type": "plan", "items": [
                {"id": "p1", "text": "x", "thread": [{"from": "agent", "text": "hi"}], "seen": 0},
            ]}]})
            silent = self._handler_apply(path, {"event": "plan_seen", "block": "pl", "item": "p1"})
            self.assertTrue(silent)
            board = srv.load_board(path)
            self.assertEqual(board["blocks"][0]["items"][0]["seen"], 1)

    def test_answer_event_is_not_silent(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            srv.save_board(path, {"blocks": [{"id": "q1", "type": "question", "prompt": "?", "answer": None}]})
            silent = self._handler_apply(path, {"event": "answer", "block": "q1", "value": "42"})
            self.assertFalse(silent)
            board = srv.load_board(path)
            self.assertEqual(board["blocks"][0]["answer"], "42")


class WhoseTurnSignalTest(unittest.TestCase):
    """M5 (SPEC.md §10): meta.agent_status drives <title>/favicon/chip."""

    def _board(self, **meta_overrides):
        return {
            "title": "Board",
            "meta": {**meta_overrides},
            "blocks": [{"id": "cl", "type": "checklist", "title": "T",
                        "items": [{"id": "c1", "text": "x", "checked": False}]}],
        }

    def test_missing_agent_status_defaults_to_working(self):
        self.assertEqual(srv._agent_status({"meta": {}}), "working")
        self.assertEqual(srv._agent_status({}), "working")

    def test_explicit_agent_status_preserved(self):
        self.assertEqual(srv._agent_status({"meta": {"agent_status": "idle"}}), "idle")
        self.assertEqual(srv._agent_status({"meta": {"agent_status": "waiting"}}), "waiting")

    def test_title_pending_beats_status(self):
        html = srv.render(self._board(agent_status="idle"))
        self.assertIn("<title>🔴 1 à tua espera — Board</title>", html)

    def test_title_working_no_pending(self):
        board = self._board(agent_status="working")
        board["blocks"][0]["items"][0]["checked"] = True
        html = srv.render(board)
        self.assertIn("<title>🟡 Board</title>", html)

    def test_title_idle_no_pending(self):
        board = self._board(agent_status="idle")
        board["blocks"][0]["items"][0]["checked"] = True
        html = srv.render(board)
        self.assertIn("<title>⚪ Board</title>", html)

    def test_title_waiting_no_pending_treated_as_idle(self):
        board = self._board(agent_status="waiting")
        board["blocks"][0]["items"][0]["checked"] = True
        html = srv.render(board)
        self.assertIn("<title>⚪ Board</title>", html)

    def test_title_missing_status_defaults_working_backward_compat(self):
        # A board saved before M5 has no meta.agent_status at all.
        board = {"title": "Board", "blocks": []}
        html = srv.render(board)
        self.assertIn("<title>🟡 Board</title>", html)

    def test_chip_pending(self):
        html = srv.render(self._board(agent_status="working"))
        self.assertIn('🔴 À espera de ti (1)', html)

    def test_chip_working(self):
        board = self._board(agent_status="working")
        board["blocks"][0]["items"][0]["checked"] = True
        html = srv.render(board)
        self.assertIn("🟡 O agente está a trabalhar…", html)

    def test_chip_idle_no_resolved_blocks(self):
        board = self._board(agent_status="idle")
        board["blocks"][0]["items"][0]["checked"] = True
        html = srv.render(board)
        self.assertIn("⚪ Agente offline", html)

    def test_chip_idle_with_resolved_block_shows_done(self):
        board = {
            "title": "Board",
            "meta": {"agent_status": "idle"},
            "blocks": [{"id": "q1", "type": "question", "prompt": "?", "answer": "42"}],
        }
        html = srv.render(board)
        self.assertIn("✅ Tudo feito", html)

    def test_favicon_link_present_for_js_swap(self):
        html = srv.render(self._board())
        self.assertIn('<link rel="icon" id="favicon" href="">', html)

    def test_status_chip_element_present(self):
        html = srv.render(self._board())
        self.assertIn('id="status-chip"', html)

    def test_version_endpoint_includes_whose_turn_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            srv.save_board(path, self._board(agent_status="working"))
            srv._Handler.board_path = path
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv._Handler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/version") as r:
                    data = json.loads(r.read())
            finally:
                httpd.shutdown()
                t.join()
                httpd.server_close()
            self.assertEqual(data["pending"], 1)
            self.assertEqual(data["agent_status"], "working")
            self.assertIn("has_resolved", data)

    def test_js_string_escapes_script_tag(self):
        out = srv._js_string('</script><script>alert(1)')
        self.assertNotIn("<script", out)


class CliAgentStatusDefaultTest(unittest.TestCase):
    """M5 (SPEC.md §10.3): `painel open`/`serve` set meta.agent_status='idle'
    on first run when the key is absent, best-effort, never overriding an
    agent that has already set it."""

    def test_sets_idle_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            srv.save_board(path, {"title": "T", "meta": {}, "blocks": []})
            _default_agent_status_if_absent(path)
            board = srv.load_board(path)
            self.assertEqual(board["meta"]["agent_status"], "idle")

    def test_does_not_override_existing_status(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            srv.save_board(path, {"title": "T", "meta": {"agent_status": "working"}, "blocks": []})
            _default_agent_status_if_absent(path)
            board = srv.load_board(path)
            self.assertEqual(board["meta"]["agent_status"], "working")

    def test_missing_board_file_does_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            # load_board() auto-creates the file if missing; must not raise.
            _default_agent_status_if_absent(path)
            board = srv.load_board(path)
            self.assertEqual(board["meta"]["agent_status"], "idle")


class LiveHTTPTest(unittest.TestCase):
    """End-to-end smoke test against a real running server on a random port."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.board_path = os.path.join(cls.tmpdir.name, "board.json")
        srv.save_board(cls.board_path, {
            "title": "Teste",
            "blocks": [{"id": "q1", "type": "question", "prompt": "Pergunta?", "answer": None}],
        })
        srv._Handler.board_path = cls.board_path
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv._Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.thread.join()
        cls.httpd.server_close()
        cls.tmpdir.cleanup()

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return r.status, r.read()

    def test_root_serves_html(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Pergunta?", body)

    def test_version_endpoint(self):
        status, body = self._get("/version")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("v", data)

    def test_unknown_path_404(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self._get("/nope")
        self.assertEqual(cm.exception.code, 404)
        cm.exception.close()

    def test_post_event(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/event",
            data=json.dumps({"event": "answer", "block": "q1", "value": "resposta"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.status, 200)
        board = srv.load_board(self.board_path)
        self.assertEqual(board["blocks"][0]["answer"], "resposta")


class EscapingRegressionTest(unittest.TestCase):
    """Every string field set to the XSS payload; rendered output must
    contain zero raw '<script' occurrences."""

    def test_full_board_escaping(self):
        board = {
            "protocol": 1,
            "title": XSS,
            "meta": {"project": XSS, "updated_at": XSS},
            "blocks": [
                {"id": "h1", "type": "heading", "text": XSS},
                {"id": "m1", "type": "markdown", "text": XSS},
                {"id": "n1", "type": "note", "tone": XSS, "text": XSS},
                {"id": "t1", "type": "tasks", "title": XSS,
                 "items": [{"text": XSS, "status": XSS}]},
                {"id": "pl", "type": "plan", "title": XSS, "items": [
                    {"id": XSS, "text": XSS, "status": XSS,
                     "thread": [{"from": XSS, "text": XSS}], "seen": 0},
                ]},
                {"id": "cl", "type": "checklist", "title": XSS,
                 "items": [{"id": XSS, "text": XSS, "checked": False}]},
                {"id": "q1", "type": "question", "prompt": XSS, "answer": XSS},
                {"id": "ch", "type": "choice", "prompt": XSS, "options": [XSS], "selected": XSS},
                {"id": "ap", "type": "approval", "prompt": XSS, "decision": XSS, "comment": XSS},
                {"id": "fm", "type": "form", "prompt": XSS, "fields": [
                    {"id": XSS, "label": XSS, "kind": XSS, "value": XSS, "options": [XSS]},
                ], "submitted": True},
                {"id": "lg", "type": "log", "title": XSS, "entries": [{"ts": XSS, "text": XSS}]},
                {"id": "unk", "type": XSS},
            ],
        }
        html = srv.render(board)
        # The page legitimately contains exactly one literal <script> tag (the
        # page's own JS, from page.py) -- that's not user content. Strip it
        # and confirm no OTHER "<script" (i.e. from unescaped user input)
        # remains anywhere in the document.
        without_real_script_tag = html.replace("<script>", "", 1)
        self.assertNotIn("<script", without_real_script_tag)


if __name__ == "__main__":
    unittest.main()
