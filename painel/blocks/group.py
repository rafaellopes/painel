"""Layout container (M17, docs/SPEC.md §21.1).

A `group` arranges *other* blocks; it renders no content of its own. It carries
a `layout` ("columns" | "stack", default "stack") and a nested `blocks[]`.

Design choice (§21.5): the group renders its children through a **render
callback threaded via ctx** (`ctx["render_block"]`), NOT by importing anything
from server.py. This is the cleaner of the two options the spec offers because
server.py already owns the per-block wrapper (`#blk-<id>` + needs-user marker +
✎ change-request box + lint marker), and a callback lets a child go through
that *exact* pipeline with zero duplication and zero circular import
(server imports blocks, never the reverse). group.py stays a plain block module.

One level only: a `group` may not contain a `group` (§21.1). An accidentally
nested group is flattened -- its container is dropped and its non-group children
are promoted, so no content (and no pending item) is lost. `child_blocks()` is
the single source of that rule, shared by render() and needs_user() so the two
can never disagree about what a group contains.
"""
from __future__ import annotations

from .base import e

TYPE = "group"

STRINGS = {
    # No user-facing literals of its own: a group only labels itself with the
    # agent-supplied `title`, escaped at render time.
}


def child_blocks(block: dict) -> list:
    """Direct children of a group, flattening exactly one level of accidental
    nesting (§21.1: no nested groups). A group-typed child is replaced by its
    own non-group children; anything deeper than that is dropped. Shared by
    render() and needs_user() so nested-block placement/pending stay in sync."""
    out = []
    for c in block.get("blocks", []):
        if c.get("type") == TYPE:
            out.extend(gc for gc in c.get("blocks", []) if gc.get("type") != TYPE)
        else:
            out.append(c)
    return out


def render(block: dict, ctx: dict) -> str:
    children = child_blocks(block)
    render_block = ctx.get("render_block")
    if render_block is not None:
        total = len(children)
        inner = "".join(render_block(c, i, total) for i, c in enumerate(children))
    else:
        # Defensive: rendered outside the page pipeline (e.g. a direct unit
        # call with no callback). Never crash -- fall back to an empty body.
        inner = ""
    layout = block.get("layout", "stack")
    body_cls = "group-body group-cols" if layout == "columns" else "group-body group-stack"
    title = block.get("title", "")
    head = f'<h2 class="section group-title">{e(title)}</h2>' if title else ""
    return f'<div class="group">{head}<div class="{body_cls}">{inner}</div></div>'


def apply(block: dict, event: dict) -> bool:
    # A group has no events of its own; interactions belong to its children,
    # which are dispatched to by id in the normal way (§21.1).
    return False


def needs_user(block: dict) -> list:
    """Recurses into children (§21.1): a group is never itself pending, but a
    pending block *inside* it must still surface in the attention bar under the
    child's own id, so its `#blk-<id>` anchor and needs-user marker keep working.
    REGISTRY is imported lazily -- at call time it's fully built (group.py is
    itself one of the modules it imports during construction)."""
    from painel.blocks import REGISTRY
    out = []
    for c in child_blocks(block):
        mod = REGISTRY.get(c.get("type"))
        if mod is None:
            continue
        out.extend(mod.needs_user(c))
    return out


SILENT_EVENTS: set = set()

JS: str = ""
