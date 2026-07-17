"""
The project registry (M13, docs/SPEC.md §17.3).

Replaces §6.6's per-port *process* registry with a plain list of the human's
*projects*. The distinction is the whole milestone: the directory should show
your projects, not your processes -- 7 boards existed on the author's disk
while only 2 had a server running, so the old hub listed 2.

    ~/.painel/projects.json   {slug: {"path": "<abs board.json>", "title": "..."}}
    ~/.painel/service.json    {"pid": int, "port": int, "host": "127.0.0.1"}

Load-bearing rule (§17.3): **the slug is generated once and then stored**,
never recomputed on read. Retitling a board must not silently change its URL
and break a bookmark -- which is exactly what a "derive the slug from
meta.project on every read" implementation would do.

board.json itself is NEVER moved here (§17.2.1): it lives next to the work,
in the project's own git/Drive folder, and the service reads it at its
registered path. This file only ever stores a pointer.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata

# Slugs that would shadow a service-level route (§17.3). Only "/" is routed at
# the top level today, but "version"/"event" are reserved *under* a slug and
# keeping them unassignable here too costs nothing and avoids a class of
# "which one wins" surprise. A collision is suffixed, never rejected: a
# registered project must always be reachable.
RESERVED_SLUGS = {"version", "event", "api", "static", "favicon.ico", "robots.txt"}

_NON_SLUG_RE = re.compile(r"[^a-z0-9-]")
_SEPARATOR_RE = re.compile(r"[\s._/\\]+")
_REPEAT_RE = re.compile(r"-{2,}")


def painel_dir() -> str:
    d = os.path.join(os.path.expanduser("~"), ".painel")
    os.makedirs(d, exist_ok=True)
    return d


def projects_path() -> str:
    return os.path.join(painel_dir(), "projects.json")


def service_path() -> str:
    return os.path.join(painel_dir(), "service.json")


def service_log_path() -> str:
    return os.path.join(painel_dir(), "service.log")


# --------------------------------------------------------------------------- #
# Slugs                                                                        #
# --------------------------------------------------------------------------- #
def slugify(text) -> str:
    """§17.3: lowercase, spaces/dots/underscores -> '-', strip anything
    outside [a-z0-9-], collapse repeats. Accents are folded first (NFKD ->
    ascii) rather than stripped, so "Finanças" becomes "financas" and not
    "finanas" -- a stripped-accent slug is unreadable, and most of the
    author's real projects are Portuguese."""
    s = unicodedata.normalize("NFKD", str(text or ""))
    s = s.encode("ascii", "ignore").decode("ascii").strip().lower()
    s = _SEPARATOR_RE.sub("-", s)
    s = _NON_SLUG_RE.sub("", s)
    s = _REPEAT_RE.sub("-", s).strip("-")
    return s or "projeto"


def _load_board_safe(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            board = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return board if isinstance(board, dict) else None


def base_slug(board_path: str, board: dict | None = None) -> str:
    """The slug a board *would* get, before collision suffixing: from
    meta.project, falling back to the board's parent directory name (§17.3)."""
    if board is None:
        board = _load_board_safe(board_path)
    project = (board.get("meta") or {}).get("project") if board else None
    if not project:
        project = os.path.basename(os.path.dirname(os.path.abspath(board_path)))
    return slugify(project)


def _unique_slug(base: str, projects: dict) -> str:
    """Collision -> '-2', '-3'… (§17.3). A reserved name is treated as a
    collision for the same reason: suffix it, never leave a project
    unreachable."""
    candidate = base
    n = 1
    while candidate in projects or candidate in RESERVED_SLUGS:
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def _display_title(board_path: str, board: dict | None) -> str:
    if board:
        title = board.get("title") or (board.get("meta") or {}).get("project")
        if title:
            return str(title)
    return os.path.basename(os.path.dirname(os.path.abspath(board_path)))


# --------------------------------------------------------------------------- #
# Reading / writing                                                            #
# --------------------------------------------------------------------------- #
def load_projects() -> dict:
    try:
        with open(projects_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_projects(projects: dict) -> None:
    path = projects_path()
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(projects, fh, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


def register(board_path: str) -> str:
    """Register a board and return its slug. Idempotent: a board already
    registered keeps the slug it was first given, forever (§17.3) -- only its
    display `title` is refreshed, since that's cosmetic and never addresses
    anything."""
    path = os.path.abspath(board_path)
    projects = load_projects()
    board = _load_board_safe(path)
    title = _display_title(path, board)
    for slug, entry in projects.items():
        if os.path.abspath(str(entry.get("path", ""))) == path:
            entry["title"] = title
            save_projects(projects)
            return slug
    slug = _unique_slug(base_slug(path, board), projects)
    projects[slug] = {"path": path, "title": title}
    save_projects(projects)
    return slug


def unregister(slug: str) -> bool:
    """Remove a slug from the registry. NEVER deletes the board file (§17.5)."""
    projects = load_projects()
    if slug not in projects:
        return False
    del projects[slug]
    save_projects(projects)
    return True


def get(slug: str) -> dict | None:
    entry = load_projects().get(slug)
    if entry is None:
        return None
    return _entry(slug, entry)


def _entry(slug: str, entry: dict) -> dict:
    path = str(entry.get("path", ""))
    return {
        "slug": slug,
        "path": path,
        "title": entry.get("title") or slug,
        # §17.3: a registry entry whose path is gone renders as a *visibly*
        # missing project, never silently dropped -- a moved project should be
        # diagnosable, not invisible (same spirit as resources' "⚠ não
        # encontrado", §15.2).
        "missing": not os.path.exists(path),
    }


def entries() -> list[dict]:
    """Every registered project, missing ones included, ordered by title."""
    projects = load_projects()
    out = [_entry(slug, entry) for slug, entry in projects.items()]
    out.sort(key=lambda x: (x["title"].casefold(), x["slug"]))
    return out


# --------------------------------------------------------------------------- #
# The service's own process (§17.3)                                            #
# --------------------------------------------------------------------------- #
def read_service() -> dict | None:
    try:
        with open(service_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_service(pid: int, port: int, host: str = "127.0.0.1") -> None:
    with open(service_path(), "w", encoding="utf-8") as fh:
        json.dump({"pid": pid, "port": port, "host": host}, fh)


def clear_service() -> None:
    try:
        os.remove(service_path())
    except OSError:
        pass


def clean_legacy_instances() -> None:
    """Migration (§17.7): pre-M13 ~/.painel/instances/*.json described one
    process per board. There are no per-board processes any more, so the
    directory is meaningless -- drop it on first run of the new service
    rather than leaving confusing dead state behind. Nothing reads it."""
    shutil.rmtree(os.path.join(painel_dir(), "instances"), ignore_errors=True)
