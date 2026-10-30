#!/usr/bin/env python3
"""Check dataset YAML files for the lab dataset catalog.

Usage:  python scripts/validate.py my-dataset.yaml [more.yaml ...]
Needs:  Python 3.9+ and PyYAML (pip install pyyaml)

Reads the schema and the lab's lists (people, modalities, tags, existing datasets)
from ../reference/. Exit code 0 = valid (warnings are allowed), 1 = errors.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is missing. Install it with: pip install pyyaml")

REF = Path(__file__).resolve().parent.parent / "reference"
PARTIAL_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
FULL_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DOI = re.compile(r"^10\.\d{4,9}/\S+$")
TAG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def load(name):
    with open(REF / name, encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else yaml.safe_load(f)


def plain(v):
    """YAML dates -> ISO strings, so they can be checked like the app does."""
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [plain(x) for x in v]
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()[:10]
    return v


class Checker:
    def __init__(self):
        self.schema = load("schema.json")
        self.people = {p["id"]: p for p in load("people.yaml") or []}
        self.modalities = {m["id"] for m in load("modalities.yaml") or []}
        self.tags = set(load("tags.yaml") or [])
        self.datasets = {d["id"]: d.get("title", "") for d in load("datasets.yaml") or []}
        self.errors: list[str] = []
        self.warnings: list[str] = []

    # --- generic part: the subset of JSON Schema that the app's schema uses ---
    def resolve(self, s):
        while "$ref" in s:
            s = self.schema["$defs"][s["$ref"].split("/")[-1]]
        return s

    def check(self, v, s, path):
        s = self.resolve(s)
        if "anyOf" in s:
            opts = [self.resolve(o) for o in s["anyOf"]]
            if v is None and any(o.get("type") == "null" for o in opts):
                return
            s = next(o for o in opts if o.get("type") != "null")
        t = s.get("type")
        if s.get("format") == "date" and not isinstance(v, str):
            self.errors.append(f"{path}: use a full date like 2034-12-31")
            return
        types = {"string": str, "integer": int, "boolean": bool, "array": list, "object": dict}
        if t in types and (not isinstance(v, types[t]) or (t == "integer" and isinstance(v, bool))):
            want = {"string": "text", "integer": "a whole number", "boolean": "true or false",
                    "array": "a list", "object": "a mapping (key: value)"}[t]
            self.errors.append(f"{path}: should be {want}, got {v!r}")
            return
        if "enum" in s and v not in s["enum"]:
            self.errors.append(f"{path}: '{v}' is not allowed; use one of: {', '.join(s['enum'])}")
        if "pattern" in s and isinstance(v, str) and not re.search(s["pattern"], v):
            self.errors.append(f"{path}: '{v}' has the wrong format")
        if "minLength" in s and isinstance(v, str) and len(v) < s["minLength"]:
            self.errors.append(f"{path}: too short (at least {s['minLength']} characters)")
        if "minimum" in s and isinstance(v, int) and v < s["minimum"]:
            self.errors.append(f"{path}: must be {s['minimum']} or more")
        if s.get("format") == "date" and isinstance(v, str) and not FULL_DATE.match(v):
            self.errors.append(f"{path}: use a full date like 2034-12-31")
        if t == "array":
            for i, x in enumerate(v):
                self.check(x, s.get("items", {}), f"{path}[{i}]")
        if t == "object" or "properties" in s:
            props = s.get("properties", {})
            for k in s.get("required", []):
                if k not in v:
                    self.errors.append(f"{path + '.' if path else ''}{k}: required field is missing")
            for k, x in v.items():
                p = f"{path}.{k}" if path else k
                if k not in props:
                    self.errors.append(f"{p}: unknown field (allowed: {', '.join(props)})")
                elif x is not None:
                    self.check(x, props[k], p)

    # --- lab-specific rules (what the schema cannot express) ---
    def lab_rules(self, d, filename):
        did = d.get("id")
        if isinstance(did, str) and re.match(self.schema["properties"]["id"]["pattern"], did):
            if filename and Path(filename).stem != did:
                self.warnings.append(f"file name should be {did}.yaml")
            if did in self.datasets:
                self.errors.append(f"id: '{did}' already exists ({self.datasets[did]}); choose another id")
        if "status" not in d:
            self.warnings.append("status: not set, 'planned' will be used")
        known = ", ".join(sorted(self.people)[:5]) + ", …"
        if isinstance(d.get("contact"), str) and d["contact"] not in self.people:
            self.errors.append(f"contact: unknown person id '{d['contact']}' (see reference/people.yaml, e.g. {known})")
        for c in d.get("contributors") or []:
            if c not in self.people:
                self.errors.append(f"contributors: unknown person id '{c}'")
        for k in ("start", "end"):
            v = (d.get("collected") or {}).get(k)
            if v is not None and not (isinstance(v, (str, int)) and PARTIAL_DATE.match(str(v))):
                self.errors.append(f"collected.{k}: use 2019, 2019-02 or 2019-02-15")
        content = d.get("content") or {}
        for m in content.get("modalities") or []:
            if m not in self.modalities:
                self.errors.append(f"content.modalities: '{m}' is not allowed; use: {', '.join(sorted(self.modalities))}")
        for t in content.get("tags") or []:
            if not isinstance(t, str) or not TAG.match(t):
                self.errors.append(f"content.tags: '{t}' should be lowercase words joined by dashes")
            elif t not in self.tags:
                self.warnings.append(f"content.tags: '{t}' is a new tag (fine, it will be added to the list)")
        locs = d.get("locations") or []
        for i, loc in enumerate(locs):
            if isinstance(loc, dict) and not (loc.get("url") or loc.get("path")):
                self.errors.append(f"locations[{i}]: needs a url or a path")
        if locs and not any(isinstance(x, dict) and x.get("is_backup") for x in locs):
            self.warnings.append("locations: no location is marked as backup (is_backup: true)")
        outputs = d.get("outputs") or {}
        for key in ("publications", "preprints"):
            for i, p in enumerate(outputs.get(key) or []):
                doi = p.get("doi") if isinstance(p, dict) else None
                if doi and not DOI.match(str(doi)):
                    self.errors.append(f"outputs.{key}[{i}].doi: write the bare DOI, like 10.1234/abcd (no https://doi.org/)")
                if isinstance(p, dict) and not (p.get("doi") or p.get("title")):
                    self.errors.append(f"outputs.{key}[{i}]: needs at least a doi or a title")
        for r in outputs.get("related_datasets") or []:
            if r not in self.datasets:
                self.errors.append(f"outputs.related_datasets: unknown dataset id '{r}' (see reference/datasets.yaml)")

    def run(self, filename: str) -> bool:
        self.errors, self.warnings = [], []
        try:
            with open(filename, encoding="utf-8") as f:
                data = plain(yaml.safe_load(f))
        except yaml.YAMLError as e:
            self.errors.append(f"not valid YAML: {e}")
            data = None
        if data is not None and not isinstance(data, dict):
            self.errors.append("the file should contain one dataset (a mapping with id, title, …)")
        elif data is not None:
            self.check(data, self.schema, "")
            self.lab_rules(data, filename)
        print(("✓ " if not self.errors else "✗ ") + filename)
        for e in self.errors:
            print(f"  error:   {e}")
        for w in self.warnings:
            print(f"  warning: {w}")
        return not self.errors


def main(argv):
    if not argv:
        sys.exit(__doc__)
    checker = Checker()
    ok = all([checker.run(f) for f in argv])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
