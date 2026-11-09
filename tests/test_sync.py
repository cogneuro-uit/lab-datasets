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


def test_admin_page_and_sync_button(repo, remote, tmp_path):
    from fastapi.testclient import TestClient

    from labcat.config import Settings
    from labcat.web import create_app

    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(remote), str(other))
    (other / "datasets/2021-by-hand.yaml").write_text("id: 2021-by-hand\ntitle: Edited by hand\ncontact: matthias\n")
    git(other, "add", "-A")
    git(other, "commit", "-qm", "hand edit")
    git(other, "push", "-q")

    admin = TestClient(create_app(Settings(data_dir=repo, user="matthias", admins=("matthias",), pull_interval=0)),
                       follow_redirects=False)
    page = admin.get("/admin").text
    assert "In sync." in page and str(remote) in page and 'href="/admin"' in page
    assert admin.get("/d/2021-by-hand").status_code == 404
    assert admin.post("/admin/sync").headers["location"] == "/admin"
    assert admin.get("/d/2021-by-hand").status_code == 200

    user = TestClient(create_app(Settings(data_dir=repo, user="matthias")), follow_redirects=False)
    assert user.get("/admin").status_code == 403 and user.post("/admin/sync").status_code == 403
    assert 'href="/admin"' not in user.get("/").text
