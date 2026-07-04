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
    """CRITICAL: boards with zero 'page' blocks render with NO nav UI at all."""

    def test_pageless_board_has_no_nav_markup(self):
        html = srv.render(_single_page_board())
        # Check the rendered BODY (not the static CSS ruleset, which always
        # defines .pages-nav etc. -- it's just unused when no nav renders).
        body = html.split("</style>", 1)[1]
        for marker in ("pages-nav", "pages-sidebar", "pages-dropdown", "page-shell", "page-main", "nav-item", "has-nav", "<nav"):
            self.assertNotIn(marker, body)

    def test_pageless_board_body_tag_unchanged(self):
        html = srv.render(_single_page_board())
        self.assertIn("<body>", html)

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
        # q2 lives on Financeiro and is pending -> its attention link must
        # carry ?page=Financeiro plus the anchor.
        self.assertIn('href="?page=Financeiro#blk-q2"', html)
        # ck lives on Ops and is pending.
        self.assertIn('href="?page=Ops#blk-ck"', html)
        # q1 lives on Home (current page) -> plain anchor, no ?page=.
        self.assertIn('href="#blk-q1"', html)

    def test_nav_links_carry_page_query_param(self):
        html = srv.render(_multi_page_board())
        self.assertIn('href="/?page=Financeiro"', html)
        self.assertIn('href="/?page=Ops"', html)
        self.assertIn('href="/"', html)  # Home link has no query param

    def test_active_page_marked_in_nav(self):
        html = srv.render(_multi_page_board(), active_page="Ops")
        # The active nav item carries the "active" class.
        self.assertIn('class="nav-item active" href="/?page=Ops"', html)


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


if __name__ == "__main__":
    unittest.main()
