# pAInel — Development Specification (v1)

**Audience:** an AI coding agent (or human) implementing pAInel features
without prior context. This document is self-contained: read it top to bottom
and you can start working. When it conflicts with code comments, this spec
wins; when it conflicts with `docs/PROTOCOL.md` (future), the protocol wins.

---

## 0. Product thesis (why every decision below looks the way it does)

pAInel is a **second interface for AI agents**: the agent composes a local
web dashboard out of **typed blocks** (plan, approval, checklist, question…)
and reacts to the human's clicks. The end user may be non-technical — a
lawyer, an accountant, a manager. The agent picks which blocks appear; the
blocks are a **grammar of human↔agent interactions**, not features.

**The core bet: the block catalog will grow a lot.** Having *the right block
for each need* is how the product fits each user. Therefore the #1
architectural requirement is: **adding a new block type must be trivial,
safe, and self-contained** — one file, one registry entry, no edits to the
HTTP layer, no risk to existing blocks.

Non-negotiable constraints:

1. **Python stdlib only.** No pip dependencies, ever, in the core.
2. **One artifact of state:** `board.json`. Human-readable, agent-editable.
3. **Events out via stdout** (JSONL) and via `<board>.log`. The agent listens
   there; pAInel never calls the agent.
4. **Never interrupt the human typing.** All refresh logic must respect the
   `isBusy()` contract (§6.4).
5. **Graceful degradation:** unknown block types render a visible fallback,
   never crash.

---

## 1. Current state (baseline you inherit)

- `painel/server.py` (~650 lines): monolithic — HTTP handler, HTML/CSS/JS
  template, per-block render functions, event application.
- `painel/__main__.py`: CLI — `open` (idempotent start+browser), `stop`,
  `status`, `serve`, `init`, `demo`.
- 10 block types implemented (§5), including `plan` with play/edit/skip/
  reorder/threads and an "attention bar" (§6.2).
- Distribution: installed via venv + symlink; PyPI pending.
- Tests: none committed yet (ad-hoc so far). You will add them (§8).

Known conventions already in the code that you must preserve:

- All user content is HTML-escaped with `e()`. **When embedding JSON in an
  HTML attribute, always `e(json.dumps(x))`** — a real bug shipped because a
  raw `"` closed the `onclick` attribute early.
- Textareas/inputs carry `data-orig` with their original value so `isBusy()`
  can detect unsent edits.
- Open plan-threads persist across reloads via `sessionStorage`
  (`openThreads` key).
- `plan_seen` events update state but are **not** written to stdout (UI
  housekeeping must not wake the agent).

---

## 2. Target architecture (Milestone M1 is getting here)

```
painel/
  __main__.py          # CLI (unchanged behavior)
  server.py            # HTTP + event dispatch + page shell ONLY
  page.py              # _PAGE template, global CSS, global JS
  blocks/
    __init__.py        # REGISTRY: {type: module}; auto-imports siblings
    base.py            # helpers: e(), md_inline(), shared field rendering
    _template.py       # copy-me skeleton for new blocks (not registered)
    heading.py  markdown.py  note.py  tasks.py  plan.py  checklist.py
    question.py  choice.py  approval.py  form.py  log.py
```

### 2.1 Block module contract

Every block module defines (only `TYPE` and `render` are mandatory):

```python
TYPE = "question"                     # unique, snake_case, stable forever

def render(block: dict, ctx: dict) -> str:
    """Return the block's HTML. ctx = {"index": int, "total": int}.
    Must escape ALL user content with e(). Must not raise on missing
    fields — use .get() with sensible defaults."""

def apply(block: dict, event: dict) -> bool:
    """Mutate `block` in place for an event addressed to it.
    Return True if the event is recognized (even if it changed nothing),
    False if this module doesn't handle that event name."""

def needs_user(block: dict) -> list[str]:
    """Labels (PT) for everything in this block currently waiting on the
    human. Empty list = nothing pending. Drives the attention bar."""

SILENT_EVENTS: set[str] = set()
    """Event names that must NOT be emitted to stdout (UI housekeeping)."""

JS: str = ""
    """Optional JS functions this block needs, appended once to the page.
    Plain string, no f-string braces issues — page.py joins them."""
```

`blocks/__init__.py` builds `REGISTRY` by importing every sibling module
that has a `TYPE` attribute. Dispatch rules in `server.py`:

- **Render:** `REGISTRY[type].render(block, ctx)`; unknown type → fallback
  card `bloco desconhecido: <type>` (keep current behavior).
- **Events:** find the target block by `event["block"]` id, call its
  `apply()`. If the module returns False or block not found, still 200 —
  log to stderr, never crash the server.
- **Attention:** concatenate `needs_user()` across all blocks, in board
  order, as `(block_id, label)` pairs.
- **stdout emission:** skip if event name ∈ that module's `SILENT_EVENTS`.

### 2.2 What must NOT change in M1

The refactor is **behavior-preserving**. Golden test (§8.1) pins the HTML
before/after. CLI, endpoints, board.json format, event names: untouched.

---

## 3. Wire protocol (freeze as v1)

### 3.1 board.json

```jsonc
{
  "protocol": 1,               // ADD in M1. Absent == 1.
  "title": "string",
  "meta": {                    // all optional
    "project": "string",
    "updated_at": "string"     // agent-maintained, free format
  },
  "blocks": [ { "id": "b1", "type": "question", ... }, ... ]
}
```

- `id` unique within the board; required on interactive blocks.
- Order of `blocks` == render order. No nesting in v1.
- **Compatibility rules:** new fields are always additive and optional;
  a renderer must tolerate unknown fields; removing/renaming a field or
  changing its type requires bumping `protocol` (avoid; we intend v1 to
  last).

### 3.2 HTTP endpoints (localhost only, bind 127.0.0.1)

| Method | Path | Behavior |
|---|---|---|
| GET | `/` | Render full page from board.json |
| GET | `/version` | `{"v": <mtime float>}` — poller uses it |
| POST | `/event` | Apply JSON body, persist board, emit JSONL |

### 3.3 Events (JSONL, one per line on stdout and `<board>.log`)

Envelope: `{"event": "<name>", "block": "<block id>", ...payload}`.
Current catalog:

| event | payload | emitted to agent? |
|---|---|---|
| `check` | `item`, `checked: bool` | yes |
| `answer` | `value: str` | yes |
| `choose` | `value: str` | yes |
| `approve` | `decision: "approved"\|"rejected"`, `comment: str` | yes |
| `submit` | `values: {field_id: value}` | yes |
| `plan_play` / `plan_skip` | `item` | yes |
| `plan_move` | `item`, `direction: "up"\|"down"` | yes |
| `plan_edit` | `item`, `value` | yes |
| `plan_comment` | `item`, `value` | yes |
| `plan_seen` | `item` | **no** (silent) |

New blocks add events under their own prefix (`<type>_<verb>`), declared in
the module. Never reuse another block's event names.

---

## 4. UX invariants (apply to every block, present and future)

1. **Answered ≠ deleted.** When an interactive block is resolved, render it
   dimmed (`.answered`) with the outcome visible ("Resposta: …",
   "Escolhido: …"). The board is also the session record.
2. **Attention is derived, never manual.** A block "waits on the human" via
   `needs_user()` only. The sticky yellow bar shows count + anchor links.
   New reply/change indicators use a **seen-counter** pattern
   (`seen: int` = items seen; unread = length > seen), cleared by a silent
   event when the user views it.
3. **Reload discipline.** The page reloads only when `/version` changes AND
   `!isBusy()`. Any block with client-side open/closed state must persist it
   in `sessionStorage` so reloads don't slam it shut.
4. **PT-PT strings** in the UI for now; collect every literal in one place
   per module to ease future i18n (constant `STRINGS` dict at module top).
5. **Dark + light** via the existing CSS custom properties; blocks use the
   variables (`--accent`, `--ok`, `--wip`, `--blocked`, `--border`,
   `--muted`), never hardcoded colors.
6. **Everything keyboard-reachable**; buttons get `title=` tooltips.

---

## 5. Block catalog

### 5.1 Implemented (v1.0) — behavior must be preserved

| type | purpose | key fields | events |
|---|---|---|---|
| `heading` | section title | `text` | — |
| `markdown` | rich text (inline md: bold/italic/code/links) | `text` | — |
| `note` | callout | `text`, `tone: info\|ok\|warn\|danger` | — |
| `tasks` | agent progress, read-only | `title`, `items[{text,status: done\|wip\|pending\|blocked}]` | — |
| `plan` | steerable plan | `title`, `items[{id,text,status(+skipped),thread[],seen}]` | plan_* |
| `checklist` | human manual steps | `title`, `items[{id,text,checked}]` | check |
| `question` | free-text ask | `prompt`, `answer` | answer |
| `choice` | pick one | `prompt`, `options[]`, `selected` | choose |
| `approval` | authorize | `prompt`, `decision`, `comment` | approve |
| `form` | multi-field input | `prompt`, `fields[{id,label,kind: text\|number\|date\|email\|select\|textarea,options?,value}]`, `submitted` | submit |
| `log` | timeline/decisions | `title`, `entries[{ts,text}]` | — |

### 5.2 Batch 1 — implement in M2 (in this order)

Each is one module + registry entry + tests. Full field spec here so no
design decisions are needed at build time.

**`countdown`** — deadline pressure for human steps.
```jsonc
{ "id":"cd1","type":"countdown","label":"Submeter IES até",
  "deadline":"2026-07-15T17:00:00","done":false }
```
Render: label + live JS countdown (days/h/m). Past deadline → red, label
"em atraso". `needs_user`: pending if not `done` (label: the block label).
Event `countdown_done {}` when user clicks "Feito".

**`file_drop`** — hand a file to the agent.
```jsonc
{ "id":"f1","type":"file_drop","prompt":"Anexa o extrato de junho (PDF)",
  "accept":".pdf,.csv","dest_dir":"./painel-uploads","files":[] }
```
Render: drag&drop zone + file input. Upload via `POST /upload?block=<id>`
(multipart; **add this endpoint in server.py as part of this block's work**,
max 25 MB, filename sanitized to `[A-Za-z0-9._-]`, saved under `dest_dir`,
path appended to `files[]`). Event `file_added {name, path, size}`.
`needs_user`: pending while `files` empty. Answered-style once ≥1 file.

**`rating`** — quick calibrated feedback.
```jsonc
{ "id":"r1","type":"rating","prompt":"Quão adequado ficou o tom do email?",
  "scale":5,"value":null,"labels":["péssimo","excelente"] }
```
Stars 1..scale (max 10). Event `rate {value:int}`. Pending until `value`.

**`table`** — structured data the human can correct.
```jsonc
{ "id":"t1","type":"table","title":"Lançamentos suspeitos",
  "columns":[{"id":"date","label":"Data"},{"id":"desc","label":"Descrição"},
             {"id":"ok","label":"Confirmar?","kind":"checkbox"}],
  "rows":[{"date":"2026-06-03","desc":"FX fee","ok":false}],
  "editable":["ok"],"confirmed":false }
```
Read-only cells as text; `editable` columns render inputs/checkboxes.
"Confirmar tabela" button → event `table_confirm {rows}` (full rows back).
Pending until `confirmed`. Horizontal scroll inside the card on overflow.

**`links`** — curated resources/outputs.
```jsonc
{ "id":"l1","type":"links","title":"Documentos gerados",
  "items":[{"label":"Minuta v2 (PDF)","url":"file:///…","kind":"file"},
           {"label":"Portal AT","url":"https://…","kind":"external"}] }
```
Render as list with kind icon. No events, never pending. `target=_blank`.

**`gauge`** — one number that matters.
```jsonc
{ "id":"g1","type":"gauge","label":"Orçamento usado","value":7350,
  "max":10000,"unit":"€","warn_at":0.8 }
```
Bar + big number. ≥ `warn_at`·max → warning color. Read-only.

### 5.3 Batch 2 — specified later, reserved names now

`diff` (before/after approval), `signature` (draw-to-sign),
`image_annotate`, `date_pick`, `multi_choice`, `evidence`
(photo/screenshot proof for a checklist step), `timer` (agent-set reminder),
`chart` (simple SVG series). **Do not implement without a spec section.**
Reserved = the names may not be used for anything else.

### 5.4 How to add a block (the recipe a simple model follows)

1. Copy `blocks/_template.py` → `blocks/<type>.py`; fill `TYPE`, `STRINGS`.
2. Write `render()` — every user string through `e()`; JSON-in-attribute
   through `e(json.dumps(…))`; colors via CSS vars only.
3. Write `apply()` for your events; add UI-housekeeping names to
   `SILENT_EVENTS`.
4. Write `needs_user()` — think "what would the yellow bar say?".
5. Add JS (if any) to module `JS` constant; functions namespaced
   `<type>Verb()` e.g. `ratingSet()`.
6. Tests (§8): render-empty, render-filled, apply-each-event,
   needs_user-both-states, escaping test with `"<script>"` in every field.
7. Add one example to `python -m painel demo`'s board.
8. Update the table in §5.1/5.2 and `.claude/skills/painel/SKILL.md`
   (the agent must learn when to reach for the new block).

Definition of done for any block PR: all 8 steps, `python -m painel demo`
shows it, golden test updated deliberately (never accidentally).

---

## 6. Page shell details (for page.py extraction)

### 6.1 Layout
Max-width 780px, centered; sticky attention bar above the header when
pending items exist; footer brand. Cards: existing `.card` style.

### 6.2 Attention bar
`_needs_user(board)` → `[(block_id, label)]`. Bar: count chip + labels as
`#blk-<id>` anchor links. Every block is wrapped in `<div id="blk-<id>">`.

### 6.3 Polling
2s interval; `GET /version`; reload iff version changed and `!isBusy()`.

### 6.4 isBusy() contract
True if: focused element is TEXTAREA/INPUT/SELECT, **or** any
textarea/input's `value !== data-orig`. Every new block with inputs must set
`data-orig` on render.

---

## 7. CLI (unchanged surface, document only)

`painel open [board] [--port N]` idempotent (pidfile `<board>.pid`,
log `<board>.log`) · `stop` · `status` · `serve` (foreground) · `init` ·
`demo`. Default board `.painel-board.json`. Auto port from 8765.

---

## 8. Testing (new — part of M1)

Framework: `unittest` (stdlib only). Layout: `tests/test_blocks.py`,
`tests/test_server.py`, `tests/test_golden.py`.

1. **Golden page test:** render the demo board, compare against
   `tests/golden/demo.html`. Update file only via
   `python -m tests.regen_golden` (script prints a diff and asks nothing —
   the diff appearing in the PR is the review).
2. **Per-block tests** as in §5.4 step 6.
3. **Event dispatch tests:** unknown event → 200 + no mutation; event to
   missing block id → 200 + no crash; `plan_seen` absent from stdout capture.
4. **Escaping regression:** a board where every string field is
   `'"<script>alert(1)</script>'` renders with zero raw `<script` in output.
5. CI: single GitHub Action, `python -m unittest discover`, py3.10–3.14.

---

## 9. Milestones for the implementing model

| # | Deliverable | Acceptance |
|---|---|---|
| **M1** | Refactor to `blocks/` registry + `page.py`; add `"protocol": 1`; test suite + CI | Golden HTML identical (modulo the protocol field); all §8 tests green; `painel demo` unchanged to the eye |
| **M2** | Batch-1 blocks: countdown, file_drop, rating, table, links, gauge (+ `/upload`) | Each passes §5.4 DoD; demo board shows all six; skill updated |
| **M3** | Board export: `GET /export` → single-file HTML report (inline CSS, no JS, print-friendly); "Exportar" link in footer | Opens standalone in a browser from disk; includes answered states + threads + log |
| **M4** | PyPI release `painel` 0.2.0 (`pipx install painel`) | Fresh machine: `pipx install painel && painel demo` works |

Work strictly in milestone order. One PR per milestone; M2 may be one PR
per block. Conventional commit messages. Ask nothing that this spec already
answers; where the spec is silent on cosmetics, match existing style.
