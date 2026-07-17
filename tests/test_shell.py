"""Navigation shell tests (M14, docs/SPEC.md §18).

The shell is page-shell chrome (server.py's render path + page.py), not a block
and not a blocks/*.py module -- so these are mostly render()-level tests, with
the switcher fed a registry snapshot exactly as the unified service feeds it
(server._ServiceHandler.do_GET passes registry.entries()). The per-project
badge count is asserted to be the SAME number directory.py computes, by calling
the shared directory._needs_user_count -- the two must never drift (§18.2)."""
import os
import tempfile
import unittest

from painel import directory as dir_mod
from painel import server as srv
from painel.server import save_board


def _board(title, project, blocks=None):
    return {"title": title, "meta": {"project": project}, "blocks": blocks or []}


class _TmpProjects(unittest.TestCase):
    """Create real board files on disk and build the registry.entries()-shaped
    snapshot the switcher consumes, without needing a fake HOME (render() takes
    the snapshot directly -- no ~/.painel involved)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _entry(self, slug, title, board):
        path = os.path.join(self._tmp.name, f"{slug}.json")
        save_board(path, board)
        return {"slug": slug, "path": path, "title": title, "missing": False}


_PENDING_Q = {"id": "q1", "type": "question", "prompt": "?", "answer": None}
_ANSWERED_Q = {"id": "q1", "type": "question", "prompt": "?", "answer": "sim"}


# --------------------------------------------------------------------------- #
# §18.1 -- breadcrumb                                                          #
# --------------------------------------------------------------------------- #
class BreadcrumbTest(_TmpProjects):
    def _entries(self):
        return [
            self._entry("spit", "Spit", _board("Spit", "spit")),
            self._entry("livrete", "Livrete", _board("Livrete", "livrete")),
        ]

    def test_service_board_page_breadcrumb_has_all_linked_segments(self):
        board = _board("Spit", "spit", [
            {"id": "h1", "type": "heading", "text": "Home"},
            {"id": "h2", "type": "heading", "text": "Fin", "page": "Financeiro"},
        ])
        html = srv.render(board, active_page="Financeiro", base_path="/spit",
                          slug="spit", entries=self._entries())
        crumb = html.split('<div class="breadcrumb">')[1].split("</div>")[0]
        self.assertIn("Todos os projetos", crumb)
        self.assertIn('href="/"', crumb)          # -> the directory
        self.assertIn('href="/spit"', crumb)      # -> the board Home
        self.assertIn("Financeiro", crumb)        # current page...
        # ...and the current page is plain text, not a link.
        self.assertNotIn('href="/spit/Financeiro"', crumb)

    def test_on_home_the_page_segment_is_absent(self):
        board = _board("Spit", "spit", [{"id": "h1", "type": "heading", "text": "Home"}])
        html = srv.render(board, active_page=None, base_path="/spit", slug="spit",
                          entries=self._entries())
        crumb = html.split('<div class="breadcrumb">')[1].split("</div>")[0]
        self.assertIn("Todos os projetos", crumb)
        self.assertIn("Spit", crumb)
        # No page segment on Home: the project is the last, plain-text crumb,
        # and it is NOT itself a link (you're on it).
        self.assertNotIn('href="/spit"', crumb)

    def test_single_board_serve_has_no_directory_link(self):
        """§18.1: single-board `painel serve` has no directory and no `/` route
        to link to -- the `Todos os projetos` segment is omitted and nothing in
        the breadcrumb points at `/`."""
        board = _board("Sozinho", "sozinho", [{"id": "h1", "type": "heading", "text": "Home"}])
        html = srv.render(board)  # bare == single-board mode (entries is None)
        crumb = html.split('<div class="breadcrumb">')[1].split("</div>")[0]
        self.assertNotIn("Todos os projetos", crumb)
        self.assertNotIn('href="/"', crumb)
        self.assertIn("Sozinho", crumb)  # still shows where you are


# --------------------------------------------------------------------------- #
# §18.2 -- the project switcher                                                #
# --------------------------------------------------------------------------- #
class SwitcherTest(_TmpProjects):
    def test_lists_every_project_with_badges_matching_the_directory(self):
        entries = [
            self._entry("com", "Com Pendentes", _board("Com Pendentes", "com", [
                _PENDING_Q, {"id": "q2", "type": "question", "prompt": "?", "answer": None}])),
            self._entry("sem", "Sem Pendentes", _board("Sem Pendentes", "sem", [_ANSWERED_Q])),
        ]
        # Render while viewing "sem" -- "com"'s badge must travel here.
        html = srv.render(_board("Sem Pendentes", "sem", [_ANSWERED_Q]),
                          base_path="/sem", slug="sem", entries=entries)
        switcher = html.split('<div class="switcher">')[1].split("</aside>")[0]
        self.assertIn('href="/com"', switcher)
        self.assertIn('href="/sem"', switcher)
        # The "com" badge is EXACTLY what the directory computes for that board
        # -- asserted via the shared function, so they can never drift (§18.2).
        com_board = dir_mod._load_board_safe(entries[0]["path"])
        expected = srv._badge(dir_mod._needs_user_count(com_board))
        self.assertEqual(expected, " ②")  # 2 pending questions
        self.assertIn(f'Com Pendentes{expected}', switcher)

    def test_current_project_is_marked(self):
        entries = [
            self._entry("spit", "Spit", _board("Spit", "spit")),
            self._entry("livrete", "Livrete", _board("Livrete", "livrete")),
        ]
        html = srv.render(_board("Spit", "spit"), base_path="/spit", slug="spit",
                          entries=entries)
        switcher = html.split('<div class="switcher">')[1].split("</aside>")[0]
        self.assertIn('class="switcher-item current" href="/spit"', switcher)
        self.assertIn('class="switcher-item" href="/livrete"', switcher)

    def test_other_projects_pending_shows_in_the_summary_line(self):
        """The count travels: viewing a project with nothing pending, the
        collapsed switcher still calls out pending elsewhere (§18.2)."""
        entries = [
            self._entry("here", "Aqui", _board("Aqui", "here", [_ANSWERED_Q])),
            self._entry("there", "Ali", _board("Ali", "there", [_PENDING_Q])),
        ]
        html = srv.render(_board("Aqui", "here", [_ANSWERED_Q]),
                          base_path="/here", slug="here", entries=entries)
        self.assertIn("1 à tua espera noutros projetos", html)

    def test_single_board_switcher_shows_only_current_no_list_no_crash(self):
        """§18.2: single-board `serve` has no registry -- the switcher degrades
        to just the current project's name, no list, no crash."""
        html = srv.render(_board("Sozinho", "sozinho"))  # entries is None
        switcher = html.split('<div class="switcher">')[1].split("</aside>")[0]
        self.assertIn("Sozinho", switcher)
        self.assertNotIn("switcher-item", switcher)   # no project list
        self.assertNotIn("switcher-others", switcher)  # no collapsible details


# --------------------------------------------------------------------------- #
# §18.3 -- the two pending levels stay distinct                                #
# --------------------------------------------------------------------------- #
class TwoLevelsDistinctTest(_TmpProjects):
    def test_attention_bar_and_switcher_badges_coexist_and_are_distinct(self):
        entries = [
            self._entry("here", "Aqui", _board("Aqui", "here", [_PENDING_Q])),
            self._entry("there", "Ali", _board("Ali", "there", [_PENDING_Q])),
        ]
        # Viewing "here" (which itself has a pending item): the attention bar is
        # THIS board's pending, the switcher badge is the OTHER board's.
        html = srv.render(_board("Aqui", "here", [_PENDING_Q]),
                          base_path="/here", slug="here", entries=entries)
        self.assertIn('class="attention"', html)               # this board
        switcher = html.split('<div class="switcher">')[1].split("</aside>")[0]
        self.assertIn("1 à tua espera noutros projetos", switcher)  # other board
        # The two are different regions -- the switcher is not inside the bar.
        attention = html.split('class="attention"')[1].split("</div>")[0]
        self.assertNotIn("switcher", attention)

    def test_attention_bar_count_is_unchanged_by_the_shell(self):
        """§18.3 regression guard: adding the shell must not touch the
        attention bar. Holding the mount point constant, the bar is
        byte-identical whether or not the M14 registry snapshot is threaded in
        -- the attention bar is purely this board's pending, never the
        switcher's."""
        board = lambda: _board("Aqui", "here", [_PENDING_Q,
                               {"id": "q2", "type": "question", "prompt": "?", "answer": None}])
        entries = [self._entry("here", "Aqui", board()),
                   self._entry("there", "Ali", _board("Ali", "there", [_PENDING_Q]))]
        with_shell = srv.render(board(), base_path="/here", slug="here", entries=entries)
        without = srv.render(board(), base_path="/here", slug="here", entries=None)
        def bar(html):
            return html.split('<div class="attention">')[1].split("</div>")[0]
        self.assertEqual(bar(with_shell), bar(without))
        self.assertIn('<span class="attention-count">2</span>', bar(with_shell))


# --------------------------------------------------------------------------- #
# §18.4 -- where it lives (directory unaffected; page-list region conditional) #
# --------------------------------------------------------------------------- #
class DirectoryUnaffectedTest(_TmpProjects):
    def test_directory_page_has_no_board_shell(self):
        """§18.4: the directory IS the top of the hierarchy -- it gets no
        breadcrumb and no project switcher."""
        entries = [self._entry("spit", "Spit", _board("Spit", "spit"))]
        html = dir_mod.render_directory(entries)
        body = html.split("</style>", 1)[1]
        # Assert on the actual markup, not bare words: page.py's shared JS
        # (always in _PAGE, directory included) mentions "switcher-others" for
        # the shell's sessionStorage persistence -- but the directory renders
        # none of the shell's DOM.
        self.assertNotIn('class="breadcrumb"', body)
        self.assertNotIn('class="app-shell"', body)
        self.assertNotIn('class="switcher"', body)
        self.assertNotIn("Todos os projetos", body)


class PageListRegionTest(_TmpProjects):
    def _entries(self):
        return [self._entry("p", "P", _board("P", "p"))]

    def test_zero_or_one_page_board_shows_shell_but_no_page_list(self):
        board = _board("P", "p", [{"id": "h1", "type": "heading", "text": "Só Home"}])
        body = srv.render(board, base_path="/p", slug="p",
                          entries=self._entries()).split("</style>", 1)[1]
        self.assertIn("app-shell", body)     # shell present...
        self.assertIn("breadcrumb", body)
        self.assertNotIn("pages-nav", body)  # ...but no §11.2 page-list region

    def test_multi_page_board_shows_the_page_list_too(self):
        board = _board("P", "p", [
            {"id": "h1", "type": "heading", "text": "Home"},
            {"id": "h2", "type": "heading", "text": "Fin", "page": "Financeiro"},
        ])
        body = srv.render(board, base_path="/p", slug="p",
                          entries=self._entries()).split("</style>", 1)[1]
        self.assertIn("app-shell", body)
        self.assertIn("pages-nav", body)          # the page list appears
        self.assertIn('href="/p/Financeiro"', body)


if __name__ == "__main__":
    unittest.main()
