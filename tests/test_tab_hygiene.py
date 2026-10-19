"""Tab hygiene (M10, docs/SPEC.md §14.1): duplicate-tab self-close via
BroadcastChannel + reuse of the existing `pulse` CSS animation.

BroadcastChannel is a browser API with no headless-browser harness available
in this environment, so these tests are static: they assert the rendered
page HTML/JS actually contains the right setup code, that the channel name
identifies the right thing, and that the `pulse` keyframes are reused -- not
duplicated -- by the new JS.

M13 (§17.4) changes what "the right thing" is: with every board sharing the
service's one port, the channel must key on the SLUG. See
ChannelKeysOnSlugTest -- that one is guarding against two different boards
mutually self-closing each other."""
import re
import unittest

from painel import directory as dir_mod
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

    def test_single_board_mode_still_derives_the_channel_from_location_port(self):
        """`painel serve` is unchanged by M13 (§17.5): one process serves one
        board, so the port genuinely still is the instance identity (§6.6) and
        the channel name keeps being built client-side from location.port,
        byte for byte as M10 shipped it."""
        html = srv.render(_simple_board())
        self.assertIn("'painel-' + (location.port || '80')", html)
        # And critically: the literal prefix appears only in that one JS
        # expression, never with a concrete port number templated in.
        self.assertNotIn('"painel-8765"', html)
        self.assertNotIn("'painel-8765'", html)

    def test_hello_protocol_present(self):
        """M10.4 (§14.4): one-shot `hello` carrying birth+id. The old
        announce/already-open handshake is gone -- the newest tab now simply
        wins and the older one retires, so no reply is needed."""
        html = srv.render(_simple_board())
        self.assertIn("type: 'hello'", html)
        self.assertIn("type !== 'hello'", html)
        self.assertNotIn("already-open", html)

    def test_duplicate_notice_element_and_copy_present(self):
        html = srv.render(_simple_board())
        self.assertIn('id="dup-notice"', html)
        # Copy must not promise closing: a mid-edit tab deliberately stays.
        self.assertIn("this pAInel moved to the tab you just opened", html)

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

    def test_no_second_near_duplicate_pulse_animation(self):
        html = srv.render(_simple_board())
        # The point of this guard (M10) is that the reply-dot / dup-pulse
        # effect must REUSE `pulse`, not spawn a second pulse-like animation.
        # Genuinely different effects with their own purpose are fine -- the
        # `spin` ("a enviar" spinner) and `shake` (failed-send) animations
        # added for action feedback are not pulses. So: allow other named
        # keyframes, but forbid a second box-shadow "pulse" clone.
        all_keyframes = re.findall(r"@keyframes\s+([A-Za-z0-9_-]+)", html)
        self.assertEqual(all_keyframes.count("pulse"), 1)
        self.assertEqual(len(all_keyframes), len(set(all_keyframes)),
                         "each @keyframes name should be defined exactly once")
        # No differently-named animation should be another box-shadow pulse.
        for name in set(all_keyframes) - {"pulse"}:
            body = re.search(r"@keyframes\s+" + re.escape(name) + r"\s*\{\{?(.*?)\}\}?\s*(?=@keyframes|\Z)",
                             html, re.DOTALL)
            block = body.group(1) if body else ""
            self.assertNotIn("box-shadow:0 0 0", block,
                             f"@keyframes {name} looks like a duplicate of pulse")

class NewestTabWinsTest(unittest.TestCase):
    """M10.4 (docs/SPEC.md §14.4): the tab born LATEST wins, because it is the
    one that already has focus. The older duplicate retires. This inverts
    M10.1, which kept the oldest and closed the newest -- the behaviour that
    left the user hunting through dozens of tabs for the survivor."""

    def test_retirement_is_decided_by_birth_with_an_id_tiebreak(self):
        html = srv.render(_simple_board())
        self.assertIn("msg.birth > myBirth", html)
        self.assertIn("msg.id > myId", html)

    def test_newer_tab_does_nothing(self):
        """The winner must not interrupt: no notice, no pulse, just work."""
        html = srv.render(_simple_board())
        self.assertIn("if (!theyAreNewer) return;", html)

    def test_retired_tab_stops_polling(self):
        """A superseded tab that the browser refuses to close must go inert,
        never reload, so it cannot be mistaken for a live board later."""
        html = srv.render(_simple_board())
        self.assertIn("if (tabRetired) return;", html)

    def test_mid_edit_tab_is_never_closed(self):
        """Never close over unsent text -- reuses the reload poller's own
        isBusy() guard."""
        html = srv.render(_simple_board())
        self.assertIn("if (isBusy()) return;", html)

    def test_no_notification_is_fired_for_duplicates(self):
        """M10.3's Notification is gone (§14.3): it depended on a permission
        that was not granted in practice, so it never fired. The only
        remaining Notification is M5's whose-turn one."""
        html = srv.render(_simple_board())
        self.assertNotIn("pAInel already open", html)
        self.assertEqual(html.count("new Notification("), 1)

    def test_channel_keys_on_the_page_too(self):
        """Two pages of one project are not duplicates of each other."""
        html = srv.render(_simple_board())
        self.assertIn("+ '|' + location.pathname", html)


class ChannelKeysOnSlugTest(unittest.TestCase):
    """M13 (docs/SPEC.md §17.4), the bug this milestone had to fix while
    landing: M10 keyed the BroadcastChannel on location.port, which was right
    when one board == one port. Under the unified service every board shares
    ONE port -- so a port-keyed channel would make two DIFFERENT boards
    believe they were duplicate tabs of each other, and one would close
    itself. The channel must key on the slug instead."""

    def test_service_rendered_board_keys_the_channel_on_its_slug(self):
        html = srv.render(_simple_board(), base_path="/livrete", slug="livrete")
        self.assertIn("""const channelName = 'painel-' + "livrete" + '|' + location.pathname;""", html)
        # The port must play no part in a service-served board's channel name.
        self.assertNotIn("'painel-' + (location.port", html)

    def test_two_different_boards_get_two_different_channel_names(self):
        a = srv.render(_simple_board(), base_path="/proj-a", slug="proj-a")
        b = srv.render(_simple_board(), base_path="/proj-b", slug="proj-b")
        self.assertIn('painel-\' + "proj-a"', a)
        self.assertIn('painel-\' + "proj-b"', b)
        self.assertNotIn("proj-b", a)
        self.assertNotIn("proj-a", b)

    def test_same_board_two_pages_are_not_duplicates(self):
        """M10.4 (§14.4) narrows this: the channel keys on board AND page via
        location.pathname, so a project page and its sub-page can be open side
        by side. Only genuinely identical tabs dedupe."""
        home = srv.render(_simple_board(), base_path="/livrete", slug="livrete")
        page = srv.render(_simple_board(), base_path="/livrete", slug="livrete",
                          active_page="Estratégia")
        self.assertIn("""'painel-' + "livrete" + '|'""", home)
        self.assertIn("""'painel-' + "livrete" + '|'""", page)

    def test_slug_is_json_escaped_into_the_script_body(self):
        """Same rule as every other value templated into <script> (§1's
        e(json.dumps(x)) precedent): a slug can only be [a-z0-9-] today, but
        the escaping must not depend on that staying true."""
        html = srv.render(_simple_board(), base_path="/x", slug='</script><script>alert(1)')
        self.assertNotIn("<script>alert(1)", html)


class DirectoryIncludesTabHygieneTest(unittest.TestCase):
    """The directory is also a page a human might open twice (it's the thing
    you bookmark, §13.3) -- it reuses page.py's shared _PAGE template directly,
    so it gets the same BroadcastChannel setup for free with zero changes to
    directory.py. It sits at the service root with no slug of its own, so it
    keeps the port-derived name: directory tabs dedupe against each other and
    never against a board's tab."""

    def test_directory_renders_without_crashing(self):
        html = dir_mod.render_directory([])
        self.assertIn("<html", html)
        self.assertIn("</html>", html)

    def test_directory_page_includes_broadcastchannel_setup_too(self):
        html = dir_mod.render_directory([])
        self.assertIn("BroadcastChannel", html)
        self.assertIn("'painel-' + (location.port || '80')", html)

    def test_directory_page_header_present_for_pulse_target(self):
        html = dir_mod.render_directory([])
        self.assertIn('id="page-header"', html)


if __name__ == "__main__":
    unittest.main()
