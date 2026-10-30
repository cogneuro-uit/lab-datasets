from conftest import minimal

PAGES = ["/", "/new", "/new/wizard", "/new/quick", "/new/import", "/people", "/changes", "/export.csv"]


def test_pages_render_empty(client):
    for p in PAGES:
        assert client.get(p).status_code == 200, p
    assert client.get("/d/2020-nope").status_code == 404


def test_wizard_create_and_view(client):
    form = {
        "_mode": "wizard", "_year": "2021", "title": "Pupil and memory", "id": "", "contact": "matthias",
        "status": "collecting", "content.modalities": "eye-tracking", "content.tags": "memory",
        "locations.0.kind": "server", "locations.0.target": "/data/pupil",
    }
    r = client.post("/new", data=form)
    assert r.status_code == 303 and r.headers["location"] == "/d/2021-pupil-memory"
    for p in ["/", "/d/2021-pupil-memory", "/d/2021-pupil-memory/edit", "/d/2021-pupil-memory/history", "/changes"]:
        assert client.get(p).status_code == 200, p
    page = client.get("/d/2021-pupil-memory").text
    assert "/data/pupil" in page and "Collecting data" in page


def test_validation_errors_rerender_form(client):
    r = client.post("/new", data={"_mode": "quick", "title": "x", "contact": "matthias", "id": "bad id"})
    assert r.status_code == 422
    assert "Some fields need attention" in r.text and 'value="x"' in r.text


def test_edit_and_retire(client):
    client.post("/new", data={"_mode": "quick", "title": "Test study", "id": "2020-test-study", "contact": "matthias"})
    edit = client.get("/d/2020-test-study/edit").text
    sha = edit.split('name="_base_sha" value="')[1].split('"')[0]
    r = client.post("/d/2020-test-study/edit", data={"_base_sha": sha, "title": "Renamed", "contact": "matthias", "status": "planned"})
    assert r.status_code == 303
    assert "Renamed" in client.get("/d/2020-test-study").text
    client.post("/d/2020-test-study/status", data={"status": "retired"})
    assert "This dataset is retired" in client.get("/d/2020-test-study").text


def test_import(client):
    yaml = "id: 2019-imported\ntitle: Imported one\ncontact: matthias\nstatus: published\n"
    r = client.post("/new/import/check", data={"yaml": yaml})
    assert "Looks good" in r.text
    r = client.post("/new/import/check", data={"yaml": "id: 2019-x\ntitle: T\ncontact: ghost\n"})
    assert "unknown person" in r.text
    r = client.post("/new/import", files={"file": ("x.yaml", yaml.encode())})
    assert r.status_code == 303 and r.headers["location"] == "/d/2019-imported"


def test_people_json_and_suggest_id(client):
    r = client.post("/people", data={"name": "Jane Doe", "email": ""}, headers={"Accept": "application/json"})
    assert r.json() == {"id": "janedoe", "name": "Jane Doe"}
    client.post("/new", data={"_mode": "quick", "title": "Eye tracking", "id": "2024-eye-tracking", "contact": "janedoe"})
    assert client.get("/api/suggest-id", params={"title": "The eye tracking", "year": "2024"}).json()["id"] == "2024-eye-tracking-2"
    assert client.get("/api/check-id", params={"id": "2024-eye-tracking"}).json()["ok"] is False


def test_site_branding(client, repo):
    (repo / "branding").mkdir()
    (repo / "branding/logo.png").write_bytes(b"\x89PNG fake")
    (repo / "site.yaml").write_text("name: Test Group\ncatalog_title: Test datasets\nlogo: branding/logo.png\n")
    page = client.get("/about").text
    assert "<title>About · Test datasets</title>" in page and "Test Group" in page
    assert client.get("/brand/logo").content == b"\x89PNG fake"
    assert client.get("/brand/../people.yaml").status_code == 404
