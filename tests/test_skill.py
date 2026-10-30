import io
import subprocess
import sys
import zipfile

import pytest

from labcat import skill
from conftest import ME


@pytest.fixture
def skill_dir(cat, tmp_path):
    cat.add_person({"id": "jdoe", "name": "Jane Doe", "email": "jane@example.org", "slack_handle": "jane"}, ME)
    cat.refresh()
    with zipfile.ZipFile(io.BytesIO(skill.build_zip(cat, "http://catalog.test/"))) as z:
        z.extractall(tmp_path)
    return tmp_path / "lab-dataset-yaml"


def validate(skill_dir, path):
    return subprocess.run([sys.executable, skill_dir / "scripts/validate.py", path], capture_output=True, text=True)


def test_zip_contents(skill_dir):
    names = {p.relative_to(skill_dir).as_posix() for p in skill_dir.rglob("*") if p.is_file()}
    assert {"SKILL.md", "scripts/validate.py", "reference/schema.json", "reference/people.yaml",
            "reference/example.yaml", "reference/datasets.yaml"} <= names
    people = (skill_dir / "reference/people.yaml").read_text()
    assert "jdoe" in people and "slack_handle: jane" in people and "@" not in people
    md = (skill_dir / "SKILL.md").read_text()
    assert "http://catalog.test/new/import" in md and "$catalog_url" not in md


def test_example_valid_in_skill_and_app(skill_dir, client, tmp_path):
    example = (skill_dir / "reference/example.yaml").read_text()
    f = tmp_path / "2019-eeg-attention.yaml"
    f.write_text(example)
    assert validate(skill_dir, f).returncode == 0
    assert "Looks good" in client.post("/new/import/check", data={"yaml": example}).text


def test_validator_rejects_bad_file(skill_dir, tmp_path):
    f = tmp_path / "2024-x.yaml"
    f.write_text("id: 2024-x\ntitle: Something\ncontact: ghost\nstatus: done\nfoo: 1\n")
    r = validate(skill_dir, f)
    assert r.returncode == 1
    for msg in ("unknown person id 'ghost'", "'done' is not allowed", "foo: unknown field"):
        assert msg in r.stdout
