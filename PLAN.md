# Lab Dataset Catalog — Proposal & Plan

Status: draft v0.1 (2026-10-30). To be revised after feeding in the first example datasets.

## 1. Goal

One place listing every dataset the lab has collected. It should be searchable, tagged and
attractive. For each dataset it records where the data and its backups live (Teams, OSF, server,
elsewhere), and which preprints, publications and code repositories belong to it.

- **Anyone in the lab can add or edit**, with no GitHub account needed. Login is through Slack.
- **Full history** of every change and who made it (git).
- **Low friction:** quick search and quick add from Slack; announcements in Slack when something changes.

### Non-goals

- Storing data. The catalog holds metadata and links only, and no personal data.
- Checking server or Teams paths. People paste links and paths by hand, and the catalog trusts them.
- Replacing OSF, Zenodo or other repositories. The catalog points to them.
- Approval workflows. Anyone can edit, and the history is the safety net.

## 2. Architecture

```
 Lab member (on VPN)                       Lab member (anywhere)
   │ browser                                 │ Slack: /dataset …
   ▼                                         ▼
 ┌──────────────────────────── lab server (VPN-only) ───────────────────────────┐
 │  Caddy (TLS)                                                                  │
 │    └─► catalog app (Python, one container)                                    │
 │          ├─ web UI: browse / search / view / edit / history                   │
 │          ├─ "Sign in with Slack" (OpenID Connect)                             │
 │          ├─ Slack bot in Socket Mode (outbound only, so no inbound port)      │
 │          └─ local git clone of lab/datasets ──push/pull──┐                    │
 └──────────────────────────────────────────────────────────┼────────────────────┘
                                                            ▼
                                       GitHub: <org>/datasets (private repo)
                                         datasets/*.yaml, schema, vocab
                                         Actions: validate, fill in from DOIs,
                                                  post to Slack
```

### Why this works with a VPN-only server

| Concern | Solution |
|---|---|
| Slack login | OpenID Connect redirects happen in the user's browser, which is on the VPN. The server only makes outbound calls to slack.com. |
| Slash commands and modals | **Socket Mode.** The bot holds an outbound WebSocket to Slack, so Slack never has to reach the server. This also gives off-VPN access for search and quick add. |
| GitHub webhooks (inbound) | Not needed. The app runs `git pull` every minute or so. Edits made directly on GitHub are announced by GitHub Actions, which post outbound to a Slack webhook. |
| TLS certificate for an internal hostname | A UiT-issued certificate, or Caddy with a DNS-01 challenge. Decide with IT (see open questions). |

The server needs **outbound** HTTPS to `slack.com`, `github.com` and `api.crossref.org` / `api.datacite.org`.

## 3. Components

### 3.1 Data repository (`<org>/datasets`, private)

```
datasets/
  2019-eeg-attention.yaml        # one file per dataset; file name = id
  2021-pupil-mindwandering.yaml
people.yaml                      # lab members and alumni (name, slack_id, orcid, active)
vocab/
  tags.yaml                      # controlled tag list, can be extended from the UI
  modalities.yaml                # EEG, fMRI, MEG, eye-tracking, behaviour, questionnaire, …
schema/
  dataset.schema.json            # generated from the app's Pydantic models
.github/workflows/
  validate.yml                   # schema check on every push
  enrich.yml                     # fill in publication details from DOIs
  notify.yml                     # post changes to #datasets
README.md                        # how to edit by hand (for coders)
```

- One YAML file per dataset keeps diffs readable and merge conflicts rare. Coders can edit the
  files directly; everyone else uses the web UI.
- `people.yaml` exists because people leave Slack. Datasets refer to people by a stable `id`,
  which is not the Slack ID.

### 3.2 Catalog app

- **Stack:** Python 3.12 managed with uv, FastAPI, Jinja2 templates and htmx for the forms, and
  Pydantic models as the single schema definition (the JSON Schema for CI is generated from them).
  `slack-bolt` runs in Socket Mode in the same process. MiniSearch handles search in the browser.
- **Reads:** from the local clone, parsed into memory at startup and after each pull. A few hundred
  files is trivial to hold in memory.
- **Writes:**
  1. The edit form carries the git blob SHA of the file as it was when the form was loaded.
  2. On save: `git pull`, then compare SHAs. If the file has changed since loading, show "changed by X
     meanwhile" with a diff and let the user merge.
  3. Validate, write the YAML (with comments and key order kept, using `ruamel.yaml`), and commit with
     **author = the logged-in user** (`Jane Doe <slack-U123@users.noreply.lab>`) and
     **committer = the bot**. Push, and retry once after a rebase if the push is rejected.
  4. Post to Slack: "Jane updated *2019-eeg-attention*: added OSF link" (diff summary and a link).
- **History page per dataset:** `git log --follow` on the file, showing each change as a readable
  field-level diff ("tags: +pupillometry"), not raw YAML. A "restore this version" button makes a
  new commit, so restoring never rewrites history.
- **Deletion:** a soft delete (`status: retired`) keeps the file, so links and history stay intact.
- **Push credentials:** a GitHub App installed on the one repo with `contents: write`. It mints
  short-lived installation tokens. No personal tokens.

### 3.3 Slack integration

| Feature | Description |
|---|---|
| Sign in with Slack | Only members of our workspace (`team_id` check) can use the web UI |
| `/dataset <query>` | Top hits, each with a link to the web UI and its storage links |
| `/dataset new` | A modal with the minimal fields (title, contact, year, modality, one location link) creates a draft entry that can be completed later on the web |
| `#datasets` feed | Every change, whether from the UI, Slack or a direct git push, is announced in one channel |
| Message shortcut "Attach to dataset…" | *(phase 3)* Pick a DOI, OSF or GitHub link out of a Slack message and attach it to a dataset |

### 3.4 Automation (light)

- **Fill in from DOIs:** when a `doi` is added without a title or authors, fetch them from
  Crossref/DataCite. The app does this live in the form, and the Action is a fallback for hand edits.
- **Preprint to paper:** a weekly Action asks Crossref whether each preprint has a published version
  and opens a suggestion (posted to Slack) rather than editing silently.
- **Gentle reminders** *(phase 3)*: a monthly Slack message to contacts whose datasets are missing a
  backup location or sharing level.
- Server and Teams paths are not validated (by decision).

## 4. Data model (draft — to be revised with the real examples)

```yaml
id: 2019-eeg-attention            # = file name; YYYY-short-slug, never changes
title: Sustained attention and mind-wandering, EEG + pupil
status: published                 # planned | collecting | analysing | published | archived | retired
summary: >
  64-channel EEG and pupillometry during a finger-tapping SART-like task…
contact: jdoe                     # person id from people.yaml
contributors: [jdoe, mmittner]
collected: {start: 2019-02, end: 2019-11}

content:
  modalities: [eeg, eye-tracking, behaviour]
  n_participants: 42
  population: healthy adults 18–35
  paradigm: finger-tapping random sequence generation
  tags: [mind-wandering, attention, tms]

legal:
  ethics_ref: "REK 2018/1234"
  data_protection_ref: "Sikt 123456"
  consent_scope: "reuse within research on attention; no sharing of raw data outside EU"
  sharing: on-request            # open | on-request | internal | restricted
  delete_by: 2034-12-31          # optional

locations:                        # pasted by hand, not validated
  - kind: teams                   # teams | server | osf | zenodo | openneuro | figshare | other
    url: "https://uitno.sharepoint.com/sites/…"
    note: raw + BIDS
    is_backup: true
  - kind: server
    path: /data/projects/2019-eeg-attention
  - kind: osf
    url: https://osf.io/abc12/
    note: preprocessed, public

outputs:
  publications:
    - doi: 10.1234/abcd.5678
      title: …                    # filled in automatically from the DOI
      year: 2021
  preprints:
    - doi: 10.31234/osf.io/xyz
  code:
    - url: https://github.com/<org>/eeg-attention-analysis
  related_datasets: [2021-pupil-mindwandering]

notes: free text, markdown allowed
```

Rules:
- Required for a draft: `id`, `title`, `contact`, `status`. Everything else is optional at first.
  A "completeness" indicator in the UI nudges people to fill in the rest.
- Tags come from `vocab/tags.yaml`. The UI offers autocomplete and an "add new tag" button, which
  commits the new tag to the vocabulary file.
- Exports later on are straightforward: schema.org/JSON-LD for each dataset, and a CSV of the whole catalog.

## 5. Web UI

- **Home / catalog:** a search box (instant search over title, summary, tags and paradigm) with
  facets for modality, tag, year, status, sharing level and contact, and a card view or table view.
- **Dataset page:** a summary block with quick buttons for each location ("Open in Teams",
  "OSF", "Copy server path"), outputs with formatted citations, a history tab and an edit button.
- **Edit page:** a structured form with repeatable groups for locations and outputs, a DOI field
  that fills in the rest, people pickers and tag autocomplete.
- **Recent changes:** across all datasets (the git log of the whole repo).
- Light and dark themes; usable on a phone.

## 6. Phases

| Phase | Content | Done when |
|---|---|---|
| **0. Schema from examples** | Enter 3–5 real datasets by hand as YAML; adjust the schema and vocabularies | We're happy with the fields |
| **1. Read-only MVP** | Repo and CI validation; app with Slack login, catalog, search, dataset pages; deployed on the server | Lab members can browse on the VPN |
| **2. Editing** | Edit/create forms, bot commits with author, history and restore, conflict handling, #datasets feed, filling in from DOIs | Non-coders add datasets without help |
| **3. Slack-native** | `/dataset` search and quick add, message shortcut, reminders, preprint→paper suggestions | Most small updates happen from Slack |
| **4. Backfill** | A "dataset sprint" at a lab meeting: everyone enters their old datasets | Catalog is near-complete |

## 7. Setup checklist (things only an admin can do)

- [ ] Create the `<org>/datasets` private repo
- [ ] Create a GitHub App (contents: write on that repo), install it, store the private key on the server
- [ ] Create a Slack app: OIDC sign-in (redirect URL = internal hostname), bot scopes
      (`commands`, `chat:write`), Socket Mode app token, an incoming webhook for Actions → #datasets
- [ ] Create the `#datasets` channel
- [ ] Internal hostname and TLS certificate (UiT IT, or a DNS-01 challenge)
- [ ] Docker/Podman (or a systemd + uv service) on the lab server; outbound HTTPS allowed

## 8. Open questions

1. **Is the catalog itself confidential?** It's assumed private for now. Should there ever be a
   public, read-only showcase of `sharing: open` datasets (for example on GitHub Pages)?
2. **Hosting on the lab server:** is running a small web service there OK, and how do we get a
   hostname and certificate (UiT IT)?
3. **Granularity:** one entry per *study*, or per *data collection* (for example pilot and main
   study as separate entries)? Settle this with the examples.
4. **Legal fields:** which REK/Sikt fields are useful, and should `delete_by` dates trigger reminders?
5. **People:** ORCID for everyone? How are alumni and external collaborators handled?
6. **Slack plan:** check that our workspace allows custom apps (it normally does; it may need admin approval).

## 9. Next step

Pick 3–5 varied datasets (old and new; open and restricted; one with a paper, one in progress),
write them up roughly in any format, and turn them into YAML together to settle the schema (phase 0).
