# pAInel with Cursor

Cursor doesn't have Claude Code's skill system, but it does read a persistent
rules file on every request. That's enough to teach it the same workflow.

## 1. Install pAInel

```bash
pip install -e /path/to/painel   # or: pipx install /path/to/painel
```

See the main [README](../README.md#installing) if `pip install` is blocked by
your system Python (Homebrew/PEP 668) — use an isolated venv + symlink instead.

## 2. Add a project rule

Create `.cursor/rules/painel.mdc` in your repo (Cursor picks up every `.mdc`
file under `.cursor/rules/` automatically):

```markdown
---
description: Use pAInel as a second interface for multi-step tasks
alwaysApply: true
---

For any non-trivial, multi-step task (implementation with several steps, a
plan with phases, anything where the user needs to do something manually or
answer questions along the way), keep a live dashboard next to the chat using
pAInel instead of burying everything in chat text.

Workflow:
1. Write `.painel-board.json` in the project root — a `title`, a `meta.project`,
   and a `blocks` array. Start with a `heading`, a `markdown` block for the goal,
   a `tasks` block for your own progress, and any interactive blocks the user
   needs: `checklist` (manual steps), `question`, `choice`, `approval`, `form`,
   `plan` (steps with play/edit/skip/reorder + a discussion thread per step).
   Full schema: run `painel demo` to see every block type live.
2. Run `painel open` in the project directory — creates the board if missing,
   starts a local server on a free port, opens the browser. Safe to call again
   (idempotent) — it just reopens the tab if already running.
3. Watch for interactions: `painel open` logs to `.painel-board.json.log` in
   the project. Tail that file for lines starting with `{` — each one is a
   JSON event (`check`, `answer`, `choose`, `approve`, `submit`, `plan_play`,
   `plan_comment`, etc.) describing what the user just did.
4. React to each event: do what it unblocks, then edit `.painel-board.json`
   directly (mark tasks done, answer a `plan_comment` thread by appending a
   `{"from": "agent", "text": "..."}` entry, add next steps) and save. The page
   polls and reloads on its own — never while the user is actively typing.
5. When done, run `painel stop`. Leave the board file as the session record.
```

## 3. Watching the log without a background-task tool

Cursor's agent loop doesn't have Claude Code's `Monitor`/background-task
primitive, so it can't get pushed a notification when a new line appears.
Two practical options:

**A — poll explicitly.** After starting the board, the agent just re-reads
the tail of `.painel-board.json.log` each time it's given control again (e.g.
after a user message, or in an explicit "check the board" step). This is the
simplest option and works fine for turn-based interaction.

**B — block on it.** For a step where you're waiting on one specific answer,
run a short blocking wait as a tool call:

```bash
timeout 300 tail -n0 -f .painel-board.json.log | grep -m1 '^{'
```

This returns as soon as the next event arrives (or after 5 minutes), and the
agent can read the returned line directly instead of re-parsing the whole log.

## 4. Minimal example board

```json
{
  "title": "Migrate billing to Stripe",
  "meta": {"project": "billing-service"},
  "blocks": [
    {"id": "h1", "type": "heading", "text": "Goal"},
    {"id": "m1", "type": "markdown", "text": "Move billing off the old provider."},
    {"id": "cl", "type": "checklist", "title": "Do this manually", "items": [
      {"id": "c1", "text": "Rotate the Stripe API key in the dashboard", "checked": false}
    ]},
    {"id": "pl", "type": "plan", "title": "Plan", "items": [
      {"id": "p1", "text": "Add Stripe client", "status": "pending"},
      {"id": "p2", "text": "Migrate webhook handlers", "status": "pending"}
    ]}
  ]
}
```

Run `painel open`, tick the checkbox or hit ▶ on a plan step, and watch
`.painel-board.json.log` for the event.
