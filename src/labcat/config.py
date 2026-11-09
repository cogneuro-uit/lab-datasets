"""Settings, read from environment variables (and from a `.env` file in the working directory).

LABCAT_DATA                 path of the catalog data repo (default: ./data)
LABCAT_USER                 person id that all edits are attributed to when Slack login is off
                            (development; default: matthias)
LABCAT_SLACK_CLIENT_ID      Slack app credentials; when both are set, everyone must sign in
LABCAT_SLACK_CLIENT_SECRET  with Slack
LABCAT_SLACK_TEAM_ID        only members of this workspace may sign in (e.g. T01234567); if
                            empty, the workspace of the first sign-in is shown in the log
LABCAT_SECRET_KEY           signs the login cookie; set it so logins survive restarts
LABCAT_BASE_URL             public address, e.g. https://datasets.lab.uit.no (default: taken
                            from the request)
LABCAT_ADMINS               person ids with access to the admin page, comma-separated (e.g. matthias)
LABCAT_PULL_INTERVAL        seconds between automatic syncs with GitHub (default: 600; 0 = off)
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
    pull_interval: int = 600  # seconds; only used when the data repo has a remote; 0 = off
    slack_client_id: str | None = None
    slack_client_secret: str | None = None
    slack_team_id: str | None = None
    secret_key: str | None = None
    base_url: str | None = None
    admins: tuple[str, ...] = ()

    @property
    def auth_enabled(self) -> bool:
        return bool(self.slack_client_id and self.slack_client_secret)


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=value lines; blank lines and # comments are skipped, quotes are stripped."""
    out = {}
    if not path.is_file():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip("'\"")
    return out


def load_settings() -> Settings:
    env = read_env_file(Path(".env")) | dict(os.environ)

    def get(key: str) -> str | None:
        return env.get(key) or None

    return Settings(
        data_dir=Path(get("LABCAT_DATA") or "data").resolve(),
        user=get("LABCAT_USER") or "matthias",
        slack_client_id=get("LABCAT_SLACK_CLIENT_ID"),
        slack_client_secret=get("LABCAT_SLACK_CLIENT_SECRET"),
        slack_team_id=get("LABCAT_SLACK_TEAM_ID"),
        secret_key=get("LABCAT_SECRET_KEY"),
        base_url=get("LABCAT_BASE_URL"),
        admins=tuple(x.strip() for x in (get("LABCAT_ADMINS") or "").split(",") if x.strip()),
        pull_interval=int(get("LABCAT_PULL_INTERVAL") or 600),
    )
