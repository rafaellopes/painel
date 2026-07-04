"""
Block registry: auto-discovers sibling modules that define a TYPE attribute
and exposes them as REGISTRY = {type: module}.

Adding a new block type is one file + one entry in this registry, added
automatically -- no edits needed here or in server.py. See _template.py for
the module contract every block must follow.
"""
from __future__ import annotations

import importlib
import pkgutil

REGISTRY: dict = {}

for _finder, _name, _is_pkg in pkgutil.iter_modules(__path__):
    if _name.startswith("_"):
        continue  # skip _template.py and any other private helper module
    _mod = importlib.import_module(f"{__name__}.{_name}")
    _type = getattr(_mod, "TYPE", None)
    if _type:
        REGISTRY[_type] = _mod
