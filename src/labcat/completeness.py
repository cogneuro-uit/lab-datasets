"""How complete is a dataset record? Used to nudge people to fill in the rest."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Dataset


@dataclass
class Check:
    label: str
    done: bool
    section: str  # anchor of the form section where it is filled in


def checks(ds: Dataset) -> list[Check]:
    c = ds.content
    out = [
        Check("Short summary", bool(ds.summary), "basics"),
        Check("When the data was collected", bool(ds.collected.start), "people"),
        Check("Slack channel for discussion", bool(ds.slack.channel), "people"),
        Check("Modalities", bool(c.modalities), "content"),
        Check("Number of participants", c.n_participants is not None, "content"),
        Check("Population or paradigm", bool(c.population or c.paradigm), "content"),
        Check("Tags", bool(c.tags), "content"),
        Check("Where the data is stored", bool(ds.locations), "locations"),
        Check("A backup copy", any(loc.is_backup for loc in ds.locations), "locations"),
        Check("Ethics approval reference", bool(ds.legal.ethics_ref), "legal"),
        Check("Sharing level", bool(ds.legal.sharing), "legal"),
    ]
    if ds.status in ("published", "archived"):
        out.append(Check("Publication or preprint", bool(ds.outputs.publications or ds.outputs.preprints), "outputs"))
    return out


def score(ds: Dataset) -> int:
    cs = checks(ds)
    return round(100 * sum(c.done for c in cs) / len(cs))
