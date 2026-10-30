"""Command line: labcat init | serve | validate | schema."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import load_settings
from .gitrepo import GitRepo
from .models import Dataset, Person
from .store import SCHEMA, Catalog, init_data_repo


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="labcat", description="Lab dataset catalog")
    ap.add_argument("--data", help="catalog data repo (default: $LABCAT_DATA or ./data)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create a new catalog data repo")
    p.add_argument("--id", default="matthias", help="your person id")
    p.add_argument("--name", default="Matthias Mittner", help="your full name")
    p.add_argument("--email", default=None)

    p = sub.add_parser("serve", help="run the web app")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true", help="restart on code changes (development)")

    sub.add_parser("validate", help="check all dataset files")
    sub.add_parser("schema", help="regenerate schema/dataset.schema.json")

    args = ap.parse_args(argv)
    if args.data:
        os.environ["LABCAT_DATA"] = args.data
    settings = load_settings()
    root = settings.data_dir

    if args.cmd == "init":
        init_data_repo(root, Person(id=args.id, name=args.name, email=args.email))
        print(f"Catalog data repo ready at {root}")
    elif args.cmd == "serve":
        import uvicorn

        uvicorn.run("labcat.web:app_factory", factory=True, host=args.host, port=args.port, reload=args.reload)
    elif args.cmd == "validate":
        cat = Catalog(root, GitRepo(root, settings.committer_name, settings.committer_email))
        cat.reload()
        problems = dict(cat.broken)
        for ds in cat.datasets.values():
            errs = cat.check_refs(ds)
            if errs:
                problems[f"{ds.id}.yaml"] = "; ".join(f"{k}: {v}" for k, v in errs.items())
        for f, msg in problems.items():
            print(f"✗ {f}: {msg}")
        print(f"{len(cat.datasets)} datasets, {len(problems)} with problems")
        sys.exit(1 if problems else 0)
    elif args.cmd == "schema":
        out = Path(root) / SCHEMA
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(Dataset.model_json_schema(), indent=2) + "\n")
        print(f"wrote {out}")
