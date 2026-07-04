"""Shared helpers for block modules."""
from __future__ import annotations

import html


def e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def md_inline(s: str) -> str:
    """Tiny inline markdown: **bold**, `code`, and line breaks. Input pre-escaped."""
    out, i, n = [], 0, len(s)
    while i < n:
        if s.startswith("**", i):
            j = s.find("**", i + 2)
            if j != -1:
                out.append("<strong>" + s[i + 2:j] + "</strong>")
                i = j + 2
                continue
        if s[i] == "`":
            j = s.find("`", i + 1)
            if j != -1:
                out.append("<code>" + s[i + 1:j] + "</code>")
                i = j + 1
                continue
        out.append(s[i])
        i += 1
    return "".join(out).replace("\n", "<br>")


def find_item(block: dict, item_id: str) -> dict | None:
    for it in block.get("items", []):
        if str(it.get("id")) == str(item_id):
            return it
    return None
