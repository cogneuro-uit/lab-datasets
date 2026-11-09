import subprocess

import pytest

from conftest import ME, minimal


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@x", *args], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout


@pytest.fixture
def remote(cat, repo, tmp_path):
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", "-q", str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "-u", "origin", "HEAD")
    return bare


def test_unpushed_commits_are_retried(cat, repo, remote, tmp_path):
    git(repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    cat.save_dataset(minimal(), ME, create=True)
    assert cat.sync_error and cat.git.unpushed() == 1
    git(repo, "remote", "set-url", "origin", str(remote))
    cat.sync()
    assert cat.sync_error is None and cat.git.unpushed() == 0
    assert "Test study" in git(remote, "show", "HEAD:datasets/2020-test-study.yaml")


def test_conflict_is_aborted_cleanly(cat, repo, remote, tmp_path, client):
    cat.save_dataset(minimal(), ME, create=True)
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(remote), str(other))
    f = other / "datasets/2020-test-study.yaml"
    f.write_text(f.read_text().replace("title: Test study", "title: Changed on GitHub"))
    git(other, "commit", "-qam", "edit on GitHub")
    # an edit here while GitHub can't be reached, so it can't be rebased first
    git(repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    cat.save_dataset(minimal(title="Changed in the app"), ME)
    git(other, "push", "-q")
    git(repo, "remote", "set-url", "origin", str(remote))
    cat.sync()
    assert "conflict" in cat.sync_error
    assert not cat.git.rebase_in_progress() and not git(repo, "status", "--porcelain").strip()
    assert cat.datasets["2020-test-study"].title == "Changed in the app"
    assert "Not in sync with GitHub" not in client.get("/").text
    client.app.state.cat.sync_error = cat.sync_error
    assert "Not in sync with GitHub" in client.get("/").text
