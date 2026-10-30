"""Field-level diffs and three-way merges of dataset records (as plain dicts)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Human-readable labels for fields, used in history and commit messages.
LABELS: dict[str, str] = {
    "id": "ID",
    "title": "Title",
    "status": "Status",
    "summary": "Summary",
    "contact": "Contact person",
    "contributors": "Contributors",
    "collected": "Collection period",
    "collected.start": "Collection start",
    "collected.end": "Collection end",
    "content": "Content",
    "content.modalities": "Modalities",
    "content.n_participants": "Participants",
    "content.population": "Population",
    "content.paradigm": "Paradigm",
    "content.tags": "Tags",
    "legal": "Legal",
    "legal.ethics_ref": "Ethics approval",
    "legal.data_protection_ref": "Data protection ref.",
    "legal.consent_scope": "Consent scope",
    "legal.sharing": "Sharing",
    "legal.delete_by": "Delete by",
    "locations": "Storage locations",
    "outputs": "Outputs",
    "outputs.publications": "Publications",
    "outputs.preprints": "Preprints",
    "outputs.code": "Code",
    "outputs.related_datasets": "Related datasets",
    "notes": "Notes",
}

GROUPS = ("collected", "content", "legal", "outputs")

Path = tuple[str, ...]


def label(path: str) -> str:
    return LABELS.get(path, path.split(".")[-1].replace("_", " ").capitalize())


def fields(data: dict) -> dict[Path, Any]:
    """Split a record into fields: top-level keys, plus sub-keys of the groups."""
    out: dict[Path, Any] = {}
    for k, v in data.items():
        if k in GROUPS and isinstance(v, dict):
            for sk, sv in v.items():
                out[(k, sk)] = sv
        else:
            out[(k,)] = v
    return out


def unfields(flat: dict[Path, Any], order: list[str]) -> dict:
    data: dict = {}
    for path, v in flat.items():
        if v is None:
            continue
        if len(path) == 2:
            data.setdefault(path[0], {})[path[1]] = v
        else:
            data[path[0]] = v
    return {k: data[k] for k in order if k in data} | {k: v for k, v in data.items() if k not in order}


def summarize_item(v: Any) -> str:
    """One-line description of a list item (e.g. a location or publication)."""
    if isinstance(v, dict):
        bits = [str(v.get(k)) for k in ("kind", "title", "doi", "url", "path", "note") if v.get(k)]
        if v.get("is_backup"):
            bits.append("(backup)")
        return " · ".join(bits) or "(empty)"
    return str(v)


@dataclass
class Change:
    path: str
    label: str
    old: Any = None
    new: Any = None
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def is_list(self) -> bool:
        return isinstance(self.old, list) or isinstance(self.new, list)


def diff(old: dict | None, new: dict | None) -> list[Change]:
    a, b = fields(old or {}), fields(new or {})
    changes = []
    for path in list(dict.fromkeys([*a, *b])):
        va, vb = a.get(path), b.get(path)
        if va == vb:
            continue
        p = ".".join(path)
        c = Change(p, label(p), va, vb)
        if isinstance(va, list) or isinstance(vb, list):
            sa = [summarize_item(x) for x in va or []]
            sb = [summarize_item(x) for x in vb or []]
            c.added = [x for x in sb if x not in sa]
            c.removed = [x for x in sa if x not in sb]
            if not c.added and not c.removed:
                c.added = ["(reordered or edited)"]
        changes.append(c)
    return changes


class MergeConflict(Exception):
    def __init__(self, paths: list[Path], theirs: dict, mine: dict):
        self.paths = paths
        self.theirs = theirs
        self.mine = mine
        super().__init__(", ".join(".".join(p) for p in paths))


def merge3(base: dict, theirs: dict, mine: dict, prefer_mine: bool = False) -> dict:
    """Apply my changes (base -> mine) on top of theirs, field by field."""
    fb, ft, fm = fields(base), fields(theirs), fields(mine)
    all_paths = list(dict.fromkeys([*ft, *fm, *fb]))
    mine_changed = {p for p in all_paths if fb.get(p) != fm.get(p)}
    theirs_changed = {p for p in all_paths if fb.get(p) != ft.get(p)}
    clash = [p for p in all_paths if p in mine_changed & theirs_changed and ft.get(p) != fm.get(p)]
    if clash and not prefer_mine:
        raise MergeConflict(clash, theirs, mine)
    out = dict(ft)
    for p in mine_changed:
        out[p] = fm.get(p)
    return unfields(out, list(mine.keys()) + list(theirs.keys()))
