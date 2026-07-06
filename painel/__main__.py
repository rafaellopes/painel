"""
Command-line entry point for pAInel.

Usage:
    python -m painel open   [board.json]          # the one command people actually type
    python -m painel stop   [board.json]
    python -m painel status [board.json]
    python -m painel serve  <board.json> [--port 8765] [--open]
    python -m painel init   <board.json>          # write a starter board
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

from .server import serve, serve_hub, save_board, load_board

DEFAULT_BOARD = ".painel-board.json"
HUB_PORT = 8765

STARTER = {
    "title": "pAInel",
    "meta": {"project": os.path.basename(os.getcwd())},
    "blocks": [
        {"id": "h1", "type": "heading", "text": "Objetivo"},
        {"id": "m1", "type": "markdown", "text": "Descreve aqui o objetivo da sessão."},
        {"id": "h2", "type": "heading", "text": "Progresso"},
        {"id": "tk", "type": "tasks", "title": "Tarefas do agente", "items": [
            {"text": "Primeira tarefa", "status": "wip"},
        ]},
    ],
}


def _demo_board() -> dict:
    return {
        "title": "pAInel — demonstração",
        "meta": {"project": "demo", "agent_status": "working"},
        "blocks": [
            {"id": "h1", "type": "heading", "text": "O que é"},
            {"id": "m1", "type": "markdown",
             "text": "O **pAInel** é a segunda interface do teu agente. "
                     "Cada bloco em baixo é um `tipo` diferente de interação."},
            {"id": "note", "type": "note", "tone": "info",
             "text": "Marca uma checkbox ou responde a uma pergunta — o agente é notificado na hora."},
            {"id": "h2", "type": "heading", "text": "Atividades manuais (tuas)"},
            {"id": "cl", "type": "checklist", "title": "Faz isto e marca", "items": [
                {"id": "c1", "text": "Fazer login no portal X", "checked": False},
                {"id": "c2", "text": "Descarregar o **PDF** do relatório", "checked": False},
                {"id": "c3", "text": "Colocar o ficheiro em `~/Downloads`", "checked": False},
            ]},
            {"id": "h2b", "type": "heading", "text": "Um plano que se controla, não só se lê"},
            {"id": "pl", "type": "plan", "title": "Plano", "items": [
                {"id": "p1", "text": "Ler configuração", "status": "done"},
                {"id": "p2", "text": "Processar ficheiro", "status": "wip"},
                {"id": "p3", "text": "Gerar relatório", "status": "pending"},
                {"id": "p4", "text": "Enviar por email", "status": "pending"},
            ]},
            {"id": "h3", "type": "heading", "text": "Progresso do agente"},
            {"id": "tk", "type": "tasks", "title": "Pipeline", "items": [
                {"text": "Ler configuração", "status": "done"},
                {"text": "Processar ficheiro", "status": "wip"},
                {"text": "Gerar relatório", "status": "pending"},
                {"text": "Enviar por email", "status": "blocked"},
            ]},
            {"id": "h4", "type": "heading", "text": "Perguntas & decisões"},
            {"id": "q1", "type": "question", "prompt": "Qual o email de destino do relatório?", "answer": None},
            {"id": "ch", "type": "choice", "prompt": "Formato do relatório?",
             "options": ["PDF", "Excel", "Ambos"], "selected": None},
            {"id": "ap", "type": "approval",
             "prompt": "Posso enviar o email agora?", "decision": None},
            {"id": "fm", "type": "form", "prompt": "Dados do cliente:", "fields": [
                {"id": "nome", "label": "Nome", "kind": "text", "value": ""},
                {"id": "plano", "label": "Plano", "kind": "select",
                 "options": ["Básico", "Pro"], "value": ""},
            ], "submitted": False},
            {"id": "lg", "type": "log", "title": "Registo", "entries": [
                {"ts": "10:00", "text": "Sessão iniciada"},
            ]},
            {"id": "h5", "type": "heading", "text": "Conversa livre"},
            {"id": "chat", "type": "chat", "title": "Conversa", "messages": [
                {"from": "user", "text": "Porque escolheste esta abordagem?"},
                {"from": "agent", "text": "Porque **X** evita Y — ver decisão em Registo."},
            ]},
        ],
        "change_requests": [
            {"id": "cr1", "block": "pl", "text": "adiciona uma fase de testes com utilizadores",
             "status": "open", "ts": "10:05"},
        ],
    }


def _pidfile(board: str) -> str:
    return board + ".pid"


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _find_free_port(start: int = 8765, tries: int = 50) -> int:
    port = start
    for _ in range(tries):
        if _port_free(port):
            return port
        port += 1
    raise RuntimeError("nenhuma porta livre encontrada")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return exc.errno == errno.EPERM  # exists but owned by someone else
    return True


def _read_pidfile(board: str) -> dict | None:
    pf = _pidfile(board)
    if not os.path.exists(pf):
        return None
    try:
        with open(pf, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


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


def _spawn(board: str, port: int) -> int:
    """Launch a detached `painel serve` for `board` on `port`, log to
    `<board>.log` (appended, so restart-all keeps history), pidfile written.
    Returns the child pid. Shared by cmd_open and restart-all so both spawn
    identically."""
    log_path = board + ".log"
    log_fh = open(log_path, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "painel", "serve", board, "--port", str(port)],
        stdout=log_fh, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    with open(_pidfile(board), "w", encoding="utf-8") as fh:
        json.dump({"pid": proc.pid, "port": port}, fh)
    _write_registry(proc.pid, port, board, kind="board")
    return proc.pid


def _hub_logfile(port: int) -> str:
    return os.path.join(_registry_dir(), f"hub-{port}.log")


def _hub_pidfile(port: int) -> str:
    return os.path.join(_registry_dir(), f"hub-{port}.pid")


def _spawn_hub(port: int) -> int:
    """Launch a detached `painel hub` on `port` (§13.2). A hub is itself a
    `painel serve`-style process -- but of a synthetic/generated board, not
    a file on disk -- so it gets its own code path (`python -m painel hub`,
    not `... serve <board>`) and its own log/pidfile under the registry dir
    (there's no project board path to hang a `<board>.log`/`<board>.pid` off
    of). Registered with kind='hub' so restart-all's discovery can tell it
    apart from a normal board instance and respawn it correctly (see
    _discover_running_boards/cmd_restart_all)."""
    log_fh = open(_hub_logfile(port), "a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "painel", "hub", "--port", str(port)],
        stdout=log_fh, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    with open(_hub_pidfile(port), "w", encoding="utf-8") as fh:
        json.dump({"pid": proc.pid, "port": port}, fh)
    _write_registry(proc.pid, port, board=None, kind="hub")
    return proc.pid


def _is_our_hub(port: int) -> bool:
    """Best-effort signature check: is whatever answers on `port` actually a
    pAInel hub, or an unrelated service that happens to occupy the hub's
    default port (8765 is a common low port -- collisions with something
    else the user already runs there are entirely plausible, not hypothetical:
    caught this exact case during dogfooding, port 8765 already held by an
    unrelated project). A quick GET + title match, not a real handshake --
    false negatives just mean an extra (harmless) stderr notice, never a
    crash or a stolen port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as r:
            body = r.read(4096).decode("utf-8", "ignore")
    except (OSError, urllib.error.URLError, TimeoutError):
        return False
    from .hub import STRINGS as HUB_STRINGS
    return HUB_STRINGS["title"] in body


def _ensure_hub_running(port: int = HUB_PORT) -> None:
    """Idempotent, same _spawn-family pattern as cmd_open's own board check
    (§13.2): if a hub is already alive on `port`, do nothing; otherwise start
    one. Never opens a browser tab -- the hub is the thing you bookmark once,
    not something that appears unprompted."""
    for inst in _discover_running_boards():
        if inst.get("kind") == "hub" and inst["port"] == port:
            return
    if not _port_free(port):
        if not _is_our_hub(port):
            print(
                f"aviso: a porta {port} já está ocupada por outro serviço -- "
                f"o hub do pAInel não arrancou aí. Usa 'painel hub --port <N>' "
                f"noutra porta se quiseres o hub mesmo assim.",
                file=sys.stderr,
            )
        return  # either it's genuinely our hub already, or something else we won't fight
    _spawn_hub(port)
    _wait_until_listening(port)


def _wait_until_listening(port: int, tries: int = 50) -> None:
    for _ in range(tries):
        if not _port_free(port):
            return
        time.sleep(0.1)


def cmd_open(board: str, port: int | None) -> int:
    if not os.path.exists(board):
        save_board(board, STARTER)
        print(f"board criado: {board}")
    _default_agent_status_if_absent(board)

    _ensure_hub_running()  # §13.2 -- idempotent, no browser tab for the hub itself

    info = _read_pidfile(board)
    if info and _pid_alive(info.get("pid", -1)) and not _port_free(info["port"]):
        url = f"http://localhost:{info['port']}/"
        print(f"pAInel já está a correr: {url}")
        webbrowser.open(url)
        return 0

    chosen_port = port or _find_free_port()
    _spawn(board, chosen_port)
    _wait_until_listening(chosen_port)
    url = f"http://localhost:{chosen_port}/"
    webbrowser.open(url)
    print(f"pAInel aberto: {url}  (para parar: python3 -m painel stop {board})")
    return 0


def cmd_stop(board: str) -> int:
    info = _read_pidfile(board)
    if not info:
        print("não há nenhum pAInel a correr para este board.")
        return 0
    pid = info.get("pid")
    if pid and _pid_alive(pid):
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    if "port" in info:
        _remove_registry(info["port"])
    os.remove(_pidfile(board))
    print("parado.")
    return 0


def cmd_status(board: str) -> int:
    info = _read_pidfile(board)
    if info and _pid_alive(info.get("pid", -1)) and not _port_free(info["port"]):
        print(f"a correr em http://localhost:{info['port']}/  (pid {info['pid']})")
    else:
        print("parado.")
    return 0


def _registry_dir() -> str:
    """Central, machine-wide record of every instance _spawn() has started,
    one small JSON file per port. This exists ONLY so restart-all can find
    every running instance without hunting down per-project pidfiles or
    parsing `ps` output -- an earlier version tried the latter and broke on
    any board path containing a space (e.g. Google Drive's "Meu Drive"),
    since `ps`'s printed command line has no reliable way to tell "a space
    inside one argument" from "a space between two arguments" once the
    kernel's argv boundaries are gone. A file per port sidesteps that
    entirely: the board path is read back as a JSON string, never
    reconstructed from shell text."""
    d = os.path.join(os.path.expanduser("~"), ".painel", "instances")
    os.makedirs(d, exist_ok=True)
    return d


def _registry_path(port: int) -> str:
    return os.path.join(_registry_dir(), f"{port}.json")


def _write_registry(pid: int, port: int, board: str | None, kind: str = "board") -> None:
    """`kind` distinguishes a normal board instance ('board', the default --
    and the implicit value of every pre-M9 registry entry, which has no
    `kind` key at all) from the hub itself ('hub', §13.2), so restart-all
    knows whether to respawn with `painel serve <board>` or `painel hub`.
    `board` is None for a hub entry (there is no board.json backing it)."""
    entry = {"pid": pid, "port": port, "kind": kind}
    entry["board"] = os.path.abspath(board) if board is not None else None
    with open(_registry_path(port), "w", encoding="utf-8") as fh:
        json.dump(entry, fh)


def _remove_registry(port: int) -> None:
    try:
        os.remove(_registry_path(port))
    except OSError:
        pass


def _discover_running_boards(kind: str | None = None) -> list[dict]:
    """Every instance _spawn()/_spawn_hub() has ever started that is still
    actually alive right now (pid alive AND its port no longer free) --
    reads the central registry (see _registry_dir), not the process table. A
    registry entry whose process has since died is stale and removed on
    sight (self-healing: no manual cleanup needed as instances come and go).

    `kind` defaults to 'board' on any entry that predates M9 and therefore
    has no `kind` key at all -- this is the backward-compat rule (§13's
    registry format extension): old entries only ever described boards, so
    absence of the key means exactly that. Pass kind="board"/"hub" to filter
    (the hub's own listing, painel/hub.py, only ever wants boards).

    Returns [{"pid", "board", "port", "kind"}] ("board" is None for hubs)."""
    found = []
    d = _registry_dir()
    try:
        names = os.listdir(d)
    except OSError:
        return []
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(d, name)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                entry = json.load(fh)
            pid, port, board = entry["pid"], entry["port"], entry["board"]
            entry_kind = entry.get("kind") or "board"
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            _try_remove(path)
            continue
        if _pid_alive(pid) and not _port_free(port):
            if kind is not None and entry_kind != kind:
                continue
            found.append({"pid": pid, "board": board, "port": port, "kind": entry_kind})
        else:
            _try_remove(path)  # stale -- that instance is gone
    return found


def _try_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def cmd_restart_all() -> int:
    """Restart every running pAInel instance on this machine on the SAME
    port (and, for boards, the same board file), so a freshly-shipped painel
    version is picked up everywhere at once without hunting down each
    project's process by hand. Respawns each instance with the code path
    matching its registry `kind` (§13.2/M9): a hub entry gets `painel hub
    --port <port>` back, a board entry gets `painel serve <board> --port
    <port>` back -- old-format entries with no `kind` key default to
    'board' (see _discover_running_boards), so this is fully backward
    compatible with a registry written before M9 shipped."""
    instances = _discover_running_boards()
    if not instances:
        print("nenhum pAInel a correr.")
        return 0
    for inst in instances:
        pid, board, port, kind = inst["pid"], inst["board"], inst["port"], inst["kind"]
        if _pid_alive(pid):
            try:
                os.kill(pid, 15)
            except OSError:
                pass
        for _ in range(50):
            if not _pid_alive(pid):
                break
            time.sleep(0.1)
        _wait_until_listening_free(port)
        if kind == "hub":
            new_pid = _spawn_hub(port)
            _wait_until_listening(port)
            print(f"reiniciado: hub  http://localhost:{port}/  (pid {new_pid})")
        else:
            new_pid = _spawn(board, port)
            _wait_until_listening(port)
            print(f"reiniciado: {board}  http://localhost:{port}/  (pid {new_pid})")
    return 0


def _wait_until_listening_free(port: int, tries: int = 50) -> None:
    for _ in range(tries):
        if _port_free(port):
            return
        time.sleep(0.1)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="painel", description="pAInel — second interface for CLI agents")
    sub = p.add_subparsers(dest="cmd", required=True)

    po = sub.add_parser("open", help="start (if needed) and open the board in the browser — the one command to remember")
    po.add_argument("board", nargs="?", default=DEFAULT_BOARD)
    po.add_argument("--port", type=int, default=None)

    pstop = sub.add_parser("stop", help="stop the running server for this board")
    pstop.add_argument("board", nargs="?", default=DEFAULT_BOARD)

    pstat = sub.add_parser("status", help="check if a board's server is running")
    pstat.add_argument("board", nargs="?", default=DEFAULT_BOARD)

    sub.add_parser("restart-all", help="restart every running pAInel instance on this machine (same board+port) -- run after upgrading painel")

    ps = sub.add_parser("serve", help="serve a board.json (blocking, foreground)")
    ps.add_argument("board")
    ps.add_argument("--port", type=int, default=8765)
    ps.add_argument("--open", action="store_true", help="open the browser")

    ph = sub.add_parser("hub", help="serve the hub (docs/SPEC.md §13): a fixed-port page listing every live board (blocking, foreground)")
    ph.add_argument("--port", type=int, default=HUB_PORT)

    pi = sub.add_parser("init", help="write a starter board.json")
    pi.add_argument("board")

    pd = sub.add_parser("demo", help="serve a showcase board")
    pd.add_argument("--port", type=int, default=8765)

    args = p.parse_args(argv)

    if args.cmd == "open":
        return cmd_open(args.board, args.port)
    if args.cmd == "stop":
        return cmd_stop(args.board)
    if args.cmd == "status":
        return cmd_status(args.board)
    if args.cmd == "restart-all":
        return cmd_restart_all()
    if args.cmd == "serve":
        _default_agent_status_if_absent(args.board)
        serve(args.board, port=args.port, open_browser=args.open)
        return 0
    if args.cmd == "hub":
        serve_hub(port=args.port)
        return 0
    if args.cmd == "init":
        if os.path.exists(args.board):
            print(f"já existe: {args.board}", file=sys.stderr)
            return 1
        save_board(args.board, STARTER)
        print(f"criado: {args.board}")
        return 0
    if args.cmd == "demo":
        path = ".painel-demo.json"
        save_board(path, _demo_board())
        serve(path, port=args.port, open_browser=True)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
