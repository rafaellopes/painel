"""
Command-line entry point for pAInel.

Shaped around ONE service serving every registered project (M13,
docs/SPEC.md §17.5), not one process per board:

    python -m painel open    [dir]                # the one command people actually type
    python -m painel add     [dir]                # register without opening
    python -m painel remove  <slug>               # unregister (never deletes the board)
    python -m painel lint    [dir]                # flag checklist items that need an answer, not a tick
    python -m painel status                       # is the service up, where, how many projects
    python -m painel stop                         # stop the service
    python -m painel restart-all                  # restart the service (run after upgrading)
    python -m painel service [--port 8765]        # the service, foreground
    python -m painel serve   <board.json> [--port 8765] [--open]   # ONE board, foreground
    python -m painel init    <board.json>         # write a starter board
    python -m painel demo                         # serve a showcase board
"""
import argparse
import errno
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

from . import lint, registry
from .server import serve, serve_service, save_board, load_board

DEFAULT_BOARD = ".painel-board.json"
# 8765 is the address now, not just a starting point to scan from: it goes in
# every bookmark. If it's taken by a foreign service we fail loudly and
# suggest --port -- we never wander to another port (§17.5).
SERVICE_PORT = 8765
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1", ""}
EXPOSE_ACK_FLAG = "--i-know-this-is-exposed"

STARTER = {
    "title": "pAInel",
    "meta": {"project": os.path.basename(os.getcwd())},
    "blocks": [
        {"id": "h1", "type": "heading", "text": "Goal"},
        {"id": "m1", "type": "markdown", "text": "Describe the session goal here."},
        {"id": "h2", "type": "heading", "text": "Progress"},
        {"id": "tk", "type": "tasks", "title": "Agent tasks", "items": [
            {"text": "First task", "status": "wip"},
        ]},
    ],
}


def _starter(board_path: str) -> dict:
    """STARTER, but with meta.project named after the board's OWN directory
    rather than the shell's cwd. `painel open <dir>` (M13, §17.5) can create a
    board somewhere other than where you're standing, and meta.project is what
    the slug derives from (§17.3) -- naming it after the cwd would give the
    project a URL borrowed from an unrelated directory."""
    board = json.loads(json.dumps(STARTER))  # deep copy; STARTER is module-level
    board["meta"]["project"] = os.path.basename(os.path.dirname(os.path.abspath(board_path)))
    return board


def _demo_board() -> dict:
    # A path that's guaranteed to exist on any machine running `painel demo`
    # (this repo's own README), computed at construction time rather than
    # hardcoded, so the resources block (M11, §15) shows a real freshness
    # string instead of a permanent "not found" warning.
    _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _readme_path = os.path.join(_repo_root, "README.md")
    return {
        "title": "pAInel — demo",
        "meta": {"project": "demo", "agent_status": "working", "phase": "exploring"},
        "blocks": [
            {"id": "h1", "type": "heading", "text": "What it is"},
            {"id": "m1", "type": "markdown",
             "text": "**pAInel** is your agent's second interface. "
                     "Each block below is a different `type` of interaction."},
            {"id": "note", "type": "note", "tone": "info",
             "text": "Check a box or answer a question — the agent is notified instantly."},
            {"id": "h2", "type": "heading", "text": "Manual steps (yours)"},
            {"id": "cl", "type": "checklist", "title": "Do this and check it off", "items": [
                {"id": "c1", "text": "Log in to portal X", "checked": False},
                {"id": "c2", "text": "Download the report **PDF**", "checked": False},
                {"id": "c3", "text": "Put the file in `~/Downloads`", "checked": False},
            ]},
            {"id": "h2b", "type": "heading", "text": "A plan you steer, not just read"},
            {"id": "pl", "type": "plan", "title": "Plan", "items": [
                {"id": "p1", "text": "Read configuration", "status": "done"},
                {"id": "p2", "text": "Process file", "status": "wip"},
                {"id": "p3", "text": "Generate report", "status": "pending"},
                {"id": "p4", "text": "Send by email", "status": "pending"},
            ]},
            {"id": "h3", "type": "heading", "text": "Agent progress"},
            {"id": "tk", "type": "tasks", "title": "Pipeline", "items": [
                {"text": "Read configuration", "status": "done"},
                {"text": "Process file", "status": "wip"},
                {"text": "Generate report", "status": "pending"},
                {"text": "Send by email", "status": "blocked"},
            ]},
            {"id": "h4", "type": "heading", "text": "Questions & decisions"},
            {"id": "q1", "type": "question", "prompt": "Which email should the report go to?", "answer": None},
            {"id": "ch", "type": "choice", "prompt": "Report format?",
             "options": ["PDF", "Excel", "Both"], "selected": None},
            {"id": "ap", "type": "approval",
             "prompt": "Can I send the email now?", "decision": None},
            {"id": "fm", "type": "form", "prompt": "Client details:", "fields": [
                {"id": "nome", "label": "Name", "kind": "text", "value": ""},
                {"id": "plano", "label": "Plan", "kind": "select",
                 "options": ["Basic", "Pro"], "value": ""},
            ], "submitted": False},
            {"id": "lg", "type": "log", "title": "Log", "entries": [
                {"ts": "10:00", "text": "Session started"},
            ]},
            {"id": "h5", "type": "heading", "text": "Free conversation"},
            {"id": "chat", "type": "chat", "title": "Conversation", "messages": [
                {"from": "user", "text": "Why did you choose this approach?"},
                {"from": "agent", "text": "Because **X** avoids Y — see the decision in Log."},
            ]},
            {"id": "h6", "type": "heading", "text": "Documents & mockups (always up to date)"},
            {"id": "res1", "type": "resources", "title": "Documents & mockups", "items": [
                {"label": "Project README", "kind": "file", "path": _readme_path},
                {"label": "Deliverables folder (example)", "kind": "folder", "path": _repo_root},
                {"label": "Figma prototype (example)", "kind": "url", "url": "https://figma.com/file/example"},
            ]},
            {"id": "h7", "type": "heading", "text": "Hand me files (drag and drop)"},
            # files[] stays empty so nothing machine-specific (a real uploaded
            # path/size) ever leaks into the committed golden (§ golden note).
            {"id": "up1", "type": "upload",
             "prompt": "Drag your screenshots here (.png, .jpg)",
             "accept": ".png,.jpg,.jpeg,.gif,.webp",
             "dest_dir": "docs/screenshots", "multiple": True, "directory": False,
             "files": []},
            {"id": "h8", "type": "heading", "text": "Adaptive layout (M17)"},
            # hero (§21.2): the one lead takeaway, rendered visually dominant.
            {"id": "hero1", "type": "markdown", "hero": True,
             "text": "**Verdict:** the board can now compose typed blocks — "
                     "side-by-side, a lead, and fold-away detail — without any free-form HTML."},
            # group with columns (§21.1): genuinely parallel content, side by
            # side, wrapping to a stack on a narrow screen.
            {"id": "g1", "type": "group", "layout": "columns",
             "title": "Evidence vs mechanism", "blocks": [
                 {"id": "gcol1", "type": "note", "tone": "info",
                  "text": "**Evidence:** two independent traces point at the same window."},
                 {"id": "gcol2", "type": "note", "tone": "ok",
                  "text": "**Mechanism:** a retry storm, not the carrier — reproduced locally."},
             ]},
            # collapsed (§21.3): long reference prose the human rarely needs open.
            {"id": "col1", "type": "note", "tone": "info", "collapsed": True,
             "title": "Full reference notes (click to expand)",
             "text": "Long-form detail lives here, folded away by default so the "
                     "board stays scannable — expand it only when you need it."},
            {"id": "h9", "type": "heading", "text": "A picture beside the text (M18)"},
            # image (§22): a figure next to the text that reads it. An inline
            # `data:` SVG keeps the demo self-contained (no binary in the repo)
            # and shows the composition M18 unlocks -- image + note side by side.
            {"id": "g2", "type": "group", "layout": "columns",
             "title": "Figure + reading", "blocks": [
                 {"id": "img1", "type": "image",
                  "src": "data:image/svg+xml;utf8,"
                         "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 120'>"
                         "<circle cx='60' cy='60' r='52' fill='none' stroke='%237dd3fc' stroke-width='6'/>"
                         "<path d='M60 18 V60 L88 74' fill='none' stroke='%237dd3fc' stroke-width='6' "
                         "stroke-linecap='round'/></svg>",
                  "alt": "A clock face at ten past two",
                  "caption": "Inline **data:** SVG — no file, no fetch.",
                  "max_width": "220px"},
                 {"id": "img1txt", "type": "markdown",
                  "text": "The agent decided the clearest way to explain this was a "
                          "figure beside the text — so it composed a `group` with an "
                          "`image` in one column and this `markdown` in the other."},
             ]},
        ],
        "change_requests": [
            {"id": "cr1", "block": "pl", "text": "add a user-testing phase",
             "status": "open", "ts": "10:05"},
        ],
    }


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return exc.errno == errno.EPERM  # exists but owned by someone else
    return True


def _default_agent_status_if_absent(board: str) -> None:
    """M5 (SPEC.md §10.3): best-effort only -- if the board predates M5 or
    was never touched by an agent, assume nobody is driving it yet. Once an
    agent starts updating meta.agent_status itself, that's authoritative and
    this is never called again for that transition (only fires on absence)."""
    try:
        b = load_board(board)
    except (OSError, ValueError):
        return
    if "agent_status" not in b.setdefault("meta", {}):
        b["meta"]["agent_status"] = "idle"
        save_board(board, b)


def _resolve_board_arg(target: str) -> str:
    """M13 reshaped `open`/`add` to take a DIRECTORY (§17.5), but the author's
    fingers have typed `painel open` (and occasionally a board path) for
    months. Accept both rather than punish the muscle memory: a directory
    means its default board, anything else is taken as the board file itself."""
    if os.path.isdir(target):
        return os.path.join(target, DEFAULT_BOARD)
    return target


def _spawn_service(port: int, host: str = "127.0.0.1") -> int:
    """Launch a detached `painel service` on `port`, logging to
    ~/.painel/service.log. There is exactly ONE of these per machine now --
    the whole point of M13 (§17.1: N processes for N projects, plus the
    machinery to herd them, is gone).

    Note what does NOT happen here: stdout is NOT the agent's event channel
    any more, so this redirect is pure debugging convenience. Each board's
    events are written straight to its own <board>.log by the service itself
    (server.emit_event, §17.2.2)."""
    log_fh = open(registry.service_log_path(), "a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "painel", "service", "--port", str(port), "--host", host],
        stdout=log_fh, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    registry.write_service(proc.pid, port, host)
    return proc.pid


def _is_our_service(port: int) -> bool:
    """Best-effort signature check: is whatever answers on `port` actually the
    pAInel service, or an unrelated app that happens to occupy 8765? (Not
    hypothetical: caught exactly this during dogfooding -- 8765 was already
    held by an unrelated project on the author's machine, which is why §13's
    _is_our_hub existed and why this, its M13 descendant, still does.) A quick
    GET + title match, not a real handshake -- a false negative just means a
    clear error message instead of silently adopting someone else's port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as r:
            body = r.read(4096).decode("utf-8", "ignore")
    except (OSError, urllib.error.URLError, TimeoutError):
        return False
    from .directory import STRINGS as DIR_STRINGS
    return DIR_STRINGS["title"] in body


def _service_running(port: int) -> bool:
    info = registry.read_service()
    if not info or info.get("port") != port:
        return False
    return _pid_alive(info.get("pid", -1)) and not _port_free(port)


def _ensure_service_running(port: int = SERVICE_PORT) -> int | None:
    """Idempotent (§17.2.3: `painel open` in any directory keeps Just
    Working). Returns the port the service is reachable on, or None if it
    could not be started.

    The port is now THE ADDRESS -- it goes in a bookmark that must keep
    working forever -- so a foreign occupant is a hard, explicit failure
    suggesting --port, never a silent wander to 8766 (§17.5)."""
    if _service_running(port):
        return port
    if not _port_free(port):
        if _is_our_service(port):
            # Running, but service.json is stale/missing (e.g. started by hand
            # with `painel service`). Adopt it rather than refuse to use it.
            registry.write_service(-1, port)
            return port
        print(
            f"error: port {port} is already taken by another service, "
            f"so pAInel did not start there. Choose another port with "
            f"'painel open --port <N>' (or free up {port}).",
            file=sys.stderr,
        )
        return None
    _spawn_service(port)
    _wait_until_listening(port)
    return port


def _wait_until_listening(port: int, tries: int = 50) -> None:
    for _ in range(tries):
        if not _port_free(port):
            return
        time.sleep(0.1)


def _wait_until_listening_free(port: int, tries: int = 50) -> None:
    for _ in range(tries):
        if _port_free(port):
            return
        time.sleep(0.1)


def _service_port(explicit: int | None) -> int:
    if explicit:
        return explicit
    info = registry.read_service()
    return (info or {}).get("port") or SERVICE_PORT


def _check_exposure(host: str, ack: bool) -> bool:
    """Exposure safety, fail closed (§17.6). A non-loopback bind makes every
    board on this machine reachable, and boards routinely accumulate secrets
    (the author's own Livrete board holds plaintext passwords for three test
    accounts in a form block, today, on disk). A footgun a typo can trigger is
    a defect -- so this refuses to start rather than warning and continuing."""
    if host in LOOPBACK_HOSTS or ack:
        return True
    print(
        f"error: refused to start on {host} (outside 127.0.0.1).\n"
        f"Boards frequently contain plaintext credentials "
        f"(test passwords, tokens, client data) and pAInel has NO "
        f"authentication at all -- by design (docs/SPEC.md §17.6).\n"
        f"Exposing this on the network hands those credentials to whoever reaches it.\n"
        f"If that's really what you want, repeat with {EXPOSE_ACK_FLAG}.",
        file=sys.stderr,
    )
    return False


def cmd_open(target: str, port: int | None) -> int:
    board = _resolve_board_arg(target)
    if not os.path.exists(board):
        os.makedirs(os.path.dirname(os.path.abspath(board)), exist_ok=True)
        save_board(board, _starter(board))
        print(f"board created: {board}")
    _default_agent_status_if_absent(board)
    slug = registry.register(board)

    chosen = _ensure_service_running(_service_port(port))
    if chosen is None:
        return 1
    url = f"http://localhost:{chosen}/{slug}"
    webbrowser.open(url)
    print(f"pAInel opened: {url}  (all projects: http://localhost:{chosen}/)")
    return 0


def cmd_add(target: str) -> int:
    """Register without opening -- for bulk-adding existing projects (§17.5)."""
    board = _resolve_board_arg(target)
    if not os.path.exists(board):
        print(f"error: no board at {board}", file=sys.stderr)
        return 1
    slug = registry.register(board)
    port = _service_port(None)
    print(f"registered: {slug}  ->  {board}\n   http://localhost:{port}/{slug}")
    return 0


def cmd_lint(target: str) -> int:
    """Compose-time prevention (M16, docs/SPEC.md §20.2 layer 1). Exit 1 when
    anything is flagged, 0 when clean -- so the agent (and CI, and a pre-commit
    hook) can gate on it. The skill instructs the agent to run this after
    composing or updating a board, which is the point where the mistake is
    still free to fix: before the human ever sees the board."""
    board_path = _resolve_board_arg(target)
    if not os.path.exists(board_path):
        print(f"error: no board at {board_path}", file=sys.stderr)
        return 1
    try:
        board = load_board(board_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: could not read {board_path}: {exc}", file=sys.stderr)
        return 1
    findings = lint.lint_board(board)
    if not findings:
        print(f"lint: no issues in {board_path}")
        return 0
    n = len(findings)
    print(f"lint: {n} checklist item{'s' if n > 1 else ''} "
          f"{'look' if n > 1 else 'looks'} like {'they ask' if n > 1 else 'it asks'} "
          f"for an answer instead of a tick ({board_path}):", file=sys.stderr)
    for f in findings:
        print("  " + lint.format_finding(f), file=sys.stderr)
    print("\nChecking one of these off delivers nothing to the agent. Convert them into "
          "'question' blocks (one answer) or 'form' (several fields).", file=sys.stderr)
    return 1


def cmd_remove(slug: str) -> int:
    """Unregister. NEVER deletes the board file (§17.5) -- the board belongs to
    the project, not to us."""
    if registry.unregister(slug):
        print(f"unregistered: {slug}  (the board itself was not deleted)")
        return 0
    print(f"not registered: {slug}", file=sys.stderr)
    return 1


def cmd_stop() -> int:
    info = registry.read_service()
    if not info:
        print("the pAInel service is not running.")
        return 0
    pid = info.get("pid")
    if pid and pid > 0 and _pid_alive(pid):
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    registry.clear_service()
    print("stopped.")
    return 0


def cmd_status() -> int:
    info = registry.read_service()
    n = len(registry.load_projects())
    if info and _service_running(info.get("port", -1)):
        print(f"running at http://localhost:{info['port']}/  "
              f"(pid {info['pid']}, {n} project{'s' if n != 1 else ''} registered)")
    else:
        print(f"stopped.  ({n} project{'s' if n != 1 else ''} registered"
              f" — 'painel open' to start)")
    return 0


def cmd_restart_all() -> int:
    """Restart the service so a freshly-shipped painel version is picked up --
    the author runs this after every upgrade, so the NAME stays even though
    M13 left it far less to do: there is one process now, not one per project
    (§17.5). Same port, so every bookmark survives the restart."""
    info = registry.read_service()
    if not info:
        print("no pAInel running.")
        return 0
    port, pid = info.get("port", SERVICE_PORT), info.get("pid", -1)
    host = info.get("host", "127.0.0.1")
    if pid and pid > 0 and _pid_alive(pid):
        try:
            os.kill(pid, 15)
        except OSError:
            pass
        for _ in range(50):
            if not _pid_alive(pid):
                break
            time.sleep(0.1)
    _wait_until_listening_free(port)
    new_pid = _spawn_service(port, host)
    _wait_until_listening(port)
    n = len(registry.load_projects())
    print(f"restarted: http://localhost:{port}/  (pid {new_pid}, {n} projects)")
    return 0


def _skill_source_dir() -> str | None:
    """Resolve the canonical .claude/skills/painel directory next to this
    checkout, if there is one. Works when painel is `pip install -e`'d
    straight from its own git repo (which is the only real install path
    right now, pre-M4/PyPI) -- an editable install's __file__ still points
    into the source tree, so the repo root is just two levels up from this
    package. Returns None for any install where that directory doesn't
    exist (e.g. a hypothetical future wheel install with no .claude/
    alongside it) rather than guessing or fabricating a path."""
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(pkg_dir)
    candidate = os.path.join(repo_root, ".claude", "skills", "painel")
    return candidate if os.path.isdir(candidate) else None


def cmd_install_skill(project_dir: str) -> int:
    """Install the pAInel Claude Code skill into `project_dir` as a SYMLINK
    to the canonical copy, never a file copy. A copy can drift out of sync
    the moment the canonical skill is improved (this is exactly how a real
    board ended up composed of checklist items that should have been
    form/tasks -- the session that wrote it had no skill file at all, just
    prior context); a symlink makes that class of bug structurally
    impossible; there is nothing to "sync" because there is only ever one
    real copy. Safe to run again: a symlink already pointing at the same
    canonical dir is a no-op, not an error. Refuses to clobber a real
    directory/file at the destination (e.g. someone's own hand-copied
    skill) rather than silently overwriting it."""
    src = _skill_source_dir()
    if src is None:
        print(
            "error: could not find the canonical skill next to this installation -- "
            "this only works when painel is installed with "
            "'pip install -e' from its own repository.",
            file=sys.stderr,
        )
        return 1
    dest_parent = os.path.join(project_dir, ".claude", "skills")
    dest = os.path.join(dest_parent, "painel")
    if os.path.islink(dest):
        if os.path.realpath(dest) == os.path.realpath(src):
            print(f"already linked: {dest} -> {src}")
            return 0
        os.remove(dest)  # stale link pointing somewhere else -- replace it
    elif os.path.exists(dest):
        print(
            f"warning: {dest} already exists and is not a symlink -- "
            f"I will not replace a manual copy. Remove it by hand if you "
            f"want the link (and from then on it never goes stale again).",
            file=sys.stderr,
        )
        return 1
    os.makedirs(dest_parent, exist_ok=True)
    os.symlink(src, dest)
    print(f"linked: {dest} -> {src}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="painel", description="pAInel — second interface for CLI agents")
    sub = p.add_subparsers(dest="cmd", required=True)

    po = sub.add_parser("open", help="register this project (if new), start the service (if needed), open the board — the one command to remember")
    po.add_argument("dir", nargs="?", default=".", help="project directory (or a board.json path)")
    po.add_argument("--port", type=int, default=None)

    pa = sub.add_parser("add", help="register a project's board without opening it (for bulk-adding existing projects)")
    pa.add_argument("dir", nargs="?", default=".", help="project directory (or a board.json path)")

    pl = sub.add_parser("lint", help="check a board for checklist items that should be a question/form (exit 1 if any)")
    pl.add_argument("board", nargs="?", default=".", help="project directory (or a board.json path)")

    prm = sub.add_parser("remove", help="unregister a project by slug (never deletes the board file)")
    prm.add_argument("slug")

    sub.add_parser("stop", help="stop the pAInel service")
    sub.add_parser("status", help="is the service up, on what port, with how many projects")
    sub.add_parser("restart-all", help="restart the pAInel service (same port) -- run after upgrading painel")

    pis = sub.add_parser("install-skill", help="symlink the Claude Code skill into a project (always in sync, never a stale copy)")
    pis.add_argument("project_dir", nargs="?", default=".")

    ps = sub.add_parser("serve", help="serve ONE board.json (blocking, foreground; no registry)")
    ps.add_argument("board")
    ps.add_argument("--port", type=int, default=8765)
    ps.add_argument("--open", action="store_true", help="open the browser")

    for name, helptext in (
        ("service", "serve every registered project (docs/SPEC.md §17), blocking, foreground"),
        ("hub", "alias for 'service' (kept so existing habits and scripts don't break)"),
    ):
        psv = sub.add_parser(name, help=helptext)
        psv.add_argument("--port", type=int, default=SERVICE_PORT)
        psv.add_argument("--host", default="127.0.0.1",
                         help="bind address; anything but loopback needs " + EXPOSE_ACK_FLAG)
        psv.add_argument(EXPOSE_ACK_FLAG, dest="expose_ack", action="store_true",
                         help="acknowledge that a non-loopback bind exposes every board, "
                              "credentials included, with no authentication at all")

    pi = sub.add_parser("init", help="write a starter board.json")
    pi.add_argument("board")

    pd = sub.add_parser("demo", help="serve a showcase board")
    pd.add_argument("--port", type=int, default=8765)

    args = p.parse_args(argv)

    if args.cmd == "open":
        return cmd_open(args.dir, args.port)
    if args.cmd == "add":
        return cmd_add(args.dir)
    if args.cmd == "lint":
        return cmd_lint(args.board)
    if args.cmd == "remove":
        return cmd_remove(args.slug)
    if args.cmd == "stop":
        return cmd_stop()
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "restart-all":
        return cmd_restart_all()
    if args.cmd == "install-skill":
        return cmd_install_skill(args.project_dir)
    if args.cmd == "serve":
        _default_agent_status_if_absent(args.board)
        serve(args.board, port=args.port, open_browser=args.open)
        return 0
    if args.cmd in ("service", "hub"):
        if not _check_exposure(args.host, args.expose_ack):
            return 1
        serve_service(port=args.port, host=args.host)
        return 0
    if args.cmd == "init":
        if os.path.exists(args.board):
            print(f"already exists: {args.board}", file=sys.stderr)
            return 1
        save_board(args.board, STARTER)
        print(f"created: {args.board}")
        return 0
    if args.cmd == "demo":
        path = ".painel-demo.json"
        save_board(path, _demo_board())
        serve(path, port=args.port, open_browser=True)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
