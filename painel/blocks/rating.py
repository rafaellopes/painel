"""
Quick calibrated feedback (M2, docs/SPEC.md §5.2).

A 1..`scale` star picker (scale capped at 10) with optional low/high endpoint
`labels`. The human clicks a star -> event `rate {value:int}`; the block is
pending until `value` is set.

Export (M3, §24.2): a snapshot has no JS/buttons -- it shows the chosen value
(or "not rated") as static text with static filled/empty stars.
"""
from __future__ import annotations

from .base import e, md_inline

TYPE = "rating"

STRINGS = {
    "heading": "Rating",
    "pending_label": "Rating pending",
    "not_rated": "not rated",
    "rated": "Rated",
}

_MAX_SCALE = 10
_STAR_FULL = "★"   # ★
_STAR_EMPTY = "☆"  # ☆


def _scale(block: dict) -> int:
    try:
        n = int(block.get("scale", 5))
    except (TypeError, ValueError):
        n = 5
    return max(1, min(_MAX_SCALE, n))


def _value(block: dict):
    v = block.get("value")
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _labels_html(block: dict) -> str:
    labels = block.get("labels") or []
    if not labels:
        return ""
    low = e(labels[0]) if len(labels) > 0 else ""
    high = e(labels[1]) if len(labels) > 1 else ""
    return (
        f'<div class="rating-labels small muted">'
        f'<span>{low}</span><span>{high}</span></div>'
    )


def _stars_static(scale: int, value) -> str:
    filled = value or 0
    return "".join(
        f'<span class="star{" on" if i <= filled else ""}">'
        f'{_STAR_FULL if i <= filled else _STAR_EMPTY}</span>'
        for i in range(1, scale + 1)
    )


def render(block: dict, ctx: dict) -> str:
    bid = e(block.get("id", ""))
    prompt = md_inline(e(block.get("prompt", "")))
    scale = _scale(block)
    value = _value(block)

    # Answered (live or export): show the chosen value + static filled stars.
    if value is not None:
        return (
            f'<div class="card rating-card answered"><h3>{e(STRINGS["heading"])}</h3>'
            f'<p>{prompt}</p>'
            f'<div class="rating-stars">{_stars_static(scale, value)}</div>'
            f'{_labels_html(block)}'
            f'<div class="answer">{e(STRINGS["rated"])}: {value}/{scale}</div></div>'
        )

    # Export (M3, §24.2): no buttons/JS -- empty stars + "not rated".
    if (ctx or {}).get("export"):
        return (
            f'<div class="card rating-card"><h3>{e(STRINGS["heading"])}</h3>'
            f'<p>{prompt}</p>'
            f'<div class="rating-stars">{_stars_static(scale, None)}</div>'
            f'{_labels_html(block)}'
            f'<div class="answer muted">{e(STRINGS["not_rated"])}</div></div>'
        )

    stars = "".join(
        f'<button class="star" type="button" title="{i}/{scale}" '
        f'onclick="ratingSet(\'{bid}\',{i})">{_STAR_EMPTY}</button>'
        for i in range(1, scale + 1)
    )
    return (
        f'<div class="card rating-card"><h3>{e(STRINGS["heading"])}</h3>'
        f'<p>{prompt}</p>'
        f'<div class="rating-stars" id="rat-{bid}">{stars}</div>'
        f'{_labels_html(block)}</div>'
    )


def apply(block: dict, event: dict) -> bool:
    if event.get("event") != "rate":
        return False
    try:
        block["value"] = int(event.get("value"))
    except (TypeError, ValueError):
        return True  # recognized event, ignored bad payload
    return True


def needs_user(block: dict) -> list:
    if _value(block) is None:
        return [(block.get("id", ""), STRINGS["pending_label"])]
    return []


SILENT_EVENTS: set = set()

JS = """
function ratingSet(id, value) {
  const row = document.getElementById('rat-' + id);
  if (row) {
    const stars = row.querySelectorAll('.star');
    stars.forEach(function (s, i) { s.textContent = (i < value) ? '★' : '☆'; });
  }
  send({event:'rate', block:id, value:value}).then(reloadSoon);
}
"""
