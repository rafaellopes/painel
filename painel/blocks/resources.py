"""
Documents/mockups/reference links that stay live (M11, docs/SPEC.md §15).

Read-only, no events -- the agent composes items, like `tasks`/`log`. The
live-freshness feature is two layers, both computed fresh on every request
(no caching, same spirit as `_needs_user()`/the hub's registry re-read):

1. Per-item: `render()` stats each `file`/`folder` path at render time and
   shows a relative "atualizado há Xm/h/d" string (§15.2 point 1). A missing
   path renders a visible warning instead of crashing or vanishing.
2. Page-level: `watched_paths()` (the new optional block-module hook, §2.1)
   returns every `file`/`folder` path so server.py's /version handler can
   fold their mtimes into the page's auto-refresh signal (§15.2 point 2).
"""
from __future__ import annotations

import os

from .base import e, relative_time

TYPE = "resources"

STRINGS = {
    "missing": "⚠ ficheiro não encontrado",
}

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")


def _freshness_html(path: str) -> str:
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return f'<span class="res-warn">{e(STRINGS["missing"])}</span>'
    return f'<span class="muted small">{e(relative_time(mtime))}</span>'


def _thumb_html(path: str) -> str:
    """Small inline thumbnail for image files; generic glyph otherwise.
    Folders never get here (only called for kind:"file")."""
    if path.lower().endswith(_IMAGE_EXTS):
        # <img src="file://..."> loads fine cross-browser (it's a resource
        # fetch, not a same-origin-restricted navigation) -- see §15.3.
        return f'<img class="res-thumb" src="file://{e(path)}" alt="">'
    return '<span class="res-glyph">📄</span>'


def _item_html(item: dict) -> str:
    label = e(item.get("label", ""))
    kind = item.get("kind")
    if kind == "url":
        url = e(item.get("url", ""))
        return (
            '<li class="res-item">'
            f'<a href="{url}" target="_blank" rel="noopener">{label} 🔗</a>'
            '</li>'
        )
    path = item.get("path", "")
    # file:// navigation is unreliable cross-browser/OS for security reasons,
    # so the path is shown as plain monospace text, never a clickable link
    # (§15.3) -- only `url` items are real <a> links.
    thumb = _thumb_html(path) if kind == "file" else '<span class="res-glyph">📁</span>'
    return (
        '<li class="res-item">'
        f'{thumb}'
        f'<span class="res-label">{label}<br>'
        f'<code class="res-path small muted">{e(path)}</code></span>'
        f'<span class="res-fresh">{_freshness_html(path)}</span>'
        '</li>'
    )


def render(block: dict, ctx: dict) -> str:
    items = block.get("items", [])
    rows = "".join(_item_html(it) for it in items)
    title = e(block.get("title", "Documentos e mockups"))
    return f'<div class="card"><h3>{title}</h3><ul class="res-list">{rows}</ul></div>'


def apply(block: dict, event: dict) -> bool:
    return False


def needs_user(block: dict) -> list:
    return []


def watched_paths(block: dict) -> list:
    """§2.1/§15.2: every file/folder item's path, so /version's freshness
    signal folds in changes made outside of board.json itself. `url` items
    are excluded -- they're external, not ours to stat."""
    return [
        it.get("path", "")
        for it in block.get("items", [])
        if it.get("kind") in ("file", "folder") and it.get("path")
    ]


SILENT_EVENTS: set = set()

JS: str = ""
