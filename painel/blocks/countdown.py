"""
Deadline pressure for a human step (M2, docs/SPEC.md §5.2).

A labelled deadline with a live client-side countdown (days/h/m). Past the
deadline the card turns red and the remaining text becomes "overdue". The
human clears it with a "Done" button (event `countdown_done`); until then the
block is pending in the attention bar.

Determinism (M2 acceptance): the SERVER never bakes a clock into the HTML --
it would make the golden non-deterministic. The static markup only carries the
`deadline` in a `data-deadline` attribute; `countdownTick()` computes and
refreshes the remaining time client-side on load and on an interval. So the
server render is byte-stable across calls.

Export (M3, §24.2): a snapshot has no JS -- it renders the deadline plus the
done/overdue state as static text, with no button and no script.
"""
from __future__ import annotations

from datetime import datetime

from .base import e

TYPE = "countdown"

STRINGS = {
    "heading": "Countdown",
    "overdue": "overdue",
    "done": "Done",
    "done_state": "Done",
    "computing": "…",
    "pending_label": "Deadline",
}


def _parse_deadline(deadline: str):
    """Best-effort ISO-8601 parse; None when it can't be read (never raises)."""
    if not deadline:
        return None
    try:
        return datetime.fromisoformat(str(deadline))
    except (TypeError, ValueError):
        return None


def _static_state(block: dict) -> str:
    """The remaining-time text for a JS-free render (export). Compares the
    deadline to the wall clock ONCE at render time -- only ever used in export
    mode, never in the live/golden render, so no determinism concern."""
    if block.get("done"):
        return STRINGS["done_state"]
    dt = _parse_deadline(block.get("deadline", ""))
    if dt is None:
        return ""
    return STRINGS["overdue"] if datetime.now() >= dt else ""


def render(block: dict, ctx: dict) -> str:
    bid = e(block.get("id", ""))
    label = e(block.get("label", ""))
    deadline = e(block.get("deadline", ""))
    done = bool(block.get("done"))

    # Export (M3, §24.2): NO JS, NO button -- deadline + done/overdue as text.
    if (ctx or {}).get("export"):
        state = _static_state(block)
        overdue_cls = " cd-overdue" if state == STRINGS["overdue"] else ""
        done_cls = " answered" if done else ""
        tail = f' · <span class="cd-state">{e(state)}</span>' if state else ""
        return (
            f'<div class="card countdown-card{overdue_cls}{done_cls}">'
            f'<h3>{e(STRINGS["heading"])}</h3>'
            f'<div class="cd-label">{label}</div>'
            f'<div class="cd-remaining muted">{e(STRINGS["computing"])}'
            f' <span class="cd-deadline small muted">{deadline}</span>{tail}</div>'
            f'</div>'
        )

    if done:
        # Resolved: outcome visible, dimmed like other answered blocks (§4.1).
        return (
            f'<div class="card countdown-card answered">'
            f'<h3>{e(STRINGS["heading"])}</h3>'
            f'<div class="cd-label">{label}</div>'
            f'<div class="answer">{e(STRINGS["done_state"])}'
            f' <span class="cd-deadline small muted">{deadline}</span></div>'
            f'</div>'
        )

    # Live: static markup + a data-deadline the JS reads. No server clock here.
    return (
        f'<div class="card countdown-card">'
        f'<h3>{e(STRINGS["heading"])}</h3>'
        f'<div class="cd-label">{label}</div>'
        f'<div class="cd-remaining muted" id="cd-rem-{bid}" '
        f'data-deadline="{deadline}">{e(STRINGS["computing"])}</div>'
        f'<button onclick="countdownDone(\'{bid}\')">{e(STRINGS["done"])}</button>'
        f'</div>'
    )


def apply(block: dict, event: dict) -> bool:
    if event.get("event") != "countdown_done":
        return False
    block["done"] = True
    return True


def needs_user(block: dict) -> list:
    if not block.get("done"):
        return [(block.get("id", ""), block.get("label") or STRINGS["pending_label"])]
    return []


SILENT_EVENTS: set = set()

# The clock lives entirely client-side (see module docstring). The overdue
# label is hardcoded here (US English, matching the translated UI) rather than
# read from STRINGS -- the JS constant is inlined into the page once and can't
# import Python. The interval only starts when a countdown is actually on the
# page, so boards without one pay nothing.
JS = """
function countdownFmt(ms) {
  const totalMin = Math.floor(ms / 60000);
  const days = Math.floor(totalMin / 1440);
  const hours = Math.floor((totalMin % 1440) / 60);
  const mins = totalMin % 60;
  const parts = [];
  if (days) parts.push(days + 'd');
  if (days || hours) parts.push(hours + 'h');
  parts.push(mins + 'm');
  return parts.join(' ') + ' left';
}
function countdownTick() {
  const now = Date.now();
  document.querySelectorAll('.cd-remaining[data-deadline]').forEach(function (el) {
    const raw = el.getAttribute('data-deadline');
    const t = Date.parse(raw);
    const card = el.closest('.countdown-card');
    if (isNaN(t)) { el.textContent = ''; return; }
    const ms = t - now;
    if (ms <= 0) {
      el.textContent = 'overdue';
      el.classList.remove('muted');
      if (card) card.classList.add('cd-overdue');
    } else {
      el.textContent = countdownFmt(ms);
      el.classList.add('muted');
      if (card) card.classList.remove('cd-overdue');
    }
  });
}
function countdownDone(id) { send({event:'countdown_done', block:id}).then(reloadSoon); }
if (document.querySelector('.cd-remaining[data-deadline]')) {
  countdownTick();
  setInterval(countdownTick, 30000);
}
"""
