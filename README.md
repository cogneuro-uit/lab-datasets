# labcat – lab dataset catalog

A small web app that lists every dataset the lab has collected: what it is, where the
data and backups live, and which papers, preprints and code belong to it. See
[PLAN.md](PLAN.md) for the full proposal. This is the **local-only** first version:
no login (every change is made as `matthias`), no Slack, no server.

## Two git repos

| Repo | Where | Contents |
|---|---|---|
| App | this folder | Python code (FastAPI + Jinja2 + htmx), tests |
| Catalog data | `data/` (own git repo, ignored by the app repo) | `datasets/*.yaml`, `people.yaml`, `vocab/`, `schema/` |

Every save in the web app is a commit in `data/`, authored by the person who made it
(committer: "Lab catalog"). The data repo is
[cogneuro-uit/lab-datasets-data](https://github.com/cogneuro-uit/lab-datasets-data): the
app pulls before each save, pushes after it, and syncs every 10 minutes
(`LABCAT_PULL_INTERVAL`). Admins (`LABCAT_ADMINS`) have an *Admin* page with the sync status
and a *Sync now* button, e.g. after pushing a hand edit. If a sync fails (GitHub unreachable,
or a conflict with a hand edit), changes stay saved on the server and everyone sees a notice
until it works again.

## Quick start

```bash
uv run labcat init      # once: creates data/ (already done)
uv run labcat serve     # http://localhost:8420
```

Other commands: `labcat validate` (check all YAML files), `labcat schema` (regenerate
the JSON schema). Settings come from environment variables or a `.env` file (see
[.env.example](.env.example)): `LABCAT_DATA` (data repo path, default `./data`),
`LABCAT_USER` (person id edits are attributed to when Slack login is off, default `matthias`).

## Sign in with Slack

Without Slack credentials the app runs in development mode: no login, every change is
made as `LABCAT_USER`. With them, everyone must sign in with Slack, and each change is
committed as the signed-in person. People are matched in `people.yaml` by Slack ID, then
by email; someone signing in for the first time is added automatically.

1. Create a Slack app at https://api.slack.com/apps → *From a manifest*, with the user
   scopes `openid`, `profile`, `email` and the redirect URL `<address>/auth/callback`.
   Slack only accepts **https** redirect URLs.
2. Copy `.env.example` to `.env` and fill in the client ID and secret, a secret key, and
   `LABCAT_SLACK_TEAM_ID` (so only the lab's workspace can sign in).
3. Locally, serve https with a trusted certificate from mkcert:
   ```bash
   mkdir -p certs && mkcert -cert-file certs/localhost.pem -key-file certs/localhost-key.pem localhost
   uv run labcat serve --https     # https://localhost:8420
   ```

To keep it running in the background, see [deploy/labcat.service](deploy/labcat.service).

## Adding datasets

- **Step by step:** a wizard with seven short steps; only the first is required.
- **Quick placeholder:** title + contact, fill in the rest later.
- **Import YAML:** upload or paste; it is checked before saving. See `examples/`
  (fictional datasets) for the format.
- **With an AI assistant:** "Download skill" on the *Add a dataset* page gives a zip
  (`lab-dataset-yaml`) for Claude or other agents. It interviews the user, writes the YAML
  and checks it with a bundled validator. It's built on request with the current people
  (names and Slack handles only), tags, modalities and dataset IDs. The source is in
  `src/labcat/skill/`.

## Development

```bash
uv run pytest
uv run labcat serve --reload
```

Frontend libraries are vendored in `src/labcat/static/vendor/` (htmx 2.0.11,
MiniSearch 7.2.0); icons are a sprite built from lucide-static by `scripts/build_icons.py`.
