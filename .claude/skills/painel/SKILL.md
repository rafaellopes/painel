---
name: painel
description: >
  Show a live, clickable dashboard (pAInel) next to the chat for any non-trivial,
  multi-step task. Use it to give the human checkboxes for manual steps, ask
  questions with answer boxes, request approvals, and show live progress — instead
  of burying everything in scrolling chat. Trigger when the work has several steps,
  requires the user to do something by hand, or when the user asks for a plan,
  dashboard, checklist, or "second interface".
---

# pAInel — the second interface

pAInel renders a `board.json` as an interactive web page next to the chat. You
compose typed blocks; the human clicks/types; each interaction is written back to
the board **and** printed as one JSON line on stdout, which you watch to react.

Use it for any non-trivial, multi-step task — **especially** when the user must
do something manually (log in somewhere, download a file, confirm a payment).
Don't use it for one-shot answers or quick chats.

## Setup (once per task)

1. **Write** a `board.json` in the working directory (see schema below). Start
   with a heading, a markdown goal, a `tasks` block for your own progress, and —
   if you need the user to do or decide anything — the relevant interactive
   blocks.

2. **Serve** it in the background and open it:
   ```bash
   python3 -m painel serve board.json --port 8765 --open
   ```
   (If `painel` isn't installed as a package, run the server file directly:
   `python3 /path/to/painel/painel/server.py`… — or vendor the single
   `server.py` into the project.)

3. **Watch** the server's stdout for interactions. In Claude Code, attach a
   background monitor to the serve command's output file, filtering to JSON
   lines (they start with `{`). Each line is one interaction event.

## React to events

Events look like:
```json
{"event":"check",   "block":"cl", "item":"c1", "checked":true}
{"event":"answer",  "block":"q1", "value":"..."}
{"event":"choose",  "block":"ch", "value":"PDF"}
{"event":"approve", "block":"ap", "decision":"approved", "comment":"..."}
{"event":"submit",  "block":"fm", "values":{"nome":"Ana"}}
```

When an event arrives:
- Do the thing it unblocks (continue the pipeline, use the answer, honor the
  decision).
- **Update `board.json`** to reflect new state: flip task statuses, add a `log`
  entry, add the next question, append next steps. The page auto-refreshes when
  the file changes (and never while the user is mid-typing).

Keep the board as the single source of truth for "where are we". The user should
be able to glance at it and know the plan, the progress, and what's waiting on
them — without re-reading the chat.

## Board schema

```json
{
  "title": "Session title",
  "meta": { "project": "name", "updated_at": "2026-07-02 21:00" },
  "blocks": [ /* ordered, each with a unique "id" and a "type" */ ]
}
```

Block types:

- `heading` — `{ "type":"heading", "text":"..." }`
- `markdown` — `{ "type":"markdown", "text":"supports **bold**, \`code\`, line breaks" }`
- `note` — `{ "type":"note", "tone":"info|ok|warn|danger", "text":"..." }`
- `tasks` — your progress. `{ "type":"tasks", "title":"...", "items":[{"text":"...","status":"done|wip|pending|blocked"}] }`
- `checklist` — the user's manual steps. `{ "type":"checklist", "title":"...", "items":[{"id":"c1","text":"...","checked":false}] }`
- `question` — `{ "type":"question", "prompt":"...", "answer":null }`
- `choice` — `{ "type":"choice", "prompt":"...", "options":["A","B"], "selected":null }`
- `approval` — `{ "type":"approval", "prompt":"...", "decision":null }`
- `form` — `{ "type":"form", "prompt":"...", "fields":[{"id":"f1","label":"...","kind":"text|number|date|email|textarea|select","options":[...],"value":""}], "submitted":false }`
- `log` — `{ "type":"log", "title":"...", "entries":[{"ts":"HH:MM","text":"..."}] }`

## Rules of thumb

- Every interactive block needs a stable, unique `id` — you match events by it.
- Prefer a `checklist` over asking the user to type "done" in chat.
- Prefer `choice`/`approval` over open questions when the options are known.
- After every meaningful step, update the board — stale boards defeat the point.
- Leave the board in its final state at the end; it's the session's record.
