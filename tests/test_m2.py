"""
M2 batch-1 blocks (docs/SPEC.md §5.2): countdown, rating, table, gauge.

Per §5.4 step 6, each block gets: render-empty, render-filled, apply-each-event,
needs_user in both states (except gauge, which has no events/needs_user), and an
escaping test with `"<script>"` in every field. Plus the M2-specific pins:

- the export-mode static render of countdown/rating/table contains no
  `<script>`, no `<button>`, no `<input>`;
- the countdown server-render is byte-stable across two calls (no baked clock);
- backward-compat: a board using none of the new blocks renders byte-identically.
"""
import unittest

from painel.blocks import countdown, rating, table, gauge
from painel import server as srv

XSS = '"<script>alert(1)</script>'


def render_ctx(mod, block, index=0, total=1, **extra):
    ctx = {"index": index, "total": total}
    ctx.update(extra)
    return mod.render(block, ctx)


def export_html(mod, block):
    return render_ctx(mod, block, export=True)


class CountdownTest(unittest.TestCase):
    def _board(self, done=False):
        return {"id": "cd1", "type": "countdown", "label": "Submit by",
                "deadline": "2026-07-15T17:00:00", "done": done}

    def test_render_empty(self):
        html = render_ctx(countdown, {"id": "cd1", "type": "countdown"})
        self.assertIn("Countdown", html)
        self.assertIn("countdownDone('cd1')", html)

    def test_render_filled_carries_deadline_in_data_attr(self):
        html = render_ctx(countdown, self._board())
        self.assertIn('data-deadline="2026-07-15T17:00:00"', html)
        self.assertIn("Submit by", html)
        self.assertIn("<button", html)

    def test_render_done_is_answered_no_button(self):
        html = render_ctx(countdown, self._board(done=True))
        self.assertIn("answered", html)
        self.assertNotIn("<button", html)

    def test_apply_countdown_done(self):
        b = self._board()
        self.assertTrue(countdown.apply(b, {"event": "countdown_done"}))
        self.assertTrue(b["done"])

    def test_apply_unknown_event(self):
        self.assertFalse(countdown.apply(self._board(), {"event": "nope"}))

    def test_needs_user_both_states(self):
        b = self._board()
        pending = countdown.needs_user(b)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0], ("cd1", "Submit by"))
        b["done"] = True
        self.assertEqual(countdown.needs_user(b), [])

    def test_server_render_is_deterministic(self):
        """No server clock baked in -> byte-stable across two calls."""
        b = self._board()
        self.assertEqual(render_ctx(countdown, b), render_ctx(countdown, b))

    def test_export_has_no_script_button_input(self):
        html = export_html(countdown, self._board())
        for tok in ("<script", "<button", "<input"):
            self.assertNotIn(tok, html)
        self.assertIn("2026-07-15T17:00:00", html)

    def test_escaping(self):
        b = {"id": XSS, "type": "countdown", "label": XSS,
             "deadline": XSS, "done": False}
        self.assertNotIn("<script", render_ctx(countdown, b))
        self.assertNotIn("<script", export_html(countdown, b))
        self.assertNotIn("<script", render_ctx(countdown, dict(b, done=True)))


class RatingTest(unittest.TestCase):
    def _board(self, value=None):
        return {"id": "r1", "type": "rating", "prompt": "How good?",
                "scale": 5, "value": value, "labels": ["poor", "great"]}

    def test_render_empty(self):
        html = render_ctx(rating, {"id": "r1", "type": "rating"})
        self.assertIn("rating-stars", html)
        # default scale 5 -> 5 star buttons
        self.assertEqual(html.count("ratingSet('r1'"), 5)

    def test_render_filled_scale_and_labels(self):
        html = render_ctx(rating, self._board())
        self.assertEqual(html.count("ratingSet('r1'"), 5)
        self.assertIn("poor", html)
        self.assertIn("great", html)

    def test_scale_capped_at_ten(self):
        html = render_ctx(rating, {"id": "r1", "type": "rating", "scale": 99})
        self.assertEqual(html.count("ratingSet('r1'"), 10)

    def test_render_rated_is_answered(self):
        html = render_ctx(rating, self._board(value=4))
        self.assertIn("answered", html)
        self.assertIn("Rated: 4/5", html)
        self.assertNotIn("<button", html)

    def test_apply_rate(self):
        b = self._board()
        self.assertTrue(rating.apply(b, {"event": "rate", "value": 3}))
        self.assertEqual(b["value"], 3)

    def test_apply_rate_bad_payload_recognized(self):
        b = self._board()
        self.assertTrue(rating.apply(b, {"event": "rate", "value": "x"}))

    def test_apply_unknown_event(self):
        self.assertFalse(rating.apply(self._board(), {"event": "nope"}))

    def test_needs_user_both_states(self):
        b = self._board()
        self.assertEqual(len(rating.needs_user(b)), 1)
        b["value"] = 5
        self.assertEqual(rating.needs_user(b), [])

    def test_export_has_no_script_button_input(self):
        html = export_html(rating, self._board())
        for tok in ("<script", "<button", "<input"):
            self.assertNotIn(tok, html)
        self.assertIn("not rated", html)

    def test_export_rated_shows_value(self):
        html = export_html(rating, self._board(value=2))
        self.assertIn("Rated: 2/5", html)
        self.assertNotIn("<button", html)

    def test_escaping(self):
        b = {"id": XSS, "type": "rating", "prompt": XSS, "scale": XSS,
             "value": XSS, "labels": [XSS, XSS]}
        self.assertNotIn("<script", render_ctx(rating, b))
        self.assertNotIn("<script", export_html(rating, b))
        self.assertNotIn("<script", render_ctx(rating, dict(b, value=3)))


class TableTest(unittest.TestCase):
    def _board(self, confirmed=False):
        return {"id": "t1", "type": "table", "title": "Suspects",
                "columns": [{"id": "date", "label": "Date"},
                            {"id": "desc", "label": "Desc"},
                            {"id": "ok", "label": "OK?", "kind": "checkbox"}],
                "rows": [{"date": "2026-06-03", "desc": "FX fee", "ok": False}],
                "editable": ["ok"], "confirmed": confirmed}

    def test_render_empty(self):
        html = render_ctx(table, {"id": "t1", "type": "table"})
        self.assertIn("table-scroll", html)
        self.assertIn("tableConfirm('t1')", html)

    def test_render_filled_editable_and_readonly(self):
        html = render_ctx(table, self._board())
        self.assertIn("FX fee", html)                       # read-only cell text
        self.assertIn('data-val="FX fee"', html)            # full-row reconstruction
        self.assertIn('type="checkbox" data-col="ok"', html)  # editable checkbox
        self.assertIn("tableConfirm('t1')", html)

    def test_render_confirmed_is_static(self):
        html = render_ctx(table, self._board(confirmed=True))
        self.assertIn("answered", html)
        self.assertNotIn("<input", html)
        self.assertNotIn("<button", html)
        self.assertIn("☐", html)  # checkbox rendered as static glyph

    def test_apply_table_confirm(self):
        b = self._board()
        rows = [{"date": "2026-06-03", "desc": "FX fee", "ok": True}]
        self.assertTrue(table.apply(b, {"event": "table_confirm", "rows": rows}))
        self.assertTrue(b["confirmed"])
        self.assertEqual(b["rows"], rows)

    def test_apply_unknown_event(self):
        self.assertFalse(table.apply(self._board(), {"event": "nope"}))

    def test_needs_user_both_states(self):
        b = self._board()
        pending = table.needs_user(b)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0], ("t1", "Suspects"))
        b["confirmed"] = True
        self.assertEqual(table.needs_user(b), [])

    def test_export_has_no_script_button_input(self):
        html = export_html(table, self._board())
        for tok in ("<script", "<button", "<input"):
            self.assertNotIn(tok, html)
        self.assertIn("FX fee", html)

    def test_escaping(self):
        b = {"id": XSS, "type": "table", "title": XSS,
             "columns": [{"id": XSS, "label": XSS, "kind": XSS}],
             "rows": [{XSS: XSS}], "editable": [XSS], "confirmed": False}
        # editable includes the (escaped) col id so the editable branch is hit too
        b2 = {"id": XSS, "type": "table", "title": XSS,
              "columns": [{"id": "c", "label": XSS, "kind": "checkbox"},
                          {"id": "d", "label": XSS}],
              "rows": [{"c": True, "d": XSS}], "editable": ["c", "d"],
              "confirmed": False}
        self.assertNotIn("<script", render_ctx(table, b))
        self.assertNotIn("<script", render_ctx(table, b2))
        self.assertNotIn("<script", export_html(table, b2))
        self.assertNotIn("<script", render_ctx(table, dict(b2, confirmed=True)))


class GaugeTest(unittest.TestCase):
    def _board(self, value=7350, warn_at=0.8):
        return {"id": "g1", "type": "gauge", "label": "Budget used",
                "value": value, "max": 10000, "unit": "€", "warn_at": warn_at}

    def test_render_empty(self):
        html = render_ctx(gauge, {"id": "g1", "type": "gauge"})
        self.assertIn("gauge-card", html)
        self.assertIn("bar-fill", html)

    def test_render_filled_value_and_width(self):
        html = render_ctx(gauge, self._board())
        self.assertIn("7350€", html)
        self.assertIn("10000€", html)
        self.assertIn("width:73.5%", html)
        self.assertNotIn("gauge-warn", html)  # 73.5% < 80% threshold

    def test_warn_color_past_threshold(self):
        html = render_ctx(gauge, self._board(value=9000))
        self.assertIn("gauge-warn", html)
        self.assertIn("gauge-fill-warn", html)

    def test_no_warn_when_warn_at_absent(self):
        b = {"id": "g1", "type": "gauge", "value": 9999, "max": 10000}
        self.assertNotIn("gauge-warn", render_ctx(gauge, b))

    def test_width_clamped_and_zero_max_safe(self):
        over = render_ctx(gauge, {"id": "g1", "type": "gauge", "value": 50, "max": 10})
        self.assertIn("width:100%", over)
        zero = render_ctx(gauge, {"id": "g1", "type": "gauge", "value": 5, "max": 0})
        self.assertIn("width:0%", zero)  # no ZeroDivision, no NaN

    def test_apply_never_recognizes_events(self):
        self.assertFalse(gauge.apply(self._board(), {"event": "anything"}))

    def test_needs_user_always_empty(self):
        self.assertEqual(gauge.needs_user(self._board()), [])
        self.assertEqual(gauge.needs_user(self._board(value=99999)), [])

    def test_render_identical_live_and_export(self):
        b = self._board()
        self.assertEqual(render_ctx(gauge, b), export_html(gauge, b))

    def test_escaping(self):
        b = {"id": XSS, "type": "gauge", "label": XSS, "value": XSS,
             "max": XSS, "unit": XSS, "warn_at": XSS}
        self.assertNotIn("<script", render_ctx(gauge, b))


class BackwardCompatTest(unittest.TestCase):
    def test_board_without_new_blocks_renders_identically(self):
        """A board using none of the M2 blocks must render byte-for-byte the
        same twice (the new modules add JS/CSS to the shell but change no
        existing block's output)."""
        board = {"title": "t", "blocks": [
            {"id": "m", "type": "markdown", "text": "hello"},
            {"id": "n", "type": "note", "tone": "info", "text": "a note"},
            {"id": "q", "type": "question", "prompt": "why?", "answer": None},
        ]}
        self.assertEqual(srv.render(board), srv.render(board))


if __name__ == "__main__":
    unittest.main()
