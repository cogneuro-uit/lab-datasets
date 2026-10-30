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


def _slack_channel(v):
    """A channel name (with or without #) or a link copied from Slack."""
    v = _blank_to_none(v)
    if v is None:
        return None
    v = str(v).strip()
    if re.match(r"^https?://", v):
        if "slack.com/" not in v:
            raise ValueError("this is not a Slack link")
        return v
    v = v.lstrip("#").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", v):
        raise ValueError("use the channel name, e.g. rlmw-project (lowercase, no spaces)")
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
    n_participants: Annotated[Annotated[int, Field(ge=0)] | None, BeforeValidator(_blank_to_none)] = None
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


class Canvas(Model):
    url: Annotated[str, Field(pattern=r"^https?://")]
    title: OptStr = None


class SlackInfo(Model):
    channel: Annotated[str | None, BeforeValidator(_slack_channel)] = None
    canvases: list[Canvas] = []


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
    slack: SlackInfo = SlackInfo()
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
    slack_handle: OptStr = None
    active: bool = True


class Modality(Model):
    id: Annotated[str, Field(pattern=PERSON_ID_PATTERN)]
    label: str


def slack_channel_url(channel: str | None, workspace: str | None) -> str | None:
    """A link that opens the channel in Slack (by name, via app_redirect)."""
    if not channel:
        return None
    if channel.startswith("http"):
        return channel
    if workspace:
        return f"{workspace.rstrip('/')}/app_redirect?channel={channel}"
    return None


class Site(BaseModel):
    """Who the catalog belongs to (site.yaml in the data repo). All optional."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    name: str = "Our lab"
    short_name: str | None = None
    catalog_title: str = "Lab datasets"
    department: OptStr = None
    institution: OptStr = None
    city: OptStr = None
    website: OptStr = None
    slack_workspace: OptStr = None  # e.g. https://cogneuro-uit.slack.com
    contact: OptStr = None
    logo: OptStr = None
    favicon: OptStr = None
    about: OptStr = None
    methods: list[str] = []
