"""
The `image` block (M18, docs/SPEC.md §22) — a domain-agnostic image primitive.

The exact inverse of `upload` (M15, §19): where `upload` writes human→disk,
`image` reads disk→page. The agent brings a ready local asset (convention:
`painel-assets/…`) or inlines a small `data:` figure, and this block places it
next to text — typically in one column of a `group:columns` (§21.1) beside a
`note`/`markdown`. pAInel never fetches, generates, or transforms images
(§22.2/§22.6); it renders what is already local.

Security line (§22.3): a project-relative `src` is served through the contained
`GET …/asset?p=` endpoint (whitelisted-images-only, realpath-contained). A
`data:` URI is inlined verbatim (still `e()`-escaped as an attribute). A remote
`http(s)` `src` is **refused** — the block renders the `alt` in a visible
"remote src refused" fallback rather than fetching it (no SSRF, no tracking
pixel, no exfiltration via URL).

Read-only, same module shape as `markdown`/`note`: no events, `apply`→False,
`needs_user`→[], `SILENT_EVENTS` empty, no JS.
"""
from __future__ import annotations

from urllib.parse import quote

from .base import e, md_inline

TYPE = "image"

STRINGS = {
    "missing": "image not shown (no src)",
    "remote": "image not shown (remote src refused)",
}


def _is_remote(src: str) -> bool:
    """A remote http(s) URL — refused (§22.3, the security line). Matched
    case-insensitively and after stripping leading whitespace so a padded
    ` HTTP://…` can't slip past into an `<img src>`."""
    s = src.lstrip().lower()
    return s.startswith("http://") or s.startswith("https://") or s.startswith("//")


def _is_data_uri(src: str) -> bool:
    return src.lstrip().lower().startswith("data:")


def _resolve_src(src: str, base_path: str) -> str | None:
    """The value to put in `<img src>`, or None when the src must NOT be loaded
    (missing, or a refused remote URL). A `data:` URI is returned verbatim; a
    project-relative path becomes the contained `…/asset?p=<percent-encoded>`
    URL (§22.3/§22.4). The caller `e()`-escapes whatever this returns."""
    if not src:
        return None
    if _is_data_uri(src):
        return src.strip()
    if _is_remote(src):
        return None  # refused — caller renders the alt fallback, never fetches
    # Project-relative path → the contained asset endpoint. The relpath is
    # percent-encoded into the query string; the server realpath-contains it.
    return f"{base_path}/asset?p={quote(src, safe='')}"


def _fallback(alt: str, reason: str) -> str:
    """A visible box carrying the `alt` text when the image can't be shown
    (§22.3/§22.4): a broken/refused/absent image must read as intentional
    fallback copy, never a broken-image glyph. `alt`/`reason` `e()`-escaped."""
    return (
        f'<figure class="card img-block img-fallback">'
        f'<div class="img-fallback-box">'
        f'<span class="img-fallback-alt">{e(alt)}</span>'
        f'<span class="img-fallback-note small muted">{e(reason)}</span>'
        f'</div></figure>'
    )


def render(block: dict, ctx: dict) -> str:
    src = block.get("src") or ""
    alt = block.get("alt") or ""  # REQUIRED per spec; render safely if absent
    base_path = ctx.get("base_path", "") if ctx else ""

    # Remote/missing → the alt fallback box, never an <img> that would fetch.
    if not src:
        return _fallback(alt, STRINGS["missing"])
    if _is_remote(src):
        return _fallback(alt, STRINGS["remote"])

    resolved = _resolve_src(src, base_path)
    if resolved is None:  # defensive: any src _resolve_src declined
        return _fallback(alt, STRINGS["remote"])

    # Sizing (§22.4): default responsive max-width:100% (from CSS) so the image
    # never overflows its column; an optional cap + object-fit are inline style.
    fit = block.get("fit")
    styles = []
    max_width = block.get("max_width")
    if max_width:
        styles.append(f"max-width:{e(str(max_width))}")
    if fit in ("contain", "cover"):
        styles.append(f"object-fit:{fit}")
    style_attr = f' style="{";".join(styles)}"' if styles else ""

    # `onerror` swaps in the fallback box for an asset that 404s / fails to
    # decode at load time (§22.4: a missing/failed image shows the alt, not a
    # broken-image glyph). Pure inline DOM swap — no page-level JS needed.
    fallback_html = e(
        f'<div class="img-fallback-box"><span class="img-fallback-alt">{e(alt)}</span>'
        f'<span class="img-fallback-note small muted">{e(STRINGS["missing"])}</span></div>'
    )
    img = (
        f'<img src="{e(resolved)}" alt="{e(alt)}" loading="lazy"{style_attr} '
        f'onerror="this.onerror=null;this.outerHTML=\'{fallback_html}\'">'
    )

    caption = block.get("caption")
    cap_html = (
        f'<figcaption class="img-cap small muted">{md_inline(e(caption))}</figcaption>'
        if caption else ""
    )
    return f'<figure class="card img-block">{img}{cap_html}</figure>'


def apply(block: dict, event: dict) -> bool:
    return False


def needs_user(block: dict) -> list:
    return []


SILENT_EVENTS: set = set()

JS: str = ""
