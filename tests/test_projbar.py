"""Sticky project bar (§18.5): which project you are in must survive
scrolling a long board. The full <header> scrolls away, and the only other
mention of the project was small muted metaline text."""
import unittest

from painel import directory as dir_mod
from painel import server as srv


def _board(project=None, pages=False):
    b = {"title": "Board", "meta": {}, "blocks": [{"id": "h", "type": "heading", "text": "Oi"}]}
    if project:
        b["meta"]["project"] = project
    if pages:
        b["blocks"].append({"id": "h2", "type": "heading", "text": "X", "page": "Estratégia"})
    return b


class ProjectBarTest(unittest.TestCase):
    def test_project_name_rendered_in_the_sticky_bar(self):
        html = srv.render(_board(project="kogno-lancamento"))
        self.assertIn('id="projbar"', html)
        self.assertIn('<span class="proj-name">kogno-lancamento</span>', html)

    def test_bar_is_inside_the_sticky_topbar(self):
        """Project bar and attention bar share ONE sticky container so they
        stack with no per-bar top: offset (the attention bar's height varies
        with link wrapping, which made a second sticky bar unreliable)."""
        html = srv.render(_board(project="p"))
        self.assertIn('<div id="topbar">', html)
        self.assertIn("#topbar {", html.replace("{{", "{"))
        self.assertIn("position:sticky", html)

    def test_falls_back_to_board_title_without_meta_project(self):
        html = srv.render(_board())
        self.assertIn('<span class="proj-name">Board</span>', html)

    def test_active_page_shown_next_to_the_project(self):
        html = srv.render(_board(project="p", pages=True), active_page="Estratégia")
        self.assertIn('<span class="proj-page">Estratégia</span>', html)

    def test_project_name_is_escaped(self):
        html = srv.render(_board(project='<script>alert(1)</script>'))
        self.assertNotIn("<script>alert(1)", html)

    def test_directory_has_no_project_bar(self):
        html = dir_mod.render_directory([])
        self.assertNotIn('id="projbar"', html)
        self.assertIn('<div id="topbar">', html)


if __name__ == "__main__":
    unittest.main()
