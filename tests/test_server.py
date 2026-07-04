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
