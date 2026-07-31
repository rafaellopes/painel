"""
One number that matters (M2, docs/SPEC.md §5.2).

A read-only bar + big number: `value` out of `max`, with a `unit` and a
`warn_at` fraction. When `value >= warn_at * max` the number and bar switch to
the warning color. No events, never pending -- same module shape as `note`, so
it renders identically in live and export mode (no JS, no inputs).
"""
from __future__ import annotations

from .base import e

TYPE = "gauge"

STRINGS = {
    "heading": "Gauge",
}


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt(value, unit: str) -> str:
    """Show the value as-is (int if whole) followed by the unit."""
    n = _num(value, None)
    if n is None:
        shown = e(value)
    elif n == int(n):
        shown = str(int(n))
    else:
        shown = str(n)
    return f"{shown}{e(unit)}"


def _is_warn(block: dict) -> bool:
    warn_at = block.get("warn_at")
    if warn_at is None:
        return False
    mx = _num(block.get("max"), 0.0)
    if mx <= 0:
        return False
    return _num(block.get("value"), 0.0) >= _num(warn_at, 1.0) * mx


def render(block: dict, ctx: dict) -> str:
    label = e(block.get("label", STRINGS["heading"]))
    unit = block.get("unit", "") or ""
    value = block.get("value")
    mx = block.get("max")

    mx_f = _num(mx, 0.0)
    val_f = _num(value, 0.0)
    pct = 0.0
    if mx_f > 0:
        pct = max(0.0, min(100.0, (val_f / mx_f) * 100.0))
    # Deterministic width string (one decimal), never scientific notation.
    width = f"{pct:.1f}".rstrip("0").rstrip(".") or "0"

    warn = _is_warn(block)
    warn_cls = " gauge-warn" if warn else ""
    fill_cls = "bar-fill gauge-fill-warn" if warn else "bar-fill"

    return (
        f'<div class="card gauge-card{warn_cls}"><h3>{label}</h3>'
        f'<div class="gauge-value">'
        f'<span class="gauge-num">{_fmt(value, unit)}</span>'
        f'<span class="gauge-max muted small"> / {_fmt(mx, unit)}</span></div>'
        f'<div class="bar"><div class="{fill_cls}" style="width:{width}%"></div></div>'
        f'</div>'
    )


def apply(block: dict, event: dict) -> bool:
    return False


def needs_user(block: dict) -> list:
    return []


SILENT_EVENTS: set = set()

JS: str = ""
