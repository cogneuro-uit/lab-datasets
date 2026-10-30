"""Pydantic models: the single definition of the catalog schema.

The JSON Schema used by CI is generated from these (`labcat schema`).
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

ID_PATTERN = r"^\d{4}-[a-z0-9]+(?:-[a-z0-9]+)*$"
PERSON_ID_PATTERN = r"^[a-z][a-z0-9_-]*$"

Status = Literal["planned", "collecting", "analysing", "published", "archived", "retired"]
Sharing = Literal["open", "on-request", "internal", "restricted"]
LocationKind = Literal["teams", "server", "osf", "zenodo", "openneuro", "figshare", "other"]

STATUSES: dict[str, str] = {
    "planned": "Planned",
    "collecting": "Collecting data",
    "analysing": "Analysing",
    "published": "Published",
    "archived": "Archived",
    "retired": "Retired",
}
SHARING: dict[str, str] = {
    "open": "Open",
    "on-request": "On request",
    "internal": "Lab internal",
    "restricted": "Restricted",
}
LOCATION_KINDS: dict[str, str] = {
    "teams": "Teams / SharePoint",
    "server": "Lab server",
    "osf": "OSF",
    "zenodo": "Zenodo",
    "openneuro": "OpenNeuro",
    "figshare": "Figshare",
    "other": "Other",
}


def _blank_to_none(v):
    if isinstance(v, str) and not v.strip():
        return None
    return v


def _partial_date(v):
    """Accept YYYY, YYYY-MM or YYYY-MM-DD (YAML may hand us a date object)."""
    v = _blank_to_none(v)
    if v is None:
        return None
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()[:10]
    if isinstance(v, int):
        v = str(v)
    if isinstance(v, str) and re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", v.strip()):
        return v.strip()
    raise ValueError("use a year (2019), a month (2019-02) or a date (2019-02-15)")


def _normalize_doi(v):
    v = _blank_to_none(v)
    if v is None:
        return None
    v = v.strip()
    v = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", v, flags=re.I)
    v = re.sub(r"^doi:\s*", "", v, flags=re.I)
    if not re.match(r"^10\.\d{4,9}/\S+$", v):
        raise ValueError("this does not look like a DOI (it should start with 10.)")
    return v


OptStr = Annotated[str | None, BeforeValidator(_blank_to_none)]
PartialDate = Annotated[str | None, BeforeValidator(_partial_date)]
Doi = Annotated[str | None, BeforeValidator(_normalize_doi)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Period(Model):
    start: PartialDate = None
    end: PartialDate = None


class Content(Model):
    modalities: list[str] = []
    n_participants: Annotated[int | None, BeforeValidator(_blank_to_none), Field(ge=0)] = None
    population: OptStr = None
    paradigm: OptStr = None
    tags: list[str] = []


class Legal(Model):
    ethics_ref: OptStr = None
    data_protection_ref: OptStr = None
    consent_scope: OptStr = None
    sharing: Annotated[Sharing | None, BeforeValidator(_blank_to_none)] = None
    delete_by: Annotated[dt.date | None, BeforeValidator(_blank_to_none)] = None


class Location(Model):
    kind: LocationKind = "other"
    url: OptStr = None
    path: OptStr = None
    note: OptStr = None
    is_backup: bool = False

    def target(self) -> str | None:
        return self.url or self.path


class Publication(Model):
    doi: Doi = None
    title: OptStr = None
    authors: OptStr = None
    venue: OptStr = None
    year: Annotated[int | None, BeforeValidator(_blank_to_none)] = None
    url: OptStr = None


class CodeRepo(Model):
    url: str
    note: OptStr = None


class Outputs(Model):
    publications: list[Publication] = []
    preprints: list[Publication] = []
    code: list[CodeRepo] = []
    related_datasets: list[str] = []


class Dataset(Model):
    id: Annotated[str, Field(pattern=ID_PATTERN)]
    title: Annotated[str, Field(min_length=3)]
    status: Status = "planned"
    summary: OptStr = None
    contact: Annotated[str, Field(min_length=1)]
    contributors: list[str] = []
    collected: Period = Period()
    content: Content = Content()
    legal: Legal = Legal()
    locations: list[Location] = []
    outputs: Outputs = Outputs()
    notes: OptStr = None

    @field_validator("contributors", mode="after")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(x for x in v if x))

    @property
    def year(self) -> int | None:
        if self.collected.start:
            return int(self.collected.start[:4])
        return int(self.id[:4])

    def to_yaml_data(self) -> dict:
        """Plain data for YAML, without empty values, in schema field order."""
        return _prune(self.model_dump(mode="json"))


def _prune(v):
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            x = _prune(x)
            if x is None or x == [] or x == {} or x == "" or (k == "is_backup" and x is False):
                continue
            out[k] = x
        return out
    if isinstance(v, list):
        return [_prune(x) for x in v]
    return v


class Person(Model):
    id: Annotated[str, Field(pattern=PERSON_ID_PATTERN)]
    name: Annotated[str, Field(min_length=1)]
    email: OptStr = None
    orcid: OptStr = None
    slack_id: OptStr = None
    active: bool = True


class Modality(Model):
    id: Annotated[str, Field(pattern=PERSON_ID_PATTERN)]
    label: str
