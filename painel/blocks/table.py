"""
Structured data the human can correct (M2, docs/SPEC.md §5.2).

A read-only grid whose `editable` columns become inputs (text) or checkboxes
(`kind: "checkbox"`). A "Confirm table" button sends event `table_confirm
{rows}` with the full current rows back; the block is pending until `confirmed`.
The grid scrolls horizontally inside its own card on overflow.

Export (M3, §24.2): a snapshot has no JS/inputs -- every cell renders as static
text (checkboxes as ☑/☐), including the confirmed state, with no button.
"""
from __future__ import annotations

from .base import e

TYPE = "table"

STRINGS = {
    "heading": "Table",
    "confirm": "Confirm table",
    "confirmed": "Confirmed",
    "pending_label": "Table to confirm",
}


def _columns(block: dict) -> list:
    return block.get("columns", []) or []


def _is_checkbox(col: dict) -> bool:
    return col.get("kind") == "checkbox"


def _cell_text(value) -> str:
    """Read-only display of a cell (checkboxes handled by the caller)."""
    if value is None:
        return ""
    return e(value)


def _static_cell(col: dict, value) -> str:
    if _is_checkbox(col):
        return "☑" if value else "☐"
    return _cell_text(value)


def _static_table(block: dict) -> str:
    cols = _columns(block)
    head = "".join(f"<th>{e(c.get('label', ''))}</th>" for c in cols)
    body_rows = []
    for row in block.get("rows", []):
        cells = "".join(
            f"<td>{_static_cell(c, row.get(c.get('id')))}</td>" for c in cols
        )
        body_rows.append(f"<tr>{cells}</tr>")
    return (
        f'<div class="table-scroll"><table class="data-table">'
        f'<thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody></table></div>'
    )


def render(block: dict, ctx: dict) -> str:
    bid = e(block.get("id", ""))
    title = e(block.get("title", STRINGS["heading"]))
    confirmed = bool(block.get("confirmed"))

    # Export (M3, §24.2) OR already confirmed: fully static grid, no controls.
    if (ctx or {}).get("export") or confirmed:
        card_cls = "card table-card answered" if confirmed else "card table-card"
        tail = f'<div class="answer">{e(STRINGS["confirmed"])}</div>' if confirmed else ""
        return (
            f'<div class="{card_cls}"><h3>{title}</h3>'
            f'{_static_table(block)}{tail}</div>'
        )

    cols = _columns(block)
    editable = set(block.get("editable", []) or [])
    head = "".join(f"<th>{e(c.get('label', ''))}</th>" for c in cols)
    body_rows = []
    for row in block.get("rows", []):
        cells = []
        for c in cols:
            cid = c.get("id")
            cid_e = e(cid)
            value = row.get(cid)
            if cid in editable:
                if _is_checkbox(c):
                    checked = "checked" if value else ""
                    cells.append(
                        f'<td data-col="{cid_e}">'
                        f'<input type="checkbox" data-col="{cid_e}" {checked}></td>'
                    )
                else:
                    val = e(value if value is not None else "")
                    cells.append(
                        f'<td data-col="{cid_e}">'
                        f'<input type="text" data-col="{cid_e}" value="{val}" '
                        f'data-orig="{val}"></td>'
                    )
            else:
                # Read-only: the raw value rides in data-val so tableConfirm can
                # send FULL rows back, not just the edited columns.
                cells.append(
                    f'<td data-col="{cid_e}" data-val="{e(value if value is not None else "")}">'
                    f'{_static_cell(c, value)}</td>'
                )
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    grid = (
        f'<div class="table-scroll"><table class="data-table" id="tbl-{bid}">'
        f'<thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody></table></div>'
    )
    return (
        f'<div class="card table-card"><h3>{title}</h3>{grid}'
        f'<button onclick="tableConfirm(\'{bid}\')">{e(STRINGS["confirm"])}</button></div>'
    )


def apply(block: dict, event: dict) -> bool:
    if event.get("event") != "table_confirm":
        return False
    rows = event.get("rows")
    if isinstance(rows, list):
        block["rows"] = rows
    block["confirmed"] = True
    return True


def needs_user(block: dict) -> list:
    if not block.get("confirmed"):
        return [(block.get("id", ""), block.get("title") or STRINGS["pending_label"])]
    return []


SILENT_EVENTS: set = set()

JS = """
function tableConfirm(id) {
  const tbl = document.getElementById('tbl-' + id);
  if (!tbl) return;
  const rows = [];
  tbl.querySelectorAll('tbody tr').forEach(function (tr) {
    const row = {};
    tr.querySelectorAll('td[data-col]').forEach(function (td) {
      const col = td.getAttribute('data-col');
      const inp = td.querySelector('input');
      if (inp) {
        row[col] = (inp.type === 'checkbox') ? inp.checked : inp.value;
      } else {
        row[col] = td.getAttribute('data-val');
      }
    });
    rows.push(row);
  });
  send({event:'table_confirm', block:id, rows:rows}).then(reloadSoon);
}
"""
