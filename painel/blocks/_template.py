"""
Copy-me skeleton for a new block type.

To add a block:
1. Copy this file to blocks/<type>.py.
2. Set TYPE to a unique, stable, snake_case name.
3. Fill in STRINGS with every user-facing literal (PT-PT), for future i18n.
4. Implement render() — escape ALL user content with e() from base.py;
   JSON embedded in an HTML attribute must go through e(json.dumps(...));
   colors must come from CSS custom properties, never hardcoded.
5. Implement apply() for each event this block introduces (prefix event
   names with "<type>_"); add UI-housekeeping event names to SILENT_EVENTS.
6. Implement needs_user() — what should the attention bar say, if anything?
7. Add any JS your block needs to the JS constant, namespaced "<type>Verb()".
8. Add tests: render-empty, render-filled, apply-each-event,
   needs_user-both-states, and an escaping test ('"<script>alert(1)</script>'
   in every string field must not appear unescaped in the rendered output).
9. Add one example block to _demo_board() in painel/__main__.py.
10. Update docs/SPEC.md (§5.1/5.2) and the painel skill docs.

This module itself is NOT registered: it has no TYPE attribute, so
blocks/__init__.py's auto-discovery skips it.
"""
from __future__ import annotations

from .base import e, md_inline  # noqa: F401  (example imports; adjust as needed)

STRINGS = {
    # "example_label": "Rótulo de exemplo",
}


def render(block: dict, ctx: dict) -> str:
    """Return the block's HTML. ctx = {"index": int, "total": int}.
    Must escape ALL user content with e(). Must not raise on missing
    fields -- use .get() with sensible defaults."""
    raise NotImplementedError


def apply(block: dict, event: dict) -> bool:
    """Mutate `block` in place for an event addressed to it.
    Return True if the event is recognized (even if it changed nothing),
    False if this module doesn't handle that event name."""
    return False


def needs_user(block: dict) -> list:
    """Labels (PT) for everything in this block currently waiting on the
    human. Empty list = nothing pending. Drives the attention bar."""
    return []


SILENT_EVENTS: set = set()
"""Event names that must NOT be emitted to stdout (UI housekeeping)."""

JS: str = ""
"""Optional JS functions this block needs, appended once to the page."""
