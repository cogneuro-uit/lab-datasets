import pytest
from pydantic import ValidationError

from labcat.forms import parse_dataset_form
from labcat.models import Dataset


def test_doi_is_normalized():
    ds = Dataset.model_validate({
        "id": "2020-x", "title": "abc", "contact": "a",
        "outputs": {"publications": [{"doi": "https://doi.org/10.1234/ABC.5"}]},
    })
    assert ds.outputs.publications[0].doi == "10.1234/ABC.5"


@pytest.mark.parametrize("bad", ["2020-X", "20-x", "2020_x", "2020-"])
def test_bad_ids_rejected(bad):
    with pytest.raises(ValidationError):
        Dataset.model_validate({"id": bad, "title": "abc", "contact": "a"})


def test_partial_dates_and_empty_numbers():
    ds = Dataset.model_validate({
        "id": "2020-x", "title": "abc", "contact": "a",
        "collected": {"start": "2019", "end": "2019-11"}, "content": {"n_participants": ""},
    })
    assert ds.collected.start == "2019" and ds.content.n_participants is None
    with pytest.raises(ValidationError):
        Dataset.model_validate({"id": "2020-x", "title": "abc", "contact": "a", "content": {"n_participants": "-3"}})


def test_yaml_data_drops_empty_values():
    ds = Dataset.model_validate({"id": "2020-x", "title": "abc", "contact": "a"})
    assert ds.to_yaml_data() == {"id": "2020-x", "title": "abc", "status": "planned", "contact": "a"}


def test_parse_form():
    items = [
        ("_base_sha", "abc"), ("title", " T "), ("content.tags", "a"), ("content.tags", "b"), ("content.tags", "a"),
        ("locations.0.kind", "osf"), ("locations.0.target", "https://osf.io/x"),
        ("locations.5.kind", "server"), ("locations.5.target", "/data/x"), ("locations.5.is_backup", "on"),
        ("locations.7.kind", "other"), ("locations.7.target", ""), ("locations.7.note", ""),
        ("outputs.code.0.url", ""),
    ]
    d = parse_dataset_form(items)
    assert d["title"] == "T"
    assert d["content"]["tags"] == ["a", "b"]
    assert d["locations"] == [
        {"kind": "osf", "url": "https://osf.io/x"},
        {"kind": "server", "path": "/data/x", "is_backup": True},
    ]
    assert d["outputs"]["code"] == []
    assert "_base_sha" not in d


def test_parse_form_todos():
    items = [
        ("title", "T"), ("todos.0.text", "Backup on Teams"), ("todos.0.assignee", "matthias"),
        ("todos.2.text", "Upload"), ("todos.2.done", "on"), ("todos.4.text", ""), ("todos.4.assignee", ""),
    ]
    d = parse_dataset_form(items)
    assert d["todos"] == [
        {"text": "Backup on Teams", "assignee": "matthias"},
        {"text": "Upload", "done": True},
    ]
    ds = Dataset.model_validate({"id": "2020-x", "title": "abc", "contact": "a", "todos": d["todos"]})
    assert [t.text for t in ds.open_todos] == ["Backup on Teams"]
    assert ds.to_yaml_data()["todos"] == [{"text": "Backup on Teams", "assignee": "matthias"}, {"text": "Upload", "done": True}]
