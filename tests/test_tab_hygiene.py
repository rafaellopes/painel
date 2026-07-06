"""Tab hygiene (M10, docs/SPEC.md §14.1): duplicate-tab self-close via
BroadcastChannel + reuse of the existing `pulse` CSS animation.

BroadcastChannel is a browser API with no headless-browser harness available
in this environment, so these tests are static: they assert the rendered
page HTML/JS actually contains the right setup code, that the channel name
is derived client-side from `location.port` (no new server-side plumbing),
and that the `pulse` keyframes are reused -- not duplicated -- by the new
JS."""
import re
import unittest

from painel import hub as hub_mod
from painel import server as srv


def _simple_board():
    return {
        "title": "Board",
        "meta": {},
        "blocks": [{"id": "h1", "type": "heading", "text": "Olá"}],
    }


class BroadcastChannelSetupTest(unittest.TestCase):
    def test_page_includes_broadcastchannel_setup(self):
        html = srv.render(_simple_board())
        self.assertIn("BroadcastChannel", html)
        self.assertIn("new BroadcastChannel(channelName)", html)

    def test_channel_name_derived_client_side_from_location_port(self):
        """No new server-side plumbing: the channel name pattern
        'painel-<port>' is built in JS from location.port, not baked into
        the rendered page server-side for a specific port."""
        html = srv.render(_simple_board())
        self.assertIn("'painel-' + (location.port || '80')", html)
        # And critically: the literal prefix appears only in that one JS
        # expression, never with a concrete port number templated in.
        self.assertNotIn('"painel-8765"', html)
        self.assertNotIn("'painel-8765'", html)

    def test_announce_and_already_open_protocol_present(self):
        html = srv.render(_simple_board())
        self.assertIn("type: 'announce'", html)
        self.assertIn("type === 'announce'", html)
        self.assertIn("type: 'already-open'", html)
        self.assertIn("type === 'already-open'", html)

    def test_duplicate_notice_element_and_pt_pt_copy_present(self):
        html = srv.render(_simple_board())
        self.assertIn('id="dup-notice"', html)
        self.assertIn("já tens este pAInel aberto — a fechar este separador", html)

    def test_window_close_called_on_duplicate(self):
        html = srv.render(_simple_board())
        self.assertIn("window.close()", html)


class PulseReuseTest(unittest.TestCase):
    """The original/surviving tab's pulse must reuse the exact same
    `@keyframes pulse` already defined for the plan-thread reply dot
    (docs/SPEC.md §5.1) -- not a second, near-duplicate animation."""

    def test_keyframes_pulse_defined_exactly_once(self):
        html = srv.render(_simple_board())
        occurrences = re.findall(r"@keyframes\s+pulse\b", html)
        self.assertEqual(len(occurrences), 1, "expected exactly one @keyframes pulse rule")

    def test_no_second_near_duplicate_keyframes_animation(self):
        html = srv.render(_simple_board())
        # Every @keyframes block in the page must be named "pulse" -- i.e.
        # there is no second, differently-named pulse-like animation.
        all_keyframes = re.findall(r"@keyframes\s+([A-Za-z0-9_-]+)", html)
        self.assertEqual(all_keyframes, ["pulse"])

    def test_dup_pulse_class_uses_the_shared_pulse_animation(self):
        html = srv.render(_simple_board())
        self.assertIn("header.dup-pulse", html)
        self.assertIn("animation:pulse", html)

    def test_new_js_applies_dup_pulse_to_page_header(self):
        """The reused animation is applied by the new JS via the 'dup-pulse'
        class toggled on the page header element (id="page-header"), which
        this milestone introduces as the visible target for the pulse --
        plan.py's own reply-dot pulse targets a different element (the ✎
        button), so this is a new, sensibly-named class reusing the same
        keyframes rather than the same selector."""
        html = srv.render(_simple_board())
        self.assertIn('id="page-header"', html)
        self.assertIn("hdr.classList.add('dup-pulse')", html)


class HubIncludesTabHygieneTest(unittest.TestCase):
    """The hub is also a page a human might open twice (bookmarked, or via
    `painel open` ensuring it's running repeatedly) -- it reuses page.py's
    shared _PAGE template directly, so it gets the same BroadcastChannel
    setup for free with zero changes to hub.py."""

    def test_hub_renders_without_crashing(self):
        html = hub_mod.render_hub([])
        self.assertIn("<html", html)
        self.assertIn("</html>", html)

    def test_hub_page_includes_broadcastchannel_setup_too(self):
        html = hub_mod.render_hub([])
        self.assertIn("BroadcastChannel", html)
        self.assertIn("'painel-' + (location.port || '80')", html)

    def test_hub_page_header_present_for_pulse_target(self):
        html = hub_mod.render_hub([])
        self.assertIn('id="page-header"', html)


if __name__ == "__main__":
    unittest.main()
