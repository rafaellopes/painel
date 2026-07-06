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
import webbrowser

from .server import serve, save_board, load_board

DEFAULT_BOARD = ".painel-board.json"

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
    _write_registry(proc.pid, port, board)
    return proc.pid


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


def _write_registry(pid: int, port: int, board: str) -> None:
    with open(_registry_path(port), "w", encoding="utf-8") as fh:
        json.dump({"pid": pid, "port": port, "board": os.path.abspath(board)}, fh)


def _remove_registry(port: int) -> None:
    try:
        os.remove(_registry_path(port))
    except OSError:
        pass


def _discover_running_boards() -> list[dict]:
    """Every instance _spawn() has ever started that is still actually alive
    right now (pid alive AND its port no longer free) -- reads the central
    registry (see _registry_dir), not the process table. A registry entry
    whose process has since died is stale and removed on sight (self-healing:
    no manual cleanup needed as instances come and go). Returns
    [{"pid", "board", "port"}]."""
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
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            _try_remove(path)
            continue
        if _pid_alive(pid) and not _port_free(port):
            found.append({"pid": pid, "board": board, "port": port})
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
    board+port, so a freshly-shipped painel version is picked up everywhere
    at once without hunting down each project's process by hand."""
    instances = _discover_running_boards()
    if not instances:
        print("nenhum pAInel a correr.")
        return 0
    for inst in instances:
        pid, board, port = inst["pid"], inst["board"], inst["port"]
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
