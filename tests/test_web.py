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


def test_slack_channel_and_canvases(client, repo):
    (repo / "site.yaml").write_text("name: G\nslack_workspace: https://lab.slack.com\n")
    form = {
        "_mode": "quick", "title": "Slack study", "id": "2024-slack-study", "contact": "matthias",
        "slack.channel": "#Slack-Study", "slack.canvases.0.url": "https://lab.slack.com/docs/T1/F1",
        "slack.canvases.0.title": "Plan", "slack.canvases.3.url": "", "slack.canvases.3.title": "",
    }
    assert client.post("/new", data=form).status_code == 303
    text = (repo / "datasets/2024-slack-study.yaml").read_text()
    assert "channel: slack-study" in text and "title: Plan" in text and text.count("url:") == 1
    page = client.get("/d/2024-slack-study").text
    assert "https://lab.slack.com/app_redirect?channel=slack-study" in page and "#slack-study" in page
    bad = client.post("/new", data=form | {"_mode": "wizard", "id": "2024-slack-two", "slack.channel": "not a channel"})
    assert bad.status_code == 422 and "use the channel name" in bad.text


def test_todos(client, repo):
    form = {
        "_mode": "quick", "title": "Todo study", "id": "2024-todo-study", "contact": "matthias",
        "todos.0.text": "Make a backup copy on Teams", "todos.0.assignee": "matthias",
    }
    assert client.post("/new", data=form).status_code == 303
    page = client.get("/d/2024-todo-study").text
    assert "Make a backup copy on Teams" in page and 'action="/d/2024-todo-study/todos/0"' in page
    assert '"todos": 1' in client.get("/").text
    assert client.post("/d/2024-todo-study/todos/0", data={"done": "true"}).status_code == 303
    assert "done: true" in (repo / "datasets/2024-todo-study.yaml").read_text()
    assert '"todos": 0' in client.get("/").text
    assert client.post("/d/2024-todo-study/todos/5", data={"done": "true"}).status_code == 404
    bad = client.post("/new", data=form | {"_mode": "wizard", "id": "2024-todo-two", "todos.0.assignee": "ghost"})
    assert bad.status_code == 422 and "unknown person &#39;ghost&#39;" in bad.text
