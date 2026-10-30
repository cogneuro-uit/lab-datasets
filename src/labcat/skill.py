"""Build the downloadable AI-agent skill (a zip) with the catalog's current lists."""

from __future__ import annotations

import datetime as dt
import io
import json
import zipfile
from pathlib import Path
from string import Template

from . import yamlio
from .models import Dataset

SKILL_DIR = Path(__file__).parent / "skill"
NAME = "lab-dataset-yaml"


def build_zip(cat, catalog_url: str) -> bytes:
    files: dict[str, str] = {}
    for f in SKILL_DIR.rglob("*"):
        if f.is_file() and "__pycache__" not in f.parts:
            files[f.relative_to(SKILL_DIR).as_posix()] = f.read_text(encoding="utf-8")
    files["SKILL.md"] = Template(files["SKILL.md"]).safe_substitute(
        catalog_url=catalog_url.rstrip("/"), generated=dt.date.today().isoformat()
    )
    # Only what an agent needs: no emails or other contact details.
    people = [
        {k: v for k, v in {"id": p.id, "name": p.name, "slack_handle": p.slack_handle}.items() if v}
        | ({} if p.active else {"alumni": True})
        for p in sorted(cat.people, key=lambda p: p.name.lower())
    ]
    files["reference/people.yaml"] = yamlio.render(people)
    files["reference/modalities.yaml"] = yamlio.render([m.model_dump() for m in cat.modalities])
    files["reference/tags.yaml"] = yamlio.render(sorted(cat.tags))
    files["reference/datasets.yaml"] = yamlio.render(
        [{"id": d.id, "title": d.title} for d in sorted(cat.datasets.values(), key=lambda d: d.id)]
    )
    files["reference/schema.json"] = json.dumps(Dataset.model_json_schema(), indent=2) + "\n"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, text in sorted(files.items()):
            info = zipfile.ZipInfo(f"{NAME}/{rel}", date_time=dt.datetime.now().timetuple()[:6])
            info.external_attr = (0o755 if rel.endswith(".py") else 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, text)
    return buf.getvalue()
