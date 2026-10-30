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
(committer: "Lab catalog"). Each repo can be pushed to GitHub on its own later; once
`data/` has a remote, the app pulls before and pushes after each change.

## Quick start

```bash
uv run labcat init      # once: creates data/ (already done)
uv run labcat serve     # http://localhost:8420
```

Other commands: `labcat validate` (check all YAML files), `labcat schema` (regenerate
the JSON schema). Settings: `LABCAT_DATA` (data repo path, default `./data`),
`LABCAT_USER` (person id edits are attributed to, default `matthias`).

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
