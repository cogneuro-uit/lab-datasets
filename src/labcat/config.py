"""Settings, read from environment variables.

LABCAT_DATA   path of the catalog data repo (default: ./data)
LABCAT_USER   person id that all edits are attributed to (no login yet; default: matthias)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    user: str
    committer_name: str = "Lab catalog"
    committer_email: str = "catalog@lab.local"
    pull_interval: int = 60  # seconds; only used when the data repo has a remote


def load_settings() -> Settings:
    return Settings(
        data_dir=Path(os.environ.get("LABCAT_DATA", "data")).resolve(),
        user=os.environ.get("LABCAT_USER", "matthias"),
    )
