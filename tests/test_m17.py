"""Adaptive layout & phase-awareness tests (M17, docs/SPEC.md §21).

Covers the four features and, above all, the load-bearing integration guard:
a block nested inside a `group` keeps the ENTIRE per-block pipeline — the
`#blk-<id>` anchor, the needs-user marker + attention bar, the ✎ change-request
box, and the M12 lint marker — because nested blocks render through the exact
same `_wrap_block` path as top-level ones (§21.1)."""
import unittest

from painel import server as srv
from painel.blocks import group

XSS = '"<script>alert(1)</script>'


def _body_markup(html: str) -> str:
    """The rendered markup region only -- after the <style> CSS and before the
    <script> JS, both of which always mention M17 class names generically."""
    return html.split("</style>", 1)[1].split("<script>")[0]


# --------------------------------------------------------------------------- #
# §21.1 -- the group container                                                #
# --------------------------------------------------------------------------- #
class GroupColumnsTest(unittest.TestCase):
    def test_columns_render_side_by_side_with_group_cols_class(self):
        board = {"blocks": [
            {"id": "g1", "type": "group", "layout": "columns", "title": "Two", "blocks": [
                {"id": "a", "type": "note", "text": "A"},
                {"id": "b", "type": "note", "text": "B"},
            ]},
        ]}
        html = srv.render(board)
        self.assertIn("group-cols", html)
        # Both children rendered, each in its own generic wrapper.
        self.assertIn('<div id="blk-a">', html)
        self.assertIn('<div id="blk-b">', html)
        # The group's own wrapper contains both child wrappers (nesting).
        g = html.split('<div id="blk-g1">')[1]
        self.assertLess(g.index('id="blk-a"'), g.index('id="blk-b"'))

    def test_stack_is_the_default_and_has_no_columns(self):
        board = {"blocks": [
            {"id": "g1", "type": "group", "title": "Section", "blocks": [
                {"id": "a", "type": "note", "text": "A"},
            ]},
        ]}
        body = _body_markup(srv.render(board))
        self.assertIn("group-stack", body)
        self.assertNotIn("group-cols", body)

    def test_group_columns_wrap_at_the_reused_narrow_breakpoint(self):
        # §21.1/§11.2: columns must collapse to a stack at the EXISTING
        # max-width:600px breakpoint, not a new one. The media query that
        # already carries the page-shell rules must now also cover .group-cols.
        html = srv.render({"blocks": []})
        css = html.split("<style>")[1].split("</style>")[0]
        mq = css.split("@media (max-width:600px)")[1].split("}}" if "}}" in css else "\n}")[0]
        # Find the 600px block and assert it addresses .group-cols.
        block = css[css.index("@media (max-width:600px)"):]
        block = block[: block.index("</style>")] if "</style>" in block else block
        self.assertIn(".group-cols", block)
        self.assertIn("flex-direction:column", block)

    def test_nested_group_is_flattened_children_preserved_no_double_columns(self):
        # §21.1: a group may NOT contain a group. The inner container is
        # dropped (flattened) and its non-group children promoted, so no
        # content is lost and there is never a doubly-nested columns layout.
        board = {"blocks": [
            {"id": "outer", "type": "group", "layout": "columns", "blocks": [
                {"id": "keep", "type": "note", "text": "kept"},
                {"id": "inner", "type": "group", "layout": "columns", "blocks": [
                    {"id": "promoted", "type": "note", "text": "promoted"},
                ]},
            ]},
        ]}
        body = _body_markup(srv.render(board))
        # Exactly one columns layout, not two.
        self.assertEqual(body.count("group-cols"), 1)
        # Both the direct child and the promoted grandchild render...
        self.assertIn('<div id="blk-keep">', body)
        self.assertIn('<div id="blk-promoted">', body)
        # ...and the inner group's own wrapper is gone.
        self.assertNotIn('<div id="blk-inner">', body)

    def test_child_blocks_helper_flattens_one_level(self):
        blk = {"id": "g", "type": "group", "blocks": [
            {"id": "a", "type": "note"},
            {"id": "gg", "type": "group", "blocks": [
                {"id": "b", "type": "note"},
                {"id": "ggg", "type": "group", "blocks": [{"id": "c", "type": "note"}]},
            ]},
        ]}
        ids = [c["id"] for c in group.child_blocks(blk)]
        self.assertEqual(ids, ["a", "b"])  # 'c' is two levels deep -> dropped

    def test_group_escapes_its_title(self):
        html = srv.render({"blocks": [
            {"id": "g1", "type": "group", "title": XSS, "blocks": [
                {"id": "a", "type": "note", "text": XSS},
            ]},
        ]})
        self.assertNotIn("<script>alert(1)</script>", html)


# --------------------------------------------------------------------------- #
# THE load-bearing integration test (§21.1)                                   #
# --------------------------------------------------------------------------- #
class NestedBlockPipelineTest(unittest.TestCase):
    """A pending `question` inside a `group` (columns) must keep the FULL
    per-block pipeline working: needs_user, the attention bar, the #blk anchor,
    the ✎ change-request box, and the M12 lint marker."""

    def _board(self):
        return {"blocks": [
            {"id": "g1", "type": "group", "layout": "columns", "blocks": [
                {"id": "qn", "type": "question", "prompt": "Which region?", "answer": None},
                {"id": "nt", "type": "note", "text": "context"},
            ]},
        ]}

    def test_nested_pending_question_appears_in_needs_user(self):
        pending = srv._needs_user(self._board())
        self.assertIn("qn", [bid for bid, _ in pending])

    def test_nested_pending_question_shows_in_attention_bar(self):
        html = srv.render(self._board())
        self.assertIn('class="attention"', html)
        # Linked by its own id, not the group's.
        self.assertIn('href="/#blk-qn"', html)

    def test_nested_block_gets_the_anchor_and_needs_user_marker(self):
        html = srv.render(self._board())
        self.assertIn('<div id="blk-qn" class="needs-user">', html)

    def test_nested_block_gets_the_change_request_box(self):
        html = srv.render(self._board())
        self.assertIn("crToggle('qn')", html)
        self.assertIn('id="cr-box-qn"', html)
        self.assertIn("crToggle('nt')", html)  # the non-pending sibling too

    def test_nested_checklist_item_keeps_lint_and_item_cr(self):
        # M12/M16 markers survive nesting (they live in the block's own render,
        # which runs identically inside a group).
        board = {"blocks": [
            {"id": "g1", "type": "group", "layout": "columns", "blocks": [
                {"id": "ck", "type": "checklist", "title": "Steps", "items": [
                    {"id": "c1", "text": "Run scripts/set_tasty.sh (paste client secret + refresh token)",
                     "checked": False},
                ]},
            ]},
        ]}
        html = srv.render(board)
        self.assertIn("crToggleItem('ck','c1')", html)   # M12 per-item ❓
        self.assertIn("lint-warn", html)                  # M16 lint marker

    def test_nested_pending_counts_on_the_right_page_badge(self):
        # A group carrying a page: its pending child counts on THAT page.
        board = {"blocks": [
            {"id": "h1", "type": "heading", "text": "Home"},
            {"id": "g1", "type": "group", "layout": "columns", "page": "Fin", "blocks": [
                {"id": "qn", "type": "question", "prompt": "?", "answer": None},
            ]},
        ]}
        counts = srv._page_pending_counts(board)
        self.assertEqual(counts["Fin"], 1)
        self.assertEqual(counts[None], 0)
        # Attention link points at the group's page, not "/".
        html = srv.render(board)
        self.assertIn('href="/Fin#blk-qn"', html)


# --------------------------------------------------------------------------- #
# §21.2 -- hero                                                                #
# --------------------------------------------------------------------------- #
class HeroTest(unittest.TestCase):
    def test_single_hero_gets_hero_class(self):
        html = srv.render({"blocks": [
            {"id": "m1", "type": "markdown", "hero": True, "text": "Verdict"},
        ]})
        self.assertIn('<div id="blk-m1" class="hero">', html)

    def test_only_first_hero_wins_rest_fall_back(self):
        html = srv.render({"blocks": [
            {"id": "m1", "type": "markdown", "hero": True, "text": "first"},
            {"id": "m2", "type": "note", "hero": True, "text": "second"},
        ]})
        self.assertIn('<div id="blk-m1" class="hero">', html)
        self.assertIn('<div id="blk-m2">', html)  # no hero class
        self.assertNotIn('<div id="blk-m2" class="hero">', html)

    def test_hero_budget_is_shared_across_nesting(self):
        # A hero nested in a group (rendered first, in DOM order) spends the
        # budget, so a later top-level hero falls back.
        html = srv.render({"blocks": [
            {"id": "g1", "type": "group", "blocks": [
                {"id": "hn", "type": "note", "hero": True, "text": "nested"},
            ]},
            {"id": "top", "type": "markdown", "hero": True, "text": "top"},
        ]})
        self.assertIn('<div id="blk-hn" class="hero">', html)
        self.assertNotIn('<div id="blk-top" class="hero">', html)

    def test_hero_block_content_is_escaped(self):
        html = srv.render({"blocks": [
            {"id": "m1", "type": "markdown", "hero": True, "text": XSS},
        ]})
        self.assertNotIn("<script>alert(1)</script>", html)


# --------------------------------------------------------------------------- #
# §21.3 -- collapsed / progressive disclosure                                 #
# --------------------------------------------------------------------------- #
class CollapsedTest(unittest.TestCase):
    def test_collapsed_block_renders_details_and_summary(self):
        html = srv.render({"blocks": [
            {"id": "n1", "type": "note", "collapsed": True, "title": "Long ref",
             "text": "lots of prose"},
        ]})
        self.assertIn('<details class="blk-collapse" data-key="n1">', html)
        self.assertIn("<summary>Long ref</summary>", html)

    def test_pending_block_is_force_expanded_even_if_collapsed(self):
        # §21.3: you cannot fold away an open question and expect it answered.
        html = srv.render({"blocks": [
            {"id": "q1", "type": "question", "prompt": "?", "answer": None, "collapsed": True},
        ]})
        # No <details> wrapping this block (the CSS/JS mention the class name
        # generically -- check the rendered markup, not the whole page).
        self.assertNotIn('<details class="blk-collapse"', html)
        self.assertIn('<div id="blk-q1" class="needs-user">', html)

    def test_resolved_interactive_block_can_be_collapsed(self):
        html = srv.render({"blocks": [
            {"id": "q1", "type": "question", "prompt": "?", "answer": "done", "collapsed": True},
        ]})
        self.assertIn('<details class="blk-collapse" data-key="q1">', html)

    def test_collapse_persistence_and_anchor_open_js_present(self):
        html = srv.render({"blocks": [
            {"id": "n1", "type": "note", "collapsed": True, "text": "x"},
        ]})
        self.assertIn("openDetails", html)          # sessionStorage set name
        self.assertIn("openTargetDetails", html)    # anchor-open handler
        self.assertIn("hashchange", html)           # opens on fragment change
        self.assertIn("blk-collapse", html)

    def test_collapsed_summary_is_escaped(self):
        html = srv.render({"blocks": [
            {"id": "n1", "type": "note", "collapsed": True, "title": XSS, "text": "x"},
        ]})
        self.assertNotIn("<script>alert(1)</script>", html)


# --------------------------------------------------------------------------- #
# §21.4 -- meta.phase                                                          #
# --------------------------------------------------------------------------- #
class PhaseTest(unittest.TestCase):
    def test_each_phase_sets_its_body_class_and_pill(self):
        for phase, label in (("exploring", "Exploring"), ("deciding", "Deciding"),
                             ("executing", "Executing"), ("done", "Done")):
            board = {"title": "B", "meta": {"phase": phase}, "blocks": []}
            html = srv.render(board)
            self.assertIn(f'phase-{phase}"', html)               # body class
            self.assertIn(f"phase-pill-{phase}", html)           # header pill
            self.assertIn(label, html)

    def test_absent_phase_adds_no_phase_class_or_pill(self):
        html = srv.render({"title": "B", "meta": {}, "blocks": []})
        self.assertIn('body class="has-nav"', html)  # exactly today's class
        self.assertNotIn("phase-", html.split("<style>")[0] + html.split("</style>")[1])

    def test_unknown_phase_is_ignored(self):
        html = srv.render({"title": "B", "meta": {"phase": "nonsense"}, "blocks": []})
        self.assertIn('body class="has-nav"', html)
        self.assertNotIn("phase-pill-nonsense", html)

    def test_phase_has_no_picker(self):
        # The agent owns phase; the human never sets it -> no form control.
        html = srv.render({"title": "B", "meta": {"phase": "deciding"}, "blocks": []})
        pill = html.split('phase-pill-deciding"')[1].split("</span>")[0]
        self.assertNotIn("<select", pill)
        self.assertNotIn("<input", pill)

    def test_phase_and_agent_status_coexist(self):
        board = {"title": "B", "meta": {"phase": "executing", "agent_status": "working"},
                 "blocks": []}
        html = srv.render(board)
        self.assertIn("phase-pill-executing", html)
        self.assertIn("The agent is working", html)


# --------------------------------------------------------------------------- #
# Backward-compat guard: a board using NONE of M17 has zero M17 markup         #
# --------------------------------------------------------------------------- #
class LegacyBoardNoM17MarkupTest(unittest.TestCase):
    """The cleaner backward-compat guard (per §21 intro / the milestone note):
    a board that uses no group/hero/collapsed/phase must render none of M17's
    per-block markup. Checked against the rendered BODY *before* the <script>
    (the static CSS ruleset and the JS always mention these class names -- they
    are just unused). The golden test pins the byte-for-byte demo separately."""

    def _legacy_board(self):
        return {"title": "Legacy", "meta": {"agent_status": "working"}, "blocks": [
            {"id": "h1", "type": "heading", "text": "Old"},
            {"id": "m1", "type": "markdown", "text": "plain"},
            {"id": "q1", "type": "question", "prompt": "?", "answer": None},
        ]}

    def test_no_m17_markup_in_rendered_body(self):
        html = srv.render(self._legacy_board())
        body = html.split("</style>", 1)[1].split("<script>")[0]  # markup, no CSS/JS
        self.assertIn('body class="has-nav"', body)   # exactly today's body class
        for marker in ('group-cols', 'group-stack', 'class="hero"',
                       '<details class="blk-collapse"', "phase-pill", "phase-exploring",
                       "phase-deciding", "phase-executing", "phase-done"):
            self.assertNotIn(marker, body)


if __name__ == "__main__":
    unittest.main()
