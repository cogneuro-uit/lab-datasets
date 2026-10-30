"""Look up publication details for a DOI (Crossref first, then DataCite)."""

from __future__ import annotations

import logging

import httpx

from .models import _normalize_doi

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "labcat/0.1 (lab dataset catalog)"}


def _authors(names: list[str], limit: int = 6) -> str:
    names = [n for n in names if n]
    if len(names) > limit:
        return ", ".join(names[:limit]) + ", et al."
    return ", ".join(names)


def _initials(given: str | None) -> str:
    if not given:
        return ""
    return " ".join(p[0] + "." for p in given.replace("-", " ").split() if p)


def _crossref(doi: str, client: httpx.Client) -> dict | None:
    r = client.get(f"https://api.crossref.org/works/{doi}")
    if r.status_code != 200:
        return None
    m = r.json()["message"]
    authors = []
    for a in m.get("author", []):
        if a.get("family"):
            authors.append(f"{a['family']}, {_initials(a.get('given'))}".strip(", "))
        elif a.get("name"):
            authors.append(a["name"])
    parts = (m.get("issued") or m.get("published") or {}).get("date-parts") or [[None]]
    venue = (
        (m.get("container-title") or [None])[0]
        or m.get("group-title")
        or ((m.get("institution") or [{}])[0].get("name"))
    )
    return {
        "doi": doi,
        "title": (m.get("title") or [None])[0],
        "authors": _authors(authors),
        "venue": venue or m.get("publisher"),
        "year": parts[0][0],
        "url": f"https://doi.org/{doi}",
        "is_preprint": m.get("type") == "posted-content" or m.get("subtype") == "preprint",
    }


def _datacite(doi: str, client: httpx.Client) -> dict | None:
    r = client.get(f"https://api.datacite.org/dois/{doi}")
    if r.status_code != 200:
        return None
    a = r.json()["data"]["attributes"]
    return {
        "doi": doi,
        "title": (a.get("titles") or [{}])[0].get("title"),
        "authors": _authors([c.get("name") for c in a.get("creators", [])]),
        "venue": a.get("publisher") if isinstance(a.get("publisher"), str) else (a.get("publisher") or {}).get("name"),
        "year": a.get("publicationYear"),
        "url": f"https://doi.org/{doi}",
        "is_preprint": (a.get("types") or {}).get("resourceTypeGeneral") == "Preprint",
    }


def lookup(raw: str) -> dict:
    """Return publication metadata, or {"error": "..."}."""
    try:
        doi = _normalize_doi(raw)
    except ValueError as e:
        return {"error": str(e)}
    if not doi:
        return {"error": "Please enter a DOI."}
    try:
        with httpx.Client(timeout=8, headers=HEADERS, follow_redirects=True) as client:
            return _crossref(doi, client) or _datacite(doi, client) or {
                "error": "This DOI was not found at Crossref or DataCite.",
                "doi": doi,
            }
    except httpx.HTTPError as e:
        log.warning("DOI lookup failed: %s", e)
        return {"error": "Could not reach the DOI service. You can fill in the details by hand.", "doi": doi}
