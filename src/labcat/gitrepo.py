"""Thin wrapper around the git command line for the catalog data repo."""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

SEP = "\x1f"
REC = "\x1e"


class GitError(RuntimeError):
    pass


@dataclass
class Commit:
    sha: str
    author_name: str
    author_email: str
    date: str  # ISO 8601
    subject: str
    files: list[str] = field(default_factory=list)

    @property
    def short(self) -> str:
        return self.sha[:7]


def blob_sha(content: bytes) -> str:
    """The SHA git would give this content as a blob (like `git hash-object`)."""
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


class GitRepo:
    def __init__(self, path: Path, committer_name: str, committer_email: str):
        self.path = Path(path)
        self.committer_name = committer_name
        self.committer_email = committer_email

    def run(self, *args: str, check: bool = True, env: dict | None = None) -> str:
        full_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})}
        res = subprocess.run(
            ["git", *args], cwd=self.path, capture_output=True, text=True, env=full_env
        )
        if check and res.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
        return res.stdout

    # --- state -----------------------------------------------------------
    def is_repo(self) -> bool:
        return (self.path / ".git").exists()

    def head(self) -> str | None:
        out = self.run("rev-parse", "--verify", "-q", "HEAD", check=False).strip()
        return out or None

    def has_remote(self) -> bool:
        return bool(self.run("remote").strip())

    def show(self, rev: str, path: str) -> str | None:
        res = subprocess.run(
            ["git", "show", f"{rev}:{path}"], cwd=self.path, capture_output=True, text=True
        )
        return res.stdout if res.returncode == 0 else None

    def cat_blob(self, sha: str) -> str | None:
        res = subprocess.run(
            ["git", "cat-file", "blob", sha], cwd=self.path, capture_output=True, text=True
        )
        return res.stdout if res.returncode == 0 else None

    # --- sync ------------------------------------------------------------
    def pull(self) -> None:
        """Rebase local commits onto the remote. On a conflict, give up cleanly (nothing is lost)."""
        if not self.has_remote():
            return
        try:
            self.run("pull", "--rebase", "--autostash", "--quiet")
        except GitError:
            if self.rebase_in_progress():
                self.run("rebase", "--abort", check=False)
                raise GitError(
                    "changes on GitHub conflict with changes made here; someone needs to merge them by hand"
                ) from None
            raise

    def push(self) -> None:
        if not self.has_remote():
            return
        try:
            self.run("push", "--quiet")
        except GitError:
            log.warning("push rejected, rebasing and retrying once")
            self.pull()
            self.run("push", "--quiet")

    def rebase_in_progress(self) -> bool:
        git_dir = self.path / ".git"
        return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()

    def unpushed(self) -> int:
        """Number of local commits not yet on the remote (0 if unknown)."""
        out = self.run("rev-list", "--count", "@{upstream}..HEAD", check=False).strip()
        return int(out) if out.isdigit() else 0

    # --- writing ---------------------------------------------------------
    def commit(self, paths: list[str], message: str, author_name: str, author_email: str) -> str:
        self.run("add", "--", *paths)
        env = {
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": self.committer_name,
            "GIT_COMMITTER_EMAIL": self.committer_email,
        }
        self.run("commit", "--quiet", "-m", message, "--", *paths, env=env)
        return self.head() or ""

    # --- reading history -------------------------------------------------
    def log(self, path: str | None = None, limit: int = 200) -> list[Commit]:
        fmt = REC + SEP.join(["%H", "%an", "%ae", "%aI", "%s"]) + SEP
        args = ["log", f"-n{limit}", f"--format={fmt}", "--name-only"]
        if path:
            args += ["--", path]
        if not self.head():
            return []
        out = self.run(*args)
        commits = []
        for rec in out.split(REC)[1:]:
            parts = rec.split(SEP)
            sha, an, ae, date, subject = parts[:5]
            files = [f for f in parts[5].split("\n") if f.strip()] if len(parts) > 5 else []
            commits.append(Commit(sha, an, ae, date, subject, files))
        return commits
