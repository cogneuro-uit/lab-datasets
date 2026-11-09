from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from labcat import auth
from labcat.config import Settings, read_env_file
from labcat.store import person_id_from_name

TEAM = "T0LAB"


def slack_api(userinfo):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("openid.connect.token"):
            body = parse_qs(request.content.decode())
            assert body["code"] == ["good-code"] and body["client_secret"] == ["s3cret"]
            return httpx.Response(200, json={"ok": True, "access_token": "xoxp-1"})
        assert request.headers["authorization"] == "Bearer xoxp-1"
        return httpx.Response(200, json={"ok": True, **userinfo})

    return handler


@pytest.fixture
def make_client(repo, monkeypatch):
    def make(userinfo, team_id=TEAM):
        real = httpx.AsyncClient
        monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(slack_api(userinfo)), **kw))
        settings = Settings(data_dir=repo, user="matthias", slack_client_id="123.456", slack_client_secret="s3cret",
                            slack_team_id=team_id, secret_key="test-key")
        from labcat.web import create_app

        return TestClient(create_app(settings), follow_redirects=False)

    return make


def sign_in(client, next_url="/"):
    r = client.get("/auth/slack", params={"next": next_url})
    assert r.status_code == 303 and r.headers["location"].startswith(auth.AUTHORIZE_URL)
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["team"] == [TEAM] and q["scope"] == ["openid profile email"]
    return client.get("/auth/callback", params={"code": "good-code", "state": q["state"][0]})


def info(**kw):
    return {"sub": "U999", "name": "Ada Lovelace", "email": "ada@example.org", auth.TEAM_CLAIM: TEAM} | kw


def test_everything_needs_login(make_client):
    c = make_client(info())
    r = c.get("/d/x?a=1")
    assert r.status_code == 303 and r.headers["location"] == "/login?next=%2Fd%2Fx%3Fa%3D1"
    assert c.post("/new", data={}).status_code == 401
    assert c.get("/static/app.css").status_code == 200
    page = c.get("/login").text
    assert "Sign in with Slack" in page and 'href="/new"' not in page


def test_first_sign_in_adds_person(make_client, repo):
    c = make_client(info())
    r = sign_in(c, "/todos")
    assert r.status_code == 303 and r.headers["location"] == "/todos"
    people = (repo / "people.yaml").read_text()
    assert "id: ada-lovelace" in people and "slack_id: U999" in people
    page = c.get("/").text
    assert "Signed in as Ada Lovelace" in page
    c.post("/new", data={"_mode": "quick", "title": "Ada's study", "id": "2024-ada", "contact": "ada-lovelace"})
    assert c.get("/d/2024-ada").status_code == 200
    log = c.get("/d/2024-ada/history").text
    assert "Ada Lovelace" in log
    assert c.post("/logout").headers["location"] == "/login?signed_out=1"
    assert c.get("/").status_code == 303


def test_sign_in_links_existing_person_by_email(make_client, repo):
    c = make_client(info(sub="U1", name="M. Mittner", email="M@Example.org"))
    assert sign_in(c).status_code == 303
    people = (repo / "people.yaml").read_text()
    assert "slack_id: U1" in people and people.count("- id: ") == 1
    assert "Signed in as Matthias Mittner" in c.get("/").text


def test_other_workspace_and_bad_state_rejected(make_client, repo):
    c = make_client(info(**{auth.TEAM_CLAIM: "T0OTHER"}))
    r = sign_in(c)
    assert r.headers["location"].startswith("/login?error=") and c.get("/").status_code == 303
    assert "U999" not in (repo / "people.yaml").read_text()
    c.get("/auth/slack")
    r = c.get("/auth/callback", params={"code": "good-code", "state": "forged"})
    assert "expired" in c.get(r.headers["location"]).text


def test_safe_next_and_helpers(tmp_path):
    assert auth.safe_next("//evil.com") == "/" and auth.safe_next("https://x") == "/" and auth.safe_next("/d/a") == "/d/a"
    assert person_id_from_name("Nya Mehnwolo Boayue") == "nya-boayue" and person_id_from_name("Gábor Csifcsák") == "gabor-csifcsak"
    (tmp_path / ".env").write_text("# c\nA=1\nB = 'two'\n\n")
    assert read_env_file(tmp_path / ".env") == {"A": "1", "B": "two"}
