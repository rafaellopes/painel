"""
Block-choice lint (M16, docs/SPEC.md §20).

**Why this exists.** The most common composition mistake is putting something
in a `checklist` that isn't a yes/no step -- it has happened three times on
real boards. The skill was updated *twice* with explicit prose rules and the
mistake recurred anyway. That is the finding this module is built on: a rule
that lives only in prose depends on the composing model remembering it, and
models forget. Prevention has to be mechanical.

`lint_board(board) -> list[Finding]` is a **pure function over a board dict**
(§20.3): not a block-module hook, not part of `server.py`. Its two callers are
the `painel lint` CLI (compose-time prevention) and `checklist.py`'s render
(the render-time safety net) -- and, because it is pure, any future consumer
(an editor plugin, a pre-commit hook) can reuse it with no plumbing.

Design rule, load-bearing: **prefer false negatives over false positives**
(§20.1). A noisy linter gets ignored, which would defeat the entire milestone.
Every marker below is earned by an observed incident or is an unambiguous
answer-request verb; when in doubt, a marker is left out.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from typing import NamedTuple


class Finding(NamedTuple):
    """One flagged item. Field names kept simple and values kept to plain
    strings so `finding._asdict()` is directly JSON-serializable -- a future
    consumer (editor plugin, pre-commit hook, Cloud) may want to emit these."""
    block: str
    item: str
    text: str
    reason: str
    suggestion: str


# --------------------------------------------------------------------------- #
# The heuristic (§20.1)                                                        #
# --------------------------------------------------------------------------- #
# Answer-requesting markers, exactly as specified. Matched case- AND
# accent-insensitively, and on WORD BOUNDARIES -- a naive substring test would
# fire "qual" inside "qualidade" and "indica" inside "indicador", both of which
# are perfectly good checklist steps. False positives are the one failure mode
# that kills adoption, so the boundary check is not optional.
#
# Deliberately absent: plain action verbs (fazer login, descarregar, publicar,
# gravar, criar conta, largar, colocar) -- those are exactly what `checklist`
# is *for*. Also absent: a bare "confirmar". The spec asks for "confirmar com"
# (as in "confirmar com o sócio: X ou Y?") precisely because bare "confirmar"
# would flag legitimate verification steps ("confirmar que o deploy correu
# bem"), which is the noise this linter must not produce.
#
# REMOVED after measuring against the real corpus (§20.5): "escolher"/"escolhe"
# and "definir". Running the linter over 59 real checklist items across 7 real
# boards produced exactly 2 findings, and BOTH were false positives, both from
# "escolhe(r)":
#
#   "…PostHog: funis, coortes, feature flags. Escolhe uma e instrumenta um
#    produto teu."
#   "Correr um teste A/B a valer: (1) escolher UMA mudança real com impacto…"
#
# In both, choosing is part of the WORK the human does, not a value they must
# report back -- the item really is a done/not-done step. That is the whole
# false-positive class §20.1 forbids, measured on real data rather than
# imagined. "definir" is the same kind of verb (an action as often as a
# request) and was likewise never earned by a real incident, so it goes with
# them rather than waiting to misfire.
#
# The survivors below are plausible answer-requests, but note honestly that
# only "responder", "confirmar com" and the ends-with-"?" rule were actually
# earned by observed incidents; the rest are unmeasured. Drop any of them at
# the FIRST real false positive -- do not defend them.
MARKERS = (
    "responder", "responde",
    "indicar", "indica",
    "informar", "informe",
    "qual", "quais",
    "quanto", "quantos",
    "preencher", "preenche",
    "diz-me", "da-me", "envia-me",
    "confirmar com",
)

_MARKER_RE = re.compile(
    r"(?<![0-9a-z])(" + "|".join(re.escape(m) for m in MARKERS) + r")(?![0-9a-z])"
)

# Trailing markup/whitespace to peel off before the "ends with '?'" test: a
# trailing HTML-ish tag, then inline-markdown punctuation. "Está correto?**"
# and "Está correto? " must both count as ending with a question mark.
_TRAILING_TAG_RE = re.compile(r"<[^<>]*>\s*$")
_TRAILING_MARKUP = "*`_~ \t\r\n"

SUGGESTION = "question"

# What the render-time ⚠ says. Layer 3 of §20.2: the copy's whole job is to
# point the human at the per-item ❓ that M12 already built. No new fix UI.
WARN_TITLE = (
    "Este passo parece pedir uma resposta, não um visto ({reason}). "
    "Marcá-lo não entrega nada ao agente. Usa o ❓ ao lado para pedires "
    "que seja convertido num bloco de pergunta."
)


def fold(text) -> str:
    """Lowercase + accent-fold, using the same NFKD->ascii approach as
    `registry.slugify` (§20.1 is explicit about not hand-writing a second
    accent table). Whitespace is collapsed so a multi-word marker like
    "confirmar com" still matches across a line break or a double space."""
    s = unicodedata.normalize("NFKD", str(text or ""))
    s = s.encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(s.split())


def _strip_trailing_markup(text: str) -> str:
    s = str(text or "")
    while True:
        stripped = _TRAILING_TAG_RE.sub("", s).rstrip(_TRAILING_MARKUP)
        if stripped == s:
            return s
        s = stripped


def check_text(text) -> str | None:
    """The whole heuristic, isolated for testability. Returns a PT-PT reason
    string when the text looks like it wants an *answer* rather than a *tick*,
    or None when it looks like a plain action."""
    if _strip_trailing_markup(text).endswith("?"):
        return "termina com '?'"
    match = _MARKER_RE.search(fold(text))
    if match:
        return f"contém «{match.group(1)}»"
    return None


# --------------------------------------------------------------------------- #
# Rules per block type (§20.3)                                                 #
# --------------------------------------------------------------------------- #
def _lint_checklist(block: dict) -> list[Finding]:
    out = []
    for it in block.get("items", []) or []:
        if not isinstance(it, dict):
            continue
        text = it.get("text", "")
        reason = check_text(text)
        if reason:
            out.append(Finding(
                block=str(block.get("id", "")),
                item=str(it.get("id", "")),
                text=str(text),
                reason=reason,
                suggestion=SUGGESTION,
            ))
    return out


# Only `checklist` is linted in M16, on purpose (§20.3): every rule here is
# earned by a real incident, and that is what keeps the signal-to-noise ratio
# high enough for the linter to be worth obeying. Adding a rule for another
# block type is one function plus one entry here -- but do not write one
# speculatively for a failure mode nobody has observed.
_RULES = {"checklist": _lint_checklist}


def lint_board(board: dict) -> list[Finding]:
    """Every flagged item in a board, in board order. Never raises on a
    malformed board -- a linter that crashes on the input it exists to
    inspect is worse than no linter."""
    out: list[Finding] = []
    if not isinstance(board, dict):
        return out
    for block in board.get("blocks", []) or []:
        if not isinstance(block, dict):
            continue
        rule = _RULES.get(block.get("type"))
        if rule:
            out.extend(rule(block))
    return out


def lint_block(block: dict) -> list[Finding]:
    """Findings for a single block -- what `checklist.py`'s render needs, so
    it doesn't have to reach for the whole board it was never given."""
    if not isinstance(block, dict):
        return []
    rule = _RULES.get(block.get("type"))
    return rule(block) if rule else []


# --------------------------------------------------------------------------- #
# Render-time stderr warning (§20.2 layer 2)                                   #
# --------------------------------------------------------------------------- #
# render() runs on EVERY request and the page is re-rendered constantly by the
# 2s poller -- logging per render would put hundreds of identical lines a
# minute into ~/.painel/service.log, and a log nobody can read is as useless as
# a lint nobody runs. So the warning is deduplicated in-process by the finding's
# own identity (block + item + text): the agent gets exactly one line per
# distinct problem per service lifetime, and an *edited* item text produces a
# fresh line (which is correct -- it is a new finding).
_warned: set[tuple[str, str, str]] = set()


def reset_warnings() -> None:
    """Forget what has already been logged. For tests; also harmless to call
    at service start."""
    _warned.clear()


def warn_once(finding: Finding, stream=None) -> bool:
    """Log `finding` to stderr unless an identical one was already logged.
    Returns True if it actually wrote a line."""
    key = (finding.block, finding.item, finding.text)
    if key in _warned:
        return False
    _warned.add(key)
    stream = sys.stderr if stream is None else stream
    print(format_finding(finding, prefix="[painel:lint] "), file=stream, flush=True)
    return True


def format_finding(finding: Finding, prefix: str = "") -> str:
    """One line, greppable, same shape for the CLI and for the stderr net."""
    where = f"{finding.block}/{finding.item}" if finding.item else finding.block
    return (
        f"{prefix}checklist {where}: {finding.reason} — parece pedir uma resposta, "
        f"não um visto; considera o bloco '{finding.suggestion}' "
        f"(ou 'form' se forem vários campos). Texto: {finding.text!r}"
    )
