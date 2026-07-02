"""
Command-line entry point for pAInel.

Usage:
    python -m painel serve <board.json> [--port 8765] [--open]
    python -m painel init  <board.json>          # write a starter board
    python -m painel demo                         # serve a showcase board
"""
import argparse
import json
import os
import sys

from .server import serve, save_board

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
        "meta": {"project": "demo"},
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
        ],
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="painel", description="pAInel — second interface for CLI agents")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("serve", help="serve a board.json")
    ps.add_argument("board")
    ps.add_argument("--port", type=int, default=8765)
    ps.add_argument("--open", action="store_true", help="open the browser")

    pi = sub.add_parser("init", help="write a starter board.json")
    pi.add_argument("board")

    pd = sub.add_parser("demo", help="serve a showcase board")
    pd.add_argument("--port", type=int, default=8765)

    args = p.parse_args(argv)

    if args.cmd == "serve":
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
