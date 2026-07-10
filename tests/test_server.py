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


class NeedsUserWrapperTest(unittest.TestCase):
    """A block waiting on the human must be visually distinct from plain
    info cards (markdown/note/log), generically -- via the wrapper div's
    class, not per-block-module code (any block type gets this for free)."""

    def _board(self):
        return {"blocks": [
            {"id": "m1", "type": "markdown", "text": "just info, never pending"},
            {"id": "q1", "type": "question", "prompt": "Qual o email?", "answer": None},
        ]}

    def test_pending_block_gets_needs_user_class(self):
        html = srv.render(self._board())
        self.assertIn('<div id="blk-q1" class="needs-user">', html)

    def test_non_pending_block_has_no_class(self):
        html = srv.render(self._board())
        self.assertIn('<div id="blk-m1">', html)
        self.assertNotIn('<div id="blk-m1" class="needs-user">', html)

    def test_answered_block_loses_the_class(self):
        board = self._board()
        board["blocks"][1]["answer"] = "ana@acme.com"
        html = srv.render(board)
        self.assertNotIn('id="blk-q1" class="needs-user"', html)

    def test_needs_user_marker_present_for_every_pending_type(self):
        # One of each interactive type still unresolved -- every single one
        # must get the wrapper class, proving this is generic, not special-
        # cased per block type.
        board = {"blocks": [
            {"id": "ck", "type": "checklist", "items": [{"id": "c1", "text": "x", "checked": False}]},
            {"id": "ch", "type": "choice", "prompt": "?", "options": ["A"], "selected": None},
            {"id": "ap", "type": "approval", "prompt": "?", "decision": None},
            {"id": "fm", "type": "form", "prompt": "?", "fields": [{"id": "f", "label": "L"}], "submitted": False},
        ]}
        html = srv.render(board)
        for bid in ("ck", "ch", "ap", "fm"):
            self.assertIn(f'<div id="blk-{bid}" class="needs-user">', html)


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


class ChangeRequestTest(unittest.TestCase):
    """M8 (docs/SPEC.md §12): universal change_request event, generic ✎
    per-block button, global affordance, change_requests card rendering, and
    the attention-bar exclusion."""

    def _handler_apply(self, board_path, data):
        srv._Handler.board_path = board_path
        h = srv._Handler.__new__(srv._Handler)
        return h._apply(data)

    def test_change_request_per_block_appends_and_not_silent(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            srv.save_board(path, {"blocks": [{"id": "regras", "type": "markdown", "text": "x"}]})
            silent = self._handler_apply(
                path, {"event": "change_request", "block": "regras", "value": "o prazo passa a 12h"}
            )
            self.assertFalse(silent)
            board = srv.load_board(path)
            self.assertEqual(len(board["change_requests"]), 1)
            cr = board["change_requests"][0]
            self.assertEqual(cr["block"], "regras")
            self.assertEqual(cr["text"], "o prazo passa a 12h")
            self.assertEqual(cr["status"], "open")

    def test_change_request_global_block_null_appends_and_not_silent(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            srv.save_board(path, {"blocks": []})
            silent = self._handler_apply(
                path, {"event": "change_request", "block": None, "value": "adiciona fase de testes"}
            )
            self.assertFalse(silent)
            board = srv.load_board(path)
            self.assertEqual(len(board["change_requests"]), 1)
            self.assertIsNone(board["change_requests"][0]["block"])
            self.assertEqual(board["change_requests"][0]["text"], "adiciona fase de testes")

    def test_change_requests_persist_and_get_stable_ids(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            srv.save_board(path, {"blocks": []})
            self._handler_apply(path, {"event": "change_request", "block": None, "value": "primeiro"})
            self._handler_apply(path, {"event": "change_request", "block": None, "value": "segundo"})
            board = srv.load_board(path)
            ids = [cr["id"] for cr in board["change_requests"]]
            self.assertEqual(len(ids), 2)
            self.assertEqual(len(set(ids)), 2)

    def test_ico_button_appears_on_every_block_type_generically(self):
        # Every block type gets the ✎ button purely from render()'s wrapper
        # injection -- not from any blocks/*.py module.
        board = {"blocks": [
            {"id": "h1", "type": "heading", "text": "x"},
            {"id": "m1", "type": "markdown", "text": "x"},
            {"id": "n1", "type": "note", "text": "x"},
            {"id": "tk", "type": "tasks", "title": "t", "items": []},
            {"id": "lg", "type": "log", "title": "t", "entries": []},
            {"id": "q1", "type": "question", "prompt": "?", "answer": None},
        ]}
        html = srv.render(board)
        for bid in ("h1", "m1", "n1", "tk", "lg", "q1"):
            self.assertIn(f"crToggle('{bid}')", html)
            self.assertIn(f'id="cr-box-{bid}"', html)

    def test_global_affordance_present(self):
        html = srv.render({"blocks": []})
        self.assertIn("crToggleGlobal()", html)
        self.assertIn('id="cr-box-global"', html)
        self.assertIn("crSendGlobal()", html)
        self.assertIn("Pedir alteração", html)

    def test_open_change_requests_render_as_own_card(self):
        board = {"blocks": [{"id": "regras", "type": "markdown", "text": "x"}],
                 "change_requests": [
                     {"id": "cr1", "block": "regras", "text": "o prazo passa a 12h", "status": "open", "ts": ""},
                 ]}
        html = srv.render(board)
        self.assertIn('class="card cr-card"', html)
        self.assertIn("Pedidos em aberto", html)
        self.assertIn("o prazo passa a 12h", html)
        self.assertIn("#blk-regras", html)

    def test_declined_or_done_change_requests_not_rendered(self):
        board = {"blocks": [], "change_requests": [
            {"id": "cr1", "block": None, "text": "already done", "status": "done", "ts": ""},
            {"id": "cr2", "block": None, "text": "declined one", "status": "declined", "ts": ""},
        ]}
        html = srv.render(board)
        self.assertNotIn('class="card cr-card"', html)
        self.assertNotIn("already done", html)
        self.assertNotIn("declined one", html)

    def test_open_change_requests_do_not_appear_in_attention_bar(self):
        # Critical (docs/SPEC.md §12.4): an open change request is something
        # the AGENT owes a resolution to, not the human -- it must never
        # show up in _needs_user()'s output nor in the human-facing
        # attention bar, mirroring M7/chat.py's identical reasoning for an
        # unanswered user chat message.
        board = {"blocks": [{"id": "regras", "type": "markdown", "text": "x"}],
                 "change_requests": [
                     {"id": "cr1", "block": "regras", "text": "muda isto", "status": "open", "ts": ""},
                 ]}
        self.assertEqual(srv._needs_user(board), [])
        html = srv.render(board)
        self.assertNotIn('class="attention"', html)
        # The card itself is still present (standing record) -- just not
        # counted/linked from the attention bar.
        self.assertIn('class="card cr-card"', html)

    def test_escaping_regression_in_change_request_text(self):
        board = {"blocks": [{"id": "regras", "type": "markdown", "text": "x"}],
                 "change_requests": [
                     {"id": "cr1", "block": "regras", "text": XSS, "status": "open", "ts": ""},
                 ]}
        html = srv.render(board)
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_change_request_with_item_appends_item_field(self):
        # M12: the ❓ on a specific checklist item posts the same event with
        # an extra 'item' -- still handled entirely by the generic
        # change_request path, never dispatched into checklist.apply().
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            srv.save_board(path, {"blocks": [
                {"id": "prep", "type": "checklist", "title": "t",
                 "items": [{"id": "p2", "text": "Ter 2 contas de teste", "checked": False}]},
            ]})
            silent = self._handler_apply(
                path, {"event": "change_request", "block": "prep", "item": "p2",
                       "value": "não sei onde arranjar isto"}
            )
            self.assertFalse(silent)
            board = srv.load_board(path)
            cr = board["change_requests"][0]
            self.assertEqual(cr["block"], "prep")
            self.assertEqual(cr["item"], "p2")
            self.assertEqual(cr["text"], "não sei onde arranjar isto")
            # The checklist item itself must be untouched -- this event never
            # reaches checklist.apply()/its 'check' handler.
            self.assertFalse(board["blocks"][0]["items"][0]["checked"])

    def test_change_request_without_item_still_defaults_to_none(self):
        # Backward compat: every change_request before M12 had no 'item' key
        # at all -- .get("item") must keep returning None, not KeyError/crash.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            srv.save_board(path, {"blocks": [{"id": "regras", "type": "markdown", "text": "x"}]})
            self._handler_apply(path, {"event": "change_request", "block": "regras", "value": "muda"})
            board = srv.load_board(path)
            self.assertIsNone(board["change_requests"][0]["item"])

    def test_open_change_request_with_item_shows_item_text_and_link(self):
        board = {"blocks": [{"id": "prep", "type": "checklist", "title": "t", "items": [
            {"id": "p2", "text": "Ter 2 contas de teste", "checked": False},
        ]}], "change_requests": [
            {"id": "cr1", "block": "prep", "item": "p2", "text": "não sei onde arranjar isto",
             "status": "open", "ts": ""},
        ]}
        html = srv.render(board)
        self.assertIn("não sei onde arranjar isto", html)
        self.assertIn("Ter 2 contas de teste", html)  # resolved item text, not just the id
        self.assertIn("#blk-prep", html)

    def test_open_change_request_with_item_still_excluded_from_attention_bar(self):
        # Item already checked (no other source of pending) -- isolates that
        # the open change request itself contributes nothing to the bar.
        board = {"blocks": [{"id": "prep", "type": "checklist", "title": "t", "items": [
            {"id": "p2", "text": "x", "checked": True},
        ]}], "change_requests": [
            {"id": "cr1", "block": "prep", "item": "p2", "text": "y", "status": "open", "ts": ""},
        ]}
        self.assertEqual(srv._needs_user(board), [])
        html = srv.render(board)
        self.assertNotIn('class="attention"', html)


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


class ResourcesVersionFreshnessTest(unittest.TestCase):
    """M11 (docs/SPEC.md §15.2): /version's `v` must widen to include the
    mtime of any path a block's watched_paths() hook returns, so the page
    auto-refreshes when a linked file changes on disk without any edit to
    board.json itself. Also pins the backward-compat guarantee: boards with
    no block defining watched_paths() must see zero change in /version's
    behavior (it stays exactly board.json's own mtime)."""

    def _run_server(self, board_path):
        srv._Handler.board_path = board_path
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv._Handler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        return httpd, t, port

    def _version(self, port):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/version") as r:
            return json.loads(r.read())["v"]

    def test_version_bumps_when_watched_file_mtime_changes(self):
        with tempfile.TemporaryDirectory() as d:
            watched = os.path.join(d, "mockup.png")
            with open(watched, "w") as fh:
                fh.write("x")
            board_path = os.path.join(d, "board.json")
            srv.save_board(board_path, {
                "title": "T", "blocks": [
                    {"id": "res1", "type": "resources", "items": [
                        {"label": "Mockup", "kind": "file", "path": watched},
                    ]},
                ],
            })
            httpd, t, port = self._run_server(board_path)
            try:
                v1 = self._version(port)
                # Push the watched file's mtime forward without touching
                # board.json at all -- this is the whole point of §15.2.
                future = os.path.getmtime(watched) + 120
                os.utime(watched, (future, future))
                v2 = self._version(port)
                self.assertGreater(v2, v1)
            finally:
                httpd.shutdown()
                t.join()
                httpd.server_close()

    def test_version_unaffected_when_no_block_defines_watched_paths(self):
        """Regression guard: every pre-M11 board (no resources block, no
        block defining watched_paths()) must produce identical /version
        behavior to before -- v stays exactly board.json's own mtime."""
        with tempfile.TemporaryDirectory() as d:
            board_path = os.path.join(d, "board.json")
            srv.save_board(board_path, {
                "title": "T", "blocks": [
                    {"id": "m1", "type": "markdown", "text": "hi"},
                    {"id": "tk", "type": "tasks", "items": []},
                ],
            })
            httpd, t, port = self._run_server(board_path)
            try:
                v = self._version(port)
                self.assertEqual(v, os.path.getmtime(board_path))
            finally:
                httpd.shutdown()
                t.join()
                httpd.server_close()

    def test_missing_watched_path_ignored_not_error(self):
        with tempfile.TemporaryDirectory() as d:
            board_path = os.path.join(d, "board.json")
            srv.save_board(board_path, {
                "title": "T", "blocks": [
                    {"id": "res1", "type": "resources", "items": [
                        {"label": "Perdido", "kind": "file", "path": "/no/such/path"},
                    ]},
                ],
            })
            httpd, t, port = self._run_server(board_path)
            try:
                v = self._version(port)  # must not raise / must not 500
                self.assertEqual(v, os.path.getmtime(board_path))
            finally:
                httpd.shutdown()
                t.join()
                httpd.server_close()


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

    def test_unknown_path_falls_back_to_home_not_404(self):
        # Friendly path-based page routing means any GET path that isn't
        # /version or /event is treated as a page name; a name that doesn't
        # match any real page just falls back to Home (200), the same
        # graceful-degradation spirit as unknown block types (docs/SPEC.md
        # §0 point 5) -- it must not 404 or crash.
        status, body = self._get("/nope")
        self.assertEqual(status, 200)
        self.assertIn(b"<!doctype html>", body)

    def test_get_event_path_still_404s(self):
        # /event is POST-only; a GET to it must not be swallowed by the
        # page-route fallback.
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self._get("/event")
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
