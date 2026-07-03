# pAInel with Aider

Aider doesn't have a skills system either, but it will happily keep a
markdown file in context across the whole session if you tell it to. That's
enough to teach it the pAInel workflow.

## 1. Install pAInel

```bash
pip install -e /path/to/painel   # or: pipx install /path/to/painel
```

See the main [README](../README.md#installing) for the isolated-venv route if
`pip install` is blocked by PEP 668 on your system Python.

## 2. Add a conventions file

Create `CONVENTIONS.md` in your repo root (or add to an existing one):

```markdown
## Second interface: pAInel

For any non-trivial, multi-step task, keep a live dashboard next to the chat
with pAInel instead of only talking in chat.

1. Write `.painel-board.json` — `title`, `meta.project`, and a `blocks` array.
   Start with `heading` + `markdown` (goal) + a `tasks` block for your own
   progress. Add interactive blocks when the user needs to do or decide
   something: `checklist` (manual steps), `question`, `choice`, `approval`,
   `form`, or `plan` (steps with play/edit/skip/reorder and a per-step
   discussion thread). Run `painel demo` to see every block type rendered.
2. Run `painel open` in the project directory. Idempotent — creates the board
   if missing, starts a local server on a free port, opens the browser; safe
   to call again, it just reopens the tab.
3. To see what the user did, read the tail of `.painel-board.json.log` (one
   JSON line per interaction: `check`, `answer`, `choose`, `approve`,
   `plan_play`, `plan_comment`, etc.).
4. React: do what the event unblocks, then edit `.painel-board.json` directly
   (mark tasks done, reply to a `plan_comment` thread by appending
   `{"from": "agent", "text": "..."}`, add next steps) and save — the page
   polls and reloads on its own, never while the user is typing.
5. `painel stop` when done. Leave the board as the session record.
```

Tell aider to always load it:

```bash
aider --read CONVENTIONS.md
```

or add it permanently in `.aider.conf.yml`:

```yaml
read:
  - CONVENTIONS.md
```

## 3. Checking the board without a background-task tool

Aider's chat loop is turn-based — there's no equivalent of Claude Code's
`Monitor` that pushes a notification the moment a new log line appears. Two
practical patterns:

**A — check on your next turn.** Just ask aider to "check the pAInel board"
and it re-reads the log tail. Fine for anything where you're going back and
forth anyway.

**B — block on a specific answer.** Have aider run a bounded blocking read as
a shell command when you're waiting on exactly one response:

```bash
timeout 300 tail -n0 -f .painel-board.json.log | grep -m1 '^{'
```

Returns the instant the next event lands (or times out after 5 minutes) —
aider reads that one line instead of re-scanning the whole file.

## 4. Minimal example board

```json
{
  "title": "Add rate limiting",
  "meta": {"project": "api-gateway"},
  "blocks": [
    {"id": "h1", "type": "heading", "text": "Goal"},
    {"id": "m1", "type": "markdown", "text": "Add per-key rate limiting to the gateway."},
    {"id": "q1", "type": "question", "prompt": "What's the default limit — requests per minute?", "answer": null},
    {"id": "pl", "type": "plan", "title": "Plan", "items": [
      {"id": "p1", "text": "Add token-bucket middleware", "status": "pending"},
      {"id": "p2", "text": "Wire up per-key config", "status": "pending"}
    ]}
  ]
}
```

Run `painel open`, answer the question or hit ▶ on a plan step, and check
`.painel-board.json.log` for the event.
