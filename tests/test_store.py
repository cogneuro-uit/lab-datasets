import subprocess

import pytest

from labcat.store import Conflict, StoreError
from conftest import ME, minimal


def test_create_commits_with_author(cat, repo):
    res = cat.save_dataset(minimal(content={"tags": ["attention", "brand-new"]}), ME, create=True)
    assert res.new_tags == ["brand-new"]
    log = subprocess.run(["git", "-C", repo, "log", "-1", "--format=%an|%cn|%s"], capture_output=True, text=True).stdout
    assert log.startswith("Matthias Mittner|Lab catalog|Add 2020-test-study")
    assert "brand-new" in (repo / "vocab/tags.yaml").read_text()
    with pytest.raises(StoreError):
        cat.save_dataset(minimal(), ME, create=True)


def test_unknown_people_rejected(cat):
    with pytest.raises(StoreError) as e:
        cat.save_dataset(minimal(contact="nobody"), ME, create=True)
    assert "contact" in e.value.errors


def test_update_keeps_hand_comments(cat, repo):
    cat.save_dataset(minimal(), ME, create=True)
    f = repo / "datasets/2020-test-study.yaml"
    f.write_text("# keep me\n" + f.read_text())
    cat.refresh()
    data = cat.datasets["2020-test-study"].to_yaml_data() | {"status": "collecting"}
    cat.save_dataset(data, ME, cat.shas["2020-test-study"])
    text = f.read_text()
    assert text.startswith("# keep me\n") and "status: collecting" in text


def test_no_change_no_commit(cat):
    cat.save_dataset(minimal(), ME, create=True)
    res = cat.save_dataset(minimal(), ME, cat.shas["2020-test-study"])
    assert res.commit is None


def test_concurrent_edits_merge_or_conflict(cat):
    cat.save_dataset(minimal(), ME, create=True)
    base = cat.shas["2020-test-study"]
    cat.save_dataset(minimal(status="collecting"), ME, base)  # someone else
    res = cat.save_dataset(minimal(summary="mine"), ME, base)  # me, on the old version
    assert res.merged
    ds = cat.datasets["2020-test-study"]
    assert ds.status == "collecting" and ds.summary == "mine"
    with pytest.raises(Conflict) as c:
        cat.save_dataset(minimal(status="published"), ME, base)
    assert c.value.paths == ["status"]
    cat.save_dataset(minimal(status="published"), ME, base, prefer_mine=True)
    assert cat.datasets["2020-test-study"].status == "published"


def test_history_and_restore(cat):
    cat.save_dataset(minimal(), ME, create=True)
    cat.save_dataset(minimal(content={"tags": ["attention"]}), ME, cat.shas["2020-test-study"])
    hist = cat.history("2020-test-study")
    assert hist[-1].created
    assert hist[0].changes[0].label == "Tags" and hist[0].changes[0].added == ["attention"]
    cat.restore("2020-test-study", hist[-1].commit.sha, ME)
    assert cat.datasets["2020-test-study"].content.tags == []
    assert len(cat.history("2020-test-study")) == 3


def test_add_person(cat):
    p = cat.add_person({"id": "jdoe", "name": "Jane Doe", "active": False}, ME)
    cat.refresh()
    assert cat.person("jdoe").name == "Jane Doe" and not cat.person("jdoe").active
    with pytest.raises(StoreError):
        cat.add_person({"id": "jdoe", "name": "Other"}, ME)
