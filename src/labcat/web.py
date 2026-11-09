"""The web app: catalog, dataset pages, wizard / editor, history, people."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import logging
import re
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from markdown_it import MarkdownIt
from markupsafe import Markup

from . import auth, completeness, doi, forms, skill, yamlio
from .config import Settings, load_settings
from .gitrepo import GitRepo
from .models import ID_PATTERN, LOCATION_KINDS, SHARING, STATUSES, Dataset, Person, slack_channel_url
from .store import Catalog, Conflict, StoreError

log = logging.getLogger(__name__)
HERE = Path(__file__).parent
STOPWORDS = set("a an and the of in on for with to from by at as is are during study data dataset".split())

md = MarkdownIt("commonmark", {"html": False, "linkify": False, "breaks": True})


def slugify(text: str, max_words: int = 4) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower().replace("æ", "ae").replace("ø", "o").replace("å", "a"))
    keep = [w for w in words if w not in STOPWORDS] or words
    return "-".join(keep[:max_words])


def time_ago(iso: str) -> str:
    then = dt.datetime.fromisoformat(iso)
    secs = (dt.datetime.now(then.tzinfo) - then).total_seconds()
    for unit, n in (("year", 31536000), ("month", 2592000), ("day", 86400), ("hour", 3600), ("minute", 60)):
        if secs >= n:
            k = int(secs // n)
            return f"{k} {unit}{'s' if k > 1 else ''} ago"
    return "just now"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    git = GitRepo(settings.data_dir, settings.committer_name, settings.committer_email)
    if not git.is_repo():
        raise SystemExit(f"No catalog data repo at {settings.data_dir}. Create one with: labcat init")
    cat = Catalog(settings.data_dir, git)
    cat.refresh()

    app = FastAPI(title="labcat", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    env = templates.env

    def static_url(name: str) -> str:
        """Link to a static file with its modification time, so browsers fetch new versions."""
        return f"/static/{name}?v={int((HERE / 'static' / name).stat().st_mtime)}"

    env.globals.update(
        static_url=static_url,
        STATUSES=STATUSES,
        SHARING=SHARING,
        LOCATION_KINDS=LOCATION_KINDS,
        get=forms.get,
        slack_channel_url=slack_channel_url,
        cat=cat,
    )
    env.filters["markdown"] = lambda s: Markup(md.render(s or ""))
    env.filters["ago"] = time_ago
    env.filters["date"] = lambda iso: dt.datetime.fromisoformat(iso).strftime("%-d %b %Y, %H:%M")
    env.filters["tojson_attr"] = lambda v: json.dumps(v, ensure_ascii=False)

    def current_user(request: Request) -> Person | None:
        """The signed-in person (or LABCAT_USER when Slack login is off)."""
        if settings.auth_enabled:
            return cat.person(request.session.get("user"))
        p = cat.person(settings.user)
        if p is None:
            raise HTTPException(500, f"User '{settings.user}' is not in people.yaml")
        return p

    def render(request: Request, name: str, status_code: int = 200, **ctx) -> HTMLResponse:
        flash = request.cookies.get("flash")
        resp = templates.TemplateResponse(
            request,
            name,
            {
                "user": current_user(request),
                "auth_enabled": settings.auth_enabled,
                "user_picture": request.session.get("picture") if settings.auth_enabled else None,
                "flash": unquote(flash) if flash else None,
                "open_todo_count": sum(len(d.open_todos) for d in cat.datasets.values() if d.status != "retired"),
                **ctx,
            },
            status_code=status_code,
        )
        if flash:
            resp.delete_cookie("flash")
        return resp

    def redirect(url: str, flash: str | None = None) -> RedirectResponse:
        resp = RedirectResponse(url, status_code=303)
        if flash:
            resp.set_cookie("flash", quote(flash), max_age=30)
        return resp

    def get_ds(dataset_id: str) -> Dataset:
        ds = cat.datasets.get(dataset_id)
        if ds is None:
            raise HTTPException(404, "No such dataset")
        return ds

    @app.get("/brand/{kind}")
    def brand(kind: str):
        rel = {"logo": cat.site.logo, "favicon": cat.site.favicon or cat.site.logo}.get(kind)
        if not rel:
            raise HTTPException(404)
        path = (settings.data_dir / rel).resolve()
        if not path.is_file() or settings.data_dir not in path.parents:
            raise HTTPException(404)
        return FileResponse(path, headers={"Cache-Control": "max-age=3600"})

    @app.get("/about", response_class=HTMLResponse)
    def about(request: Request):
        statuses = sorted({d.status for d in cat.datasets.values()})
        return render(request, "about.html", n_datasets=len(cat.datasets), statuses=statuses)

    @app.middleware("http")
    async def refresh_catalog(request: Request, call_next):
        if not request.url.path.startswith("/static"):
            cat.refresh()
        return await call_next(request)

    if settings.auth_enabled:

        @app.middleware("http")
        async def require_login(request: Request, call_next):
            if not auth.is_public(request.url.path) and not cat.person(request.session.get("user")):
                return auth.login_required_response(request)
            return await call_next(request)

    # Added last, so it runs first: the login check above needs the session.
    secret_key = settings.secret_key or secrets.token_urlsafe(32)
    if settings.auth_enabled and not settings.secret_key:
        log.warning("LABCAT_SECRET_KEY is not set; everyone has to sign in again after a restart.")
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret_key,
        session_cookie="labcat_session",
        max_age=30 * 24 * 3600,
        same_site="lax",
        https_only=bool(settings.base_url and settings.base_url.startswith("https")),
    )
    app.include_router(auth.make_router(settings, cat, render, redirect))

    if git.has_remote():

        def pull_loop():
            while True:
                time.sleep(settings.pull_interval)
                try:
                    with cat.lock:
                        git.pull()
                        cat.refresh()
                except Exception as e:  # noqa: BLE001
                    log.error("background pull failed: %s", e)

        threading.Thread(target=pull_loop, daemon=True).start()

    # --- catalog ---------------------------------------------------------
    def index_entry(ds: Dataset, last) -> dict:
        return {
            "id": ds.id,
            "title": ds.title,
            "summary": ds.summary or "",
            "status": ds.status,
            "year": ds.year,
            "contact": ds.contact,
            "contactName": cat.person_name(ds.contact),
            "people": " ".join(cat.person_name(p) for p in [ds.contact, *ds.contributors]),
            "peopleIds": list(dict.fromkeys([ds.contact, *ds.contributors])),
            "modalities": ds.content.modalities,
            "modalityLabels": " ".join(cat.modality_label(m) for m in ds.content.modalities),
            "tags": ds.content.tags,
            "n": ds.content.n_participants,
            "paradigm": ds.content.paradigm or "",
            "population": ds.content.population or "",
            "sharing": ds.legal.sharing,
            "channel": ds.slack.channel or "",
            "locations": sorted({loc.kind for loc in ds.locations}),
            "hasBackup": any(loc.is_backup for loc in ds.locations),
            "outputs": len(ds.outputs.publications) + len(ds.outputs.preprints),
            "score": completeness.score(ds),
            "todos": len(ds.open_todos),
            "updated": last.date if last else None,
        }

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        last = cat.last_changes()
        index = [index_entry(ds, last.get(ds.id)) for ds in cat.datasets.values()]
        meta = {
            "statuses": STATUSES,
            "sharing": SHARING,
            "modalities": {m.id: m.label for m in cat.modalities},
            "people": {p.id: p.name for p in cat.people},
            "locationKinds": LOCATION_KINDS,
        }
        return render(request, "catalog.html", index=index, meta=meta)

    # --- dataset pages ---------------------------------------------------
    @app.get("/d/{dataset_id}", response_class=HTMLResponse)
    def dataset_page(request: Request, dataset_id: str):
        ds = get_ds(dataset_id)
        hist = cat.git.log(cat.path_of(ds.id), limit=1)
        related_back = [d for d in cat.datasets.values() if ds.id in d.outputs.related_datasets]
        return render(
            request,
            "dataset.html",
            ds=ds,
            checks=completeness.checks(ds),
            score=completeness.score(ds),
            last=hist[0] if hist else None,
            related_back=related_back,
        )

    @app.get("/d/{dataset_id}.yaml")
    def dataset_yaml(dataset_id: str):
        get_ds(dataset_id)
        return PlainTextResponse(
            cat.file_text(dataset_id) or "",
            media_type="text/yaml",
            headers={"Content-Disposition": f'attachment; filename="{dataset_id}.yaml"'},
        )

    @app.get("/d/{dataset_id}/history", response_class=HTMLResponse)
    def history(request: Request, dataset_id: str):
        ds = get_ds(dataset_id)
        return render(request, "history.html", ds=ds, entries=cat.history(dataset_id))

    @app.post("/d/{dataset_id}/restore/{rev}")
    def restore(request: Request, dataset_id: str, rev: str):
        get_ds(dataset_id)
        if not re.fullmatch(r"[0-9a-f]{7,40}", rev):
            raise HTTPException(400)
        cat.restore(dataset_id, rev, current_user(request))
        return redirect(f"/d/{dataset_id}", f"Restored the version from {rev[:7]}. The old state is kept in the history.")

    @app.post("/d/{dataset_id}/status")
    def change_status(request: Request, dataset_id: str, status: str = Form(...)):
        get_ds(dataset_id)
        if status not in STATUSES:
            raise HTTPException(400)
        cat.set_status(dataset_id, status, current_user(request))
        msg = "Dataset retired. It is hidden from the catalog but kept, with its history." if status == "retired" else "Dataset is active again."
        return redirect(f"/d/{dataset_id}", msg)

    @app.post("/d/{dataset_id}/todos/{index}")
    def toggle_todo(request: Request, dataset_id: str, index: int, done: bool = Form(False)):
        if not 0 <= index < len(get_ds(dataset_id).todos):
            raise HTTPException(404)
        cat.set_todo_done(dataset_id, index, done, current_user(request))
        if request.headers.get("x-requested-with") == "fetch":
            return JSONResponse({"done": done})
        return redirect(f"/d/{dataset_id}#todos", "To-do ticked off." if done else "To-do reopened.")

    @app.get("/todos", response_class=HTMLResponse)
    def todos(request: Request, person: str = "", done: bool = False):
        groups = []
        for ds in sorted(cat.datasets.values(), key=lambda d: d.id, reverse=True):
            if ds.status == "retired":
                continue
            items = [
                (i, t)
                for i, t in enumerate(ds.todos)
                if (done or not t.done)
                and (not person or (t.assignee or "") == (person if person != "nobody" else ""))
            ]
            if items:
                groups.append((ds, items))
        assignees: dict[str, int] = {}
        for ds in cat.datasets.values():
            if ds.status != "retired":
                for t in ds.open_todos:
                    key = t.assignee or "nobody"
                    assignees[key] = assignees.get(key, 0) + 1
        return render(request, "todos.html", groups=groups, person=person, show_done=done, assignees=assignees)

    # --- editing ---------------------------------------------------------
    def form_page(request, mode, values, errors=None, message=None, base_sha=None, status_code=200, ds=None):
        return render(
            request,
            "edit.html",
            status_code=status_code,
            mode=mode,
            v=values,
            errors=errors or {},
            message=message,
            base_sha=base_sha,
            ds=ds,
            this_year=dt.date.today().year,
            id_pattern=ID_PATTERN,
        )

    @app.get("/d/{dataset_id}/edit", response_class=HTMLResponse)
    def edit_page(request: Request, dataset_id: str):
        ds = get_ds(dataset_id)
        return form_page(request, "edit", ds.model_dump(mode="json"), base_sha=cat.shas.get(dataset_id), ds=ds)

    @app.post("/d/{dataset_id}/edit", response_class=HTMLResponse)
    async def edit_save(request: Request, dataset_id: str):
        ds = get_ds(dataset_id)
        form = await request.form()
        items = list(form.multi_items())
        data = forms.parse_dataset_form(items)
        data["id"] = dataset_id
        base_sha = form.get("_base_sha") or None
        prefer_mine = form.get("_resolve") == "mine"
        try:
            res = cat.save_dataset(data, current_user(request), base_sha=base_sha, prefer_mine=prefer_mine)
        except StoreError as e:
            return form_page(request, "edit", data, e.errors, str(e), base_sha, 422, ds=ds)
        except Conflict as c:
            return render(request, "conflict.html", status_code=409, c=c, ds=ds, items=items)
        if res.commit is None:
            return redirect(f"/d/{dataset_id}", "Nothing changed.")
        msg = "Saved."
        if res.merged:
            msg = "Saved. Someone else edited this dataset meanwhile; their changes were kept."
        if res.new_tags:
            msg += " New tags added to the list: " + ", ".join(res.new_tags) + "."
        return redirect(f"/d/{dataset_id}", msg)

    # --- creating --------------------------------------------------------
    @app.get("/new", response_class=HTMLResponse)
    def new_chooser(request: Request):
        return render(request, "new.html")

    @app.get("/new/wizard", response_class=HTMLResponse)
    def new_wizard(request: Request):
        return form_page(request, "wizard", {"contact": settings.user, "status": "planned"})

    @app.get("/new/quick", response_class=HTMLResponse)
    def new_quick(request: Request):
        return form_page(request, "quick", {"contact": settings.user, "status": "planned"})

    @app.post("/new", response_class=HTMLResponse)
    async def create(request: Request):
        form = await request.form()
        mode = form.get("_mode") if form.get("_mode") in ("wizard", "quick") else "wizard"
        data = forms.parse_dataset_form(list(form.multi_items()))
        if not data.get("id") and data.get("title"):
            data["id"] = f"{form.get('_year') or dt.date.today().year}-{slugify(data['title'])}"
        try:
            res = cat.save_dataset(data, current_user(request), create=True)
        except StoreError as e:
            return form_page(request, mode, data, e.errors, str(e), status_code=422)
        msg = "Dataset created."
        if completeness.score(res.dataset) < 100:
            msg += " You can fill in the rest any time with “Edit”."
        return redirect(f"/d/{res.dataset.id}", msg)

    @app.get("/new/import", response_class=HTMLResponse)
    def new_import(request: Request):
        return render(request, "import.html", text="", result=None)

    def check_yaml(text: str) -> dict:
        """Parse and validate YAML text; returns a result dict for the template."""
        try:
            data = yamlio.plain(yamlio.load(text))
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "message": "This is not valid YAML.", "errors": {"yaml": str(e).splitlines()[0]}}
        if not isinstance(data, dict):
            return {"ok": False, "message": "The YAML should describe one dataset (a mapping with id, title, …).", "errors": {}}
        try:
            ds = cat.parse(data)
        except StoreError as e:
            return {"ok": False, "message": str(e), "errors": e.errors, "data": data}
        if ds.id in cat.datasets:
            return {"ok": False, "message": "A dataset with this ID already exists.", "errors": {"id": ds.id}, "data": data}
        new_tags = [t for t in ds.content.tags if t not in cat.tags]
        return {"ok": True, "ds": ds, "new_tags": new_tags, "score": completeness.score(ds)}

    @app.post("/new/import/check", response_class=HTMLResponse)
    async def import_check(request: Request):
        form = await request.form()
        text = await _yaml_text(form)
        return templates.TemplateResponse(request, "_import_result.html", {"result": check_yaml(text), "text": text})

    @app.post("/new/import", response_class=HTMLResponse)
    async def import_create(request: Request):
        form = await request.form()
        text = await _yaml_text(form)
        result = check_yaml(text)
        if not result["ok"]:
            return render(request, "import.html", status_code=422, text=text, result=result)
        res = cat.save_dataset(result["ds"].to_yaml_data(), current_user(request), create=True)
        return redirect(f"/d/{res.dataset.id}", "Dataset imported.")

    async def _yaml_text(form) -> str:
        upload = form.get("file")
        if upload is not None and hasattr(upload, "read"):
            content = await upload.read()
            if content:
                return content.decode("utf-8", errors="replace")
        return str(form.get("yaml") or "")

    # --- people ----------------------------------------------------------
    @app.get("/people", response_class=HTMLResponse)
    def people(request: Request):
        counts: dict[str, int] = {}
        for ds in cat.datasets.values():
            for pid in {ds.contact, *ds.contributors}:
                counts[pid] = counts.get(pid, 0) + 1
        return render(request, "people.html", counts=counts, errors={}, v={})

    @app.get("/people/{person_id}", response_class=HTMLResponse)
    def profile(request: Request, person_id: str):
        p = cat.person(person_id)
        if p is None:
            raise HTTPException(404)
        active = [d for d in cat.datasets.values() if d.status != "retired"]
        by_year = lambda d: (d.year or 0, d.id)  # noqa: E731
        contact = sorted((d for d in active if d.contact == p.id), key=by_year, reverse=True)
        contributor = sorted((d for d in active if d.contact != p.id and p.id in d.contributors), key=by_year, reverse=True)
        todo_groups = []
        for d in sorted(active, key=lambda d: d.id, reverse=True):
            items = [(i, t) for i, t in enumerate(d.todos) if t.assignee == p.id and not t.done]
            if items:
                todo_groups.append((d, items))
        # Open to-dos nobody has taken on yet, in datasets this person is contact for.
        unassigned = [
            (d, [(i, t) for i, t in enumerate(d.todos) if not t.assignee and not t.done]) for d in contact
        ]
        unassigned = [(d, items) for d, items in unassigned if items]
        edits = [(c, ids) for c, ids in cat.recent(400) if (a := cat.author_of(c)) and a.id == p.id][:12]
        collaborators: dict[str, int] = {}
        for d in [*contact, *contributor]:
            for q in {d.contact, *d.contributors} - {p.id}:
                collaborators[q] = collaborators.get(q, 0) + 1
        top = sorted(collaborators.items(), key=lambda kv: (-kv[1], cat.person_name(kv[0])))[:8]
        return render(
            request, "profile.html", p=p, contact=contact, contributor=contributor, todo_groups=todo_groups,
            unassigned=unassigned, edits=edits, collaborators=top,
            n_todos=sum(len(items) for _, items in todo_groups),
        )

    @app.post("/people")
    async def add_person(request: Request):
        form = await request.form()
        data = {k: v for k, v in form.items() if not k.startswith("_") and k != "alumni"}
        data["active"] = not form.get("alumni")
        if not data.get("id") and data.get("name"):
            data["id"] = slugify(data["name"], 2).replace("-", "")
        wants_json = "application/json" in request.headers.get("accept", "")
        try:
            p = cat.add_person(data, current_user(request))
        except StoreError as e:
            if wants_json:
                return JSONResponse({"error": str(e), "errors": e.errors}, status_code=422)
            return render(request, "people.html", status_code=422, counts={}, errors=e.errors, v=data)
        if wants_json:
            return {"id": p.id, "name": p.name}
        return redirect("/people", f"Added {p.name}.")

    # --- changes ---------------------------------------------------------
    @app.get("/changes", response_class=HTMLResponse)
    def changes(request: Request):
        return render(request, "changes.html", commits=cat.recent(100))

    # --- small APIs used by the forms ------------------------------------
    @app.get("/api/doi")
    def api_doi(q: str):
        return doi.lookup(q)

    @app.get("/api/suggest-id")
    def api_suggest_id(title: str = "", year: str = ""):
        year = year if re.fullmatch(r"\d{4}", year or "") else str(dt.date.today().year)
        slug = slugify(title)
        if not slug:
            return {"id": "", "available": False}
        base = f"{year}-{slug}"
        cand, n = base, 2
        while cand in cat.datasets:
            cand, n = f"{base}-{n}", n + 1
        return {"id": cand, "available": True}

    @app.get("/api/check-id")
    def api_check_id(id: str):
        if not re.fullmatch(ID_PATTERN, id):
            return {"ok": False, "message": "Use YYYY-short-name: lowercase letters, digits and dashes."}
        if id in cat.datasets:
            return {"ok": False, "message": "This ID is already taken."}
        return {"ok": True, "message": "Available"}

    @app.get("/skill/lab-dataset-yaml.zip")
    def skill_zip(request: Request):
        return Response(
            skill.build_zip(cat, str(request.base_url)),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="lab-dataset-yaml.zip"'},
        )

    @app.get("/export.csv")
    def export_csv():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "title", "status", "year", "contact", "modalities", "n_participants", "tags", "sharing", "slack_channel", "locations"])
        for ds in sorted(cat.datasets.values(), key=lambda d: d.id):
            w.writerow([
                ds.id, ds.title, ds.status, ds.year, cat.person_name(ds.contact),
                "; ".join(ds.content.modalities), ds.content.n_participants or "",
                "; ".join(ds.content.tags), ds.legal.sharing or "", ds.slack.channel or "",
                "; ".join(f"{loc.kind}: {loc.target()}" for loc in ds.locations),
            ])
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="lab-datasets.csv"'})

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        return render(request, "error.html", status_code=404, title="Not found",
                      message="This page or dataset does not exist. It may have been renamed.")

    return app


def app_factory() -> FastAPI:
    return create_app()
