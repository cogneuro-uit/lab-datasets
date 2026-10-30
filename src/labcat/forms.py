"""Translate between HTML form fields and dataset dicts.

Field names use dots and list indices, e.g. `content.tags`, `locations.2.note`.
Fields that hold several values (chips, checkboxes) are listed in MULTI.
"""

from __future__ import annotations

import re
from typing import Any

MULTI = {"contributors", "content.modalities", "content.tags", "outputs.related_datasets"}
BOOL = {"is_backup"}
URL_RE = re.compile(r"^([a-z][a-z0-9+.-]*://|www\.)", re.I)


def _set(root: dict, parts: list[str], value: Any) -> None:
    node = root
    for i, p in enumerate(parts):
        last = i == len(parts) - 1
        key: Any = int(p) if p.isdigit() else p
        if last:
            node[key] = value
        else:
            node = node.setdefault(key, {})


def _listify(v: Any) -> Any:
    """Dicts with integer keys (from `x.0.y` names) become lists, in index order."""
    if isinstance(v, dict):
        if v and all(isinstance(k, int) for k in v):
            return [_listify(v[k]) for k in sorted(v)]
        return {k: _listify(x) for k, x in v.items()}
    return v


def _empty(v: Any) -> bool:
    if isinstance(v, dict):
        return all(_empty(x) for k, x in v.items() if k not in ("kind", "is_backup"))
    if isinstance(v, list):
        return all(_empty(x) for x in v)
    return v is None or (isinstance(v, str) and not v.strip())


def parse_dataset_form(items: list[tuple[str, str]]) -> dict:
    """Form items -> nested dict suitable for `Dataset.model_validate`."""
    data: dict = {}
    multi: dict[str, list[str]] = {}
    for name, value in items:
        if name.startswith("_"):
            continue  # control fields such as _base_sha
        value = value.strip() if isinstance(value, str) else value
        if name in MULTI:
            if value:
                multi.setdefault(name, []).append(value)
            continue
        parts = name.split(".")
        if parts[-1] in BOOL:
            value = value in ("on", "true", "1", "yes")
        _set(data, parts, value)
    for name in MULTI:
        _set(data, name.split("."), list(dict.fromkeys(multi.get(name, []))))
    data = _listify(data)

    # Repeatable groups: drop blank rows; locations have a single "link or path" input.
    locs = []
    for loc in data.get("locations", []):
        if _empty(loc):
            continue
        target = (loc.pop("target", "") or "").strip()
        if target:
            loc["url" if URL_RE.match(target) else "path"] = target
        locs.append(loc)
    data["locations"] = locs
    outputs = data.setdefault("outputs", {})
    for key in ("publications", "preprints", "code"):
        outputs[key] = [x for x in outputs.get(key, []) if not _empty(x)]
    return data


def get(data: Any, path: str, default: Any = None) -> Any:
    """`get(d, "content.tags")` for templates; works on dicts and lists."""
    node = data
    for p in path.split("."):
        if isinstance(node, dict):
            node = node.get(p)
        elif isinstance(node, list) and p.isdigit() and int(p) < len(node):
            node = node[int(p)]
        else:
            return default
        if node is None:
            return default
    return node
