"""The catalog: data repo parsed into memory, plus all write operations (= git commits)."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from . import diffing, yamlio
from .gitrepo import Commit, GitRepo, blob_sha
from .models import Dataset, Modality, Person

log = logging.getLogger(__name__)

DATASETS = "datasets"
PEOPLE = "people.yaml"
TAGS = "vocab/tags.yaml"
MODALITIES = "vocab/modalities.yaml"
SCHEMA = "schema/dataset.schema.json"

DEFAULT_MODALITIES = [
    ("eeg", "EEG"),
    ("meg", "MEG"),
    ("fmri", "fMRI"),
    ("mri", "Structural MRI"),
    ("tms", "TMS"),
    ("eye-tracking", "Eye-tracking / pupillometry"),
    ("behaviour", "Behaviour"),
    ("questionnaire", "Questionnaire"),
    ("physiology", "Physiology (ECG, EDA, …)"),
    ("other", "Other"),
]


class StoreError(Exception):
    """A user-facing problem with a write (validation, unknown references, …)."""

    def __init__(self, message: str, errors: dict[str, str] | None = None):
        super().__init__(message)
        self.errors = errors or {}


@dataclass
class Conflict(Exception):
    """Someone changed the same fields since the form was loaded."""

    dataset_id: str
    changes_theirs: list[diffing.Change]
    paths: list[str]
    theirs: dict
    mine: dict
    current_sha: str
    last_commit: Commit | None


@dataclass
class HistoryEntry:
    commit: Commit
    changes: list[diffing.Change]
    created: bool = False


@dataclass
class SaveResult:
    dataset: Dataset
    commit: str | None
    merged: bool = False  # True if changes by others were merged in
    new_tags: list[str] = field(default_factory=list)


def validation_errors(e: ValidationError) -> dict[str, str]:
    out = {}
    for err in e.errors():
        loc = ".".join(str(x) for x in err["loc"])
        msg = err["msg"].removeprefix("Value error, ")
        if err["type"] == "string_pattern_mismatch" and loc == "id":
            msg = "use the form YYYY-short-name (lowercase letters, digits and dashes)"
        elif err["type"] == "missing":
            msg = "this field is required"
        out[loc] = msg
    return out


class Catalog:
    def __init__(self, root: Path, git: GitRepo):
        self.root = Path(root)
        self.git = git
        self.lock = threading.RLock()
        self.datasets: dict[str, Dataset] = {}
        self.shas: dict[str, str] = {}
        self.broken: dict[str, str] = {}  # file name -> problem
        self.people: list[Person] = []
        self.tags: list[str] = []
        self.modalities: list[Modality] = []
        self._signature = None

    # --- loading ---------------------------------------------------------
    def _read(self, rel: str) -> str | None:
        p = self.root / rel
        return p.read_text(encoding="utf-8") if p.exists() else None

    def _signature_now(self):
        files = sorted(self.root.glob(f"{DATASETS}/*.yaml")) + [
            self.root / PEOPLE,
            self.root / TAGS,
            self.root / MODALITIES,
        ]
        return (self.git.head(), tuple((f.name, f.stat().st_mtime_ns) for f in files if f.exists()))

    def refresh(self) -> None:
        """Reload if anything changed on disk (commits or hand edits)."""
        with self.lock:
            sig = self._signature_now()
            if sig != self._signature:
                self.reload()
                self._signature = sig

    def reload(self) -> None:
        with self.lock:
            self.people = [Person.model_validate(p) for p in yamlio.plain(yamlio.load(self._read(PEOPLE) or "[]")) or []]
            self.tags = sorted(set(yamlio.plain(yamlio.load(self._read(TAGS) or "[]")) or []))
            self.modalities = [
                Modality.model_validate(m) for m in yamlio.plain(yamlio.load(self._read(MODALITIES) or "[]")) or []
            ]
            datasets, shas, broken = {}, {}, {}
            for f in sorted((self.root / DATASETS).glob("*.yaml")):
                raw = f.read_bytes()
                try:
                    ds = Dataset.model_validate(yamlio.plain(yamlio.load(raw.decode("utf-8"))))
                    if ds.id != f.stem:
                        raise ValueError(f"id '{ds.id}' does not match the file name")
                except (ValidationError, ValueError, Exception) as e:  # noqa: BLE001
                    broken[f.name] = str(e)
                    log.warning("could not load %s: %s", f.name, e)
                    continue
                datasets[ds.id] = ds
                shas[ds.id] = blob_sha(raw)
            self.datasets, self.shas, self.broken = datasets, shas, broken

    # --- lookups ---------------------------------------------------------
    def person(self, pid: str | None) -> Person | None:
        return next((p for p in self.people if p.id == pid), None)

    def person_name(self, pid: str | None) -> str:
        p = self.person(pid)
        return p.name if p else (pid or "")

    def modality_label(self, mid: str) -> str:
        m = next((m for m in self.modalities if m.id == mid), None)
        return m.label if m else mid

    def path_of(self, dataset_id: str) -> str:
        return f"{DATASETS}/{dataset_id}.yaml"

    def file_text(self, dataset_id: str) -> str | None:
        return self._read(self.path_of(dataset_id))

    # --- validation ------------------------------------------------------
    def check_refs(self, ds: Dataset) -> dict[str, str]:
        errors = {}
        ids = {p.id for p in self.people}
        if ds.contact not in ids:
            errors["contact"] = f"unknown person '{ds.contact}'"
        unknown = [c for c in ds.contributors if c not in ids]
        if unknown:
            errors["contributors"] = "unknown people: " + ", ".join(unknown)
        mods = {m.id for m in self.modalities}
        bad = [m for m in ds.content.modalities if m not in mods]
        if bad:
            errors["content.modalities"] = "unknown modalities: " + ", ".join(bad)
        rel = [r for r in ds.outputs.related_datasets if r not in self.datasets or r == ds.id]
        if rel:
            errors["outputs.related_datasets"] = "unknown datasets: " + ", ".join(rel)
        return errors

    def parse(self, data: dict) -> Dataset:
        try:
            ds = Dataset.model_validate(data)
        except ValidationError as e:
            raise StoreError("Some fields need attention.", validation_errors(e)) from e
        errors = self.check_refs(ds)
        if errors:
            raise StoreError("Some fields need attention.", errors)
        return ds

    # --- writing ---------------------------------------------------------
    def _write(self, rel: str, text: str) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def _commit(self, paths: list[str], message: str, author: Person) -> str:
        email = author.email or f"{author.id}@users.noreply.lab"
        sha = self.git.commit(paths, message, author.name, email)
        try:
            self.git.push()
        except Exception as e:  # noqa: BLE001
            log.error("push failed: %s", e)
        return sha

    def _add_tags(self, tags: list[str]) -> list[str]:
        new = sorted({t for t in tags if t not in self.tags})
        if new:
            self._write(TAGS, yamlio.render(sorted(set(self.tags) | set(new)), self._read(TAGS)))
        return new

    def save_dataset(
        self,
        data: dict,
        author: Person,
        base_sha: str | None = None,
        create: bool = False,
        prefer_mine: bool = False,
        message: str | None = None,
    ) -> SaveResult:
        """Validate and commit a dataset. `base_sha` = blob SHA when the form was loaded."""
        with self.lock:
            try:
                self.git.pull()
            except Exception as e:  # noqa: BLE001
                log.error("pull failed: %s", e)
            self.refresh()
            ds = self.parse(data)
            path = self.path_of(ds.id)
            old_text = self._read(path)
            if create and old_text is not None:
                raise StoreError("This ID is already taken.", {"id": "a dataset with this ID already exists"})
            if not create and old_text is None:
                raise StoreError("This dataset does not exist (any more).")

            new_data = ds.to_yaml_data()
            merged = False
            if old_text is not None:
                current_sha = blob_sha(old_text.encode("utf-8"))
                theirs = Dataset.model_validate(yamlio.plain(yamlio.load(old_text))).to_yaml_data()
                if base_sha and base_sha != current_sha:
                    base_text = self.git.cat_blob(base_sha)
                    base = (
                        Dataset.model_validate(yamlio.plain(yamlio.load(base_text))).to_yaml_data()
                        if base_text
                        else {}
                    )
                    try:
                        new_data = diffing.merge3(base, theirs, new_data, prefer_mine=prefer_mine)
                    except diffing.MergeConflict as mc:
                        commits = self.git.log(path, limit=1)
                        raise Conflict(
                            ds.id,
                            diffing.diff(base, theirs),
                            [".".join(p) for p in mc.paths],
                            theirs,
                            new_data,
                            current_sha,
                            commits[0] if commits else None,
                        ) from None
                    ds = self.parse(new_data)
                    new_data = ds.to_yaml_data()
                    merged = True
                changes = diffing.diff(theirs, new_data)
                if not changes:
                    return SaveResult(ds, None, merged)
                msg = message or f"Update {ds.id}: " + ", ".join(c.label.lower() for c in changes[:6])
            else:
                msg = message or f"Add {ds.id}: {ds.title}"

            new_tags = self._add_tags(ds.content.tags)
            if new_tags:
                msg += "\n\nNew tags: " + ", ".join(new_tags)
            self._write(path, yamlio.render(new_data, old_text))
            sha = self._commit([path] + ([TAGS] if new_tags else []), msg, author)
            self.refresh()
            return SaveResult(self.datasets[ds.id], sha, merged, new_tags)

    def set_status(self, dataset_id: str, status: str, author: Person) -> SaveResult:
        data = self.datasets[dataset_id].to_yaml_data()
        data["status"] = status
        verb = "Retire" if status == "retired" else "Reactivate"
        return self.save_dataset(data, author, self.shas.get(dataset_id), message=f"{verb} {dataset_id}")

    def restore(self, dataset_id: str, rev: str, author: Person) -> SaveResult:
        text = self.git.show(rev, self.path_of(dataset_id))
        if text is None:
            raise StoreError("That version could not be found.")
        data = Dataset.model_validate(yamlio.plain(yamlio.load(text))).to_yaml_data()
        return self.save_dataset(
            data,
            author,
            self.shas.get(dataset_id),
            prefer_mine=True,
            message=f"Restore {dataset_id} to version {rev[:7]}",
        )

    def add_person(self, data: dict, author: Person) -> Person:
        with self.lock:
            try:
                person = Person.model_validate(data)
            except ValidationError as e:
                raise StoreError("Please check the fields.", validation_errors(e)) from e
            if self.person(person.id):
                raise StoreError("This ID is already taken.", {"id": "someone already has this ID"})
            people = [
                p.model_dump(exclude_defaults=True) | {"active": p.active} for p in [*self.people, person]
            ]
            self._write(PEOPLE, yamlio.render(people, self._read(PEOPLE)))
            self._commit([PEOPLE], f"Add person {person.id}: {person.name}", author)
            self.refresh()
            return person

    # --- history ---------------------------------------------------------
    def history(self, dataset_id: str) -> list[HistoryEntry]:
        path = self.path_of(dataset_id)
        commits = self.git.log(path)
        versions = []
        for c in commits:
            text = self.git.show(c.sha, path)
            try:
                versions.append(yamlio.plain(yamlio.load(text)) if text else None)
            except Exception:  # noqa: BLE001
                versions.append(None)
        entries = []
        for i, c in enumerate(commits):
            prev = versions[i + 1] if i + 1 < len(versions) else None
            entries.append(HistoryEntry(c, diffing.diff(prev, versions[i]), created=prev is None))
        return entries

    def recent(self, limit: int = 60) -> list[tuple[Commit, list[str]]]:
        out = []
        for c in self.git.log(limit=limit):
            ids = [Path(f).stem for f in c.files if f.startswith(DATASETS + "/")]
            out.append((c, ids))
        return out

    def last_changes(self) -> dict[str, Commit]:
        """Most recent commit per dataset (for 'recently updated' sorting)."""
        out: dict[str, Commit] = {}
        for c in self.git.log(limit=2000):
            for f in c.files:
                if f.startswith(DATASETS + "/"):
                    out.setdefault(Path(f).stem, c)
        return out


def init_data_repo(root: Path, owner: Person) -> None:
    """Create a fresh catalog data repo with vocabularies, schema and one person."""
    root.mkdir(parents=True, exist_ok=True)
    (root / DATASETS).mkdir(exist_ok=True)
    (root / DATASETS / ".gitkeep").touch()
    git = GitRepo(root, "Lab catalog", "catalog@lab.local")
    if not git.is_repo():
        git.run("init", "-q", "-b", "main")
    files = {
        PEOPLE: yamlio.render([owner.model_dump(exclude_defaults=True) | {"active": True}]),
        TAGS: yamlio.render(["attention", "memory", "mind-wandering", "pilot", "resting-state"]),
        MODALITIES: yamlio.render([{"id": i, "label": label} for i, label in DEFAULT_MODALITIES]),
        SCHEMA: json.dumps(Dataset.model_json_schema(), indent=2) + "\n",
        "README.md": README,
    }
    for rel, text in files.items():
        p = root / rel
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
    if git.head() is None:
        email = owner.email or f"{owner.id}@users.noreply.lab"
        git.commit(["."], "Initialise lab dataset catalog", owner.name, email)


README = """\
# Lab dataset catalog

One YAML file per dataset in `datasets/` (file name = dataset id). Most people edit
through the web app; if you edit by hand, check your file with `labcat validate`.

- `people.yaml`: lab members and alumni; datasets refer to people by `id`.
- `vocab/tags.yaml`, `vocab/modalities.yaml`: controlled vocabularies.
- `schema/dataset.schema.json`: generated from the app (`labcat schema`).
"""
