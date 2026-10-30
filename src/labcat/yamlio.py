"""YAML reading and writing that keeps comments and key order of hand-edited files."""

from __future__ import annotations

import datetime as dt
import io
import re
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import LiteralScalarString


def _yaml() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 100
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def load(text: str) -> Any:
    return _yaml().load(text)


def dump(data: Any) -> str:
    buf = io.StringIO()
    _yaml().dump(data, buf)
    return buf.getvalue()


def plain(v: Any) -> Any:
    """Convert ruamel objects to plain JSON-like Python (dates become strings)."""
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [plain(x) for x in v]
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()[:10]
    if isinstance(v, str):
        return str(v)
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, int):
        return int(v)
    if isinstance(v, float):
        return float(v)
    return v


def _fresh(v: Any) -> Any:
    """Plain value -> ruamel value with nice formatting (block scalars for multi-line text)."""
    if isinstance(v, dict):
        m = CommentedMap()
        for k, x in v.items():
            m[k] = _fresh(x)
        return m
    if isinstance(v, list):
        s = CommentedSeq(_fresh(x) for x in v)
        if v and all(isinstance(x, (str, int)) for x in v) and sum(len(str(x)) for x in v) < 70:
            s.fa.set_flow_style()
        return s
    if isinstance(v, str) and "\n" in v:
        return LiteralScalarString(v.rstrip("\n") + "\n")
    if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return dt.date.fromisoformat(v)  # written unquoted
    return v


def merge(old: Any, new: Any) -> Any:
    """Return `new`, re-using objects from `old` where values are unchanged.

    That keeps comments, quoting and key order of hand-edited files. New keys are
    inserted after their predecessor in `new`'s (schema) order.
    """
    if plain(old) == new:
        return old
    if isinstance(old, CommentedMap) and isinstance(new, dict):
        for k in [k for k in old if k not in new]:
            del old[k]
        prev = None
        for k, v in new.items():
            if k in old:
                old[k] = merge(old[k], v)
            else:
                pos = list(old.keys()).index(prev) + 1 if prev in old else 0
                old.insert(pos, k, _fresh(v))
            prev = k
        return old
    if isinstance(old, CommentedSeq) and isinstance(new, list):
        if not all(isinstance(x, dict) for x in new):
            fresh = _fresh(new)
            return fresh
        for i, v in enumerate(new):
            if i < len(old):
                old[i] = merge(old[i], v)
            else:
                old.append(_fresh(v))
        del old[len(new):]
        return old
    return _fresh(new)


def render(new: dict, old_text: str | None = None) -> str:
    """YAML text for `new`, keeping formatting of `old_text` where possible."""
    if old_text:
        try:
            old = load(old_text)
        except Exception:
            old = None
        if isinstance(old, CommentedMap):
            return dump(merge(old, new))
    return dump(_fresh(new))
