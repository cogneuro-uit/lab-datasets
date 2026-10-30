import pytest
from fastapi.testclient import TestClient

from labcat.config import Settings
from labcat.gitrepo import GitRepo
from labcat.models import Person
from labcat.store import Catalog, init_data_repo

ME = Person(id="matthias", name="Matthias Mittner", email="m@example.org")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "data"
    init_data_repo(root, ME)
    return root


@pytest.fixture
def cat(repo):
    c = Catalog(repo, GitRepo(repo, "Lab catalog", "catalog@lab.local"))
    c.refresh()
    return c


@pytest.fixture
def client(repo):
    from labcat.web import create_app

    return TestClient(create_app(Settings(data_dir=repo, user="matthias")), follow_redirects=False)


def minimal(**kw):
    return {"id": "2020-test-study", "title": "Test study", "contact": "matthias"} | kw
