"""Multi-page navigation tests (M6, docs/SPEC.md §11)."""
import unittest

from painel import server as srv


def _single_page_board():
    """No block carries a 'page' field -- the critical backward-compat case."""
    return {
        "title": "Board",
        "meta": {},
        "blocks": [
            {"id": "h1", "type": "heading", "text": "Olá"},
            {"id": "q1", "type": "question", "prompt": "?", "answer": None},
        ],
    }


def _multi_page_board():
    return {
        "title": "Board",
        "meta": {},
        "blocks": [
            {"id": "h1", "type": "heading", "text": "Home"},
            {"id": "q1", "type": "question", "prompt": "Home pergunta?", "answer": None},
            {"id": "f1", "type": "heading", "text": "Fin", "page": "Financeiro"},
            {"id": "q2", "type": "question", "prompt": "Fin pergunta?", "answer": None, "page": "Financeiro"},
            {"id": "q3", "type": "question", "prompt": "Fin pergunta 2?", "answer": "ok", "page": "Financeiro"},
            {"id": "o1", "type": "heading", "text": "Ops", "page": "Ops"},
            {"id": "ck", "type": "checklist", "title": "T", "page": "Ops",
             "items": [{"id": "c1", "text": "x", "checked": False}]},
        ],
    }


class BackwardCompatTest(unittest.TestCase):
    """M6's original contract was "a board with zero 'page' blocks renders with
    NO nav UI at all". M14 (docs/SPEC.md §18.2) deliberately supersedes that:
    the app-shell (breadcrumb + project switcher) is now on EVERY board page,
    and a 0-1 page board simply has no PAGE-LIST region inside it. So the
    surviving guarantee here is narrower and precise: the *§11.2 page-list nav*
    (pages-sidebar / pages-dropdown / nav-item / <nav>) is what stays absent
    for a pageless board -- not the whole shell."""

    def test_pageless_board_has_no_page_list_nav(self):
        html = srv.render(_single_page_board())
        # Check the rendered BODY (not the static CSS ruleset, which always
        # defines .pages-nav etc. -- it's just unused when no page list renders).
        body = html.split("</style>", 1)[1]
        for marker in ("pages-nav", "pages-sidebar", "pages-dropdown", "nav-item", "<nav"):
            self.assertNotIn(marker, body)

    def test_pageless_board_still_gets_the_app_shell(self):
        """§18.2: a single-page board still shows the switcher + breadcrumb,
        just no page list."""
        body = srv.render(_single_page_board()).split("</style>", 1)[1]
        self.assertIn("app-shell", body)
        self.assertIn("switcher", body)
        self.assertIn("breadcrumb", body)

    def test_pages_helper_returns_only_home(self):
        self.assertEqual(srv._pages(_single_page_board()), [None])


class MultiPageRenderTest(unittest.TestCase):
    def test_pages_order_is_first_appearance_home_first(self):
        self.assertEqual(srv._pages(_multi_page_board()), [None, "Financeiro", "Ops"])

    def test_nav_appears_with_two_plus_pages(self):
        html = srv.render(_multi_page_board())
        self.assertIn("pages-nav", html)
        self.assertIn("has-nav", html)

    def test_nav_shows_page_names(self):
        html = srv.render(_multi_page_board())
        self.assertIn("Financeiro", html)
        self.assertIn("Ops", html)
        self.assertIn("Board", html)  # home shown as board title

    def test_home_page_default_active_renders_only_home_blocks(self):
        html = srv.render(_multi_page_board())
        self.assertIn("Home pergunta?", html)
        self.assertNotIn("Fin pergunta?", html)
        # Ops/Financeiro blocks must not be in the DOM at all when Home is active.
        self.assertNotIn("id=\"blk-q2\"", html)
        self.assertNotIn("id=\"blk-ck\"", html)

    def test_active_page_renders_only_its_blocks(self):
        html = srv.render(_multi_page_board(), active_page="Financeiro")
        self.assertIn("Fin pergunta?", html)
        self.assertNotIn("Home pergunta?", html)
        self.assertNotIn("id=\"blk-ck\"", html)  # Ops block absent

    def test_unknown_page_falls_back_to_home(self):
        html = srv.render(_multi_page_board(), active_page="Nonexistent")
        self.assertIn("Home pergunta?", html)
        self.assertNotIn("Fin pergunta?", html)

    def test_badge_counts_match_needs_user_per_page(self):
        board = _multi_page_board()
        counts = srv._page_pending_counts(board)
        # Home: q1 pending -> 1
        self.assertEqual(counts[None], 1)
        # Financeiro: q2 pending, q3 answered -> 1
        self.assertEqual(counts["Financeiro"], 1)
        # Ops: ck unchecked item -> 1
        self.assertEqual(counts["Ops"], 1)

    def test_zero_pending_page_has_no_badge(self):
        board = _multi_page_board()
        # Resolve everything on Financeiro.
        for b in board["blocks"]:
            if b.get("page") == "Financeiro" and b["type"] == "question":
                b["answer"] = "done"
        html = srv.render(board)
        nav_section = html.split("<nav")[1].split("</nav>")[0]
        # No badge glyph should be attached right after "Financeiro" now.
        self.assertNotIn("Financeiro ①", nav_section)
        self.assertNotIn("Financeiro①", nav_section)

    def test_pending_page_has_badge_glyph(self):
        html = srv.render(_multi_page_board())
        nav_section = html.split("<nav")[1].split("</nav>")[0]
        self.assertIn("①", nav_section)

    def test_attention_bar_links_cross_pages(self):
        html = srv.render(_multi_page_board())  # active page = Home
        # q2 lives on Financeiro and is pending -> its attention link is a
        # friendly path, e.g. "/Financeiro#blk-q2", not "?page=...".
        self.assertIn('href="/Financeiro#blk-q2"', html)
        # ck lives on Ops and is pending.
        self.assertIn('href="/Ops#blk-ck"', html)
        # q1 lives on Home -- always an absolute "/#blk-id", never a bare
        # fragment, so the link works even when a different page is active.
        self.assertIn('href="/#blk-q1"', html)

    def test_nav_links_use_friendly_paths(self):
        html = srv.render(_multi_page_board())
        self.assertIn('href="/Financeiro"', html)
        self.assertIn('href="/Ops"', html)
        self.assertIn('href="/"', html)  # Home link is just "/"
        # No query-string page links anywhere in fresh nav markup.
        self.assertNotIn("?page=", html.split("<nav")[1].split("</nav>")[0])

    def test_active_page_marked_in_nav(self):
        html = srv.render(_multi_page_board(), active_page="Ops")
        # The active nav item carries the "active" class.
        self.assertIn('class="nav-item active" href="/Ops"', html)

    def test_page_name_with_special_chars_is_url_quoted(self):
        board = _multi_page_board()
        board["blocks"][0]["page"] = "Contas & Recibos"
        html = srv.render(board)
        # quote(..., safe='') percent-encodes space and "&"; the raw
        # characters must never leak into an href attribute unescaped.
        self.assertIn("Contas%20%26%20Recibos", html)
        self.assertNotIn('href="/Contas & Recibos"', html)


class HttpPageParamTest(unittest.TestCase):
    """End-to-end: GET /?page=X filters correctly over a real running server."""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.TemporaryDirectory()
        self.board_path = f"{self.tmpdir.name}/board.json"
        srv.save_board(self.board_path, _multi_page_board())
        srv._Handler.board_path = self.board_path
        from http.server import ThreadingHTTPServer
        import threading
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv._Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.thread.join()
        self.httpd.server_close()
        self.tmpdir.cleanup()

    def _get(self, path):
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return r.read().decode()

    def test_root_defaults_to_home(self):
        body = self._get("/")
        self.assertIn("Home pergunta?", body)
        self.assertNotIn("Fin pergunta?", body)

    def test_query_param_selects_financeiro(self):
        body = self._get("/?page=Financeiro")
        self.assertIn("Fin pergunta?", body)
        self.assertNotIn("Home pergunta?", body)

    def test_query_param_selects_ops(self):
        body = self._get("/?page=Ops")
        self.assertIn("checklist", body)
        self.assertNotIn("Fin pergunta?", body)

    def test_friendly_path_selects_financeiro(self):
        body = self._get("/Financeiro")
        self.assertIn("Fin pergunta?", body)
        self.assertNotIn("Home pergunta?", body)

    def test_friendly_path_selects_ops(self):
        body = self._get("/Ops")
        self.assertIn("checklist", body)
        self.assertNotIn("Fin pergunta?", body)

    def test_unknown_path_falls_back_to_home(self):
        # e.g. a stray browser /favicon.ico request -- must not 404 or crash.
        body = self._get("/favicon.ico")
        self.assertIn("Home pergunta?", body)

    def test_version_and_event_paths_are_not_treated_as_pages(self):
        import json
        body = self._get("/version")
        payload = json.loads(body)
        self.assertIn("pending", payload)  # confirms /version's own handler ran


if __name__ == "__main__":
    unittest.main()
