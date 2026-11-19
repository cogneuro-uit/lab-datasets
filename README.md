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

## Deploy to Azure App Service

The [GitHub Actions workflow](.github/workflows/p-resapp-labdata-deploy.yaml) tests
the app with `uv`, builds a ZIP with its locked runtime dependencies, and deploys
it to the production slot of `p-resapp-labdata` on pushes to `main`. You can also
run it manually from `main` in the Actions tab.

Before the first deployment:

1. Configure Azure OIDC federation for the repository's `main` branch
   (`repo:uit-no/lab-datasets:ref:refs/heads/main`). Grant the federated identity
   deployment access to the production Web App and set these GitHub Actions
   secrets: `P_RESAPP_DEPLOYMENT_ID_CLIENTID`, `P_RESAPP_DEPLOYMENT_ID_TENANTID`,
   and `P_RESAPP_DEPLOYMENT_ID_SUBSCRIPTIONID`.
2. Set the Web App's stack to **Python 3.12 on Linux**. Set
   `SCM_DO_BUILD_DURING_DEPLOYMENT=false` because the runner builds the ZIP, and
   leave `WEBSITE_RUN_FROM_PACKAGE` unset. Set the startup command to:
   ```sh
   python -m uvicorn labcat.web:app_factory --factory --host 0.0.0.0 --port 8000
   ```
3. Clone the catalog data repository into a persistent path outside the
   deployment directory, such as `/home/labcat-data`, and set `LABCAT_DATA` to
   that path in App Service. The app won't start without the Git checkout.
   Configure Git credentials on the Web App for catalog sync; the workflow's
   Azure credentials are only for deployment.
4. Before exposing the app publicly, set the Slack credentials, workspace ID,
   session secret, and HTTPS `LABCAT_BASE_URL` in App Service. Without the Slack
   credentials, the app permits edits without signing in. Register
   `<LABCAT_BASE_URL>/auth/callback` in the Slack app.

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
