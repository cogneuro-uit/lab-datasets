"""Sign in with Slack (OpenID Connect).

Everything except the login pages, static files and branding needs a signed-in user. The
person is found in people.yaml by Slack ID, then by email; people signing in for the first
time are added. Without Slack credentials (development), everyone is LABCAT_USER.
"""

from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .config import Settings
from .store import Catalog

log = logging.getLogger("labcat.auth")

AUTHORIZE_URL = "https://slack.com/openid/connect/authorize"
TOKEN_URL = "https://slack.com/api/openid.connect.token"
USERINFO_URL = "https://slack.com/api/openid.connect.userInfo"
TEAM_CLAIM = "https://slack.com/team_id"

PUBLIC_PREFIXES = ("/login", "/auth/", "/static/", "/brand/")


def safe_next(url: str | None) -> str:
    """Only allow redirects within this site."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return "/"


def is_public(path: str) -> bool:
    return path == "/login" or path.startswith(PUBLIC_PREFIXES)


def login_required_response(request: Request):
    wants_json = "application/json" in request.headers.get("accept", "") or request.headers.get("x-requested-with")
    if request.method == "GET" and not wants_json:
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse("/login?" + urlencode({"next": target}), status_code=303)
    return JSONResponse({"error": "Please sign in again."}, status_code=401)


class SlackLoginError(Exception):
    pass


def make_router(settings: Settings, cat: Catalog, render, redirect) -> APIRouter:
    router = APIRouter()

    def redirect_uri(request: Request) -> str:
        if settings.base_url:
            return settings.base_url.rstrip("/") + "/auth/callback"
        return str(request.url_for("auth_callback"))

    @router.get("/login")
    def login_page(request: Request, next: str = "/", error: str | None = None, signed_out: bool = False):
        if request.session.get("user"):
            return RedirectResponse(safe_next(next), status_code=303)
        return render(request, "login.html", next=safe_next(next), error=error, signed_out=signed_out)

    @router.get("/auth/slack")
    def start(request: Request, next: str = "/"):
        state = secrets.token_urlsafe(24)
        request.session["oauth"] = {"state": state, "next": safe_next(next)}
        params = {
            "response_type": "code",
            "scope": "openid profile email",
            "client_id": settings.slack_client_id,
            "redirect_uri": redirect_uri(request),
            "state": state,
        }
        if settings.slack_team_id:
            params["team"] = settings.slack_team_id
        return RedirectResponse(f"{AUTHORIZE_URL}?{urlencode(params)}", status_code=303)

    async def slack_user(request: Request, code: str) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                TOKEN_URL,
                data={
                    "client_id": settings.slack_client_id,
                    "client_secret": settings.slack_client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri(request),
                },
            )
            tok = r.json()
            if not tok.get("ok"):
                raise SlackLoginError(f"Slack did not accept the sign-in ({tok.get('error', r.status_code)}).")
            r = await client.get(USERINFO_URL, headers={"Authorization": f"Bearer {tok['access_token']}"})
            info = r.json()
            if not info.get("ok"):
                raise SlackLoginError(f"Could not read your Slack profile ({info.get('error', r.status_code)}).")
            return info

    @router.get("/auth/callback", name="auth_callback")
    async def callback(request: Request, code: str = "", state: str = "", error: str = ""):
        pending = request.session.pop("oauth", None)
        login = lambda msg: RedirectResponse("/login?" + urlencode({"error": msg}), status_code=303)  # noqa: E731
        if error:
            return login("Sign-in was cancelled." if error == "access_denied" else f"Slack reported: {error}")
        if not pending or not code or not secrets.compare_digest(state, pending["state"]):
            return login("The sign-in link expired. Please try again.")
        try:
            info = await slack_user(request, code)
        except (SlackLoginError, httpx.HTTPError) as e:
            log.warning("Slack sign-in failed: %s", e)
            return login(str(e) if isinstance(e, SlackLoginError) else "Could not reach Slack. Please try again.")
        team = info.get(TEAM_CLAIM)
        if settings.slack_team_id and team != settings.slack_team_id:
            return login("This Slack workspace has no access to the catalog.")
        if not settings.slack_team_id:
            log.warning("LABCAT_SLACK_TEAM_ID is not set; signed in from workspace %s. Set it to restrict access.", team)
        name = info.get("name") or " ".join(x for x in (info.get("given_name"), info.get("family_name")) if x)
        person = cat.person_for_slack(info["sub"], name or info["sub"], info.get("email"))
        request.session.clear()
        request.session["user"] = person.id
        if info.get("picture"):
            request.session["picture"] = info["picture"]
        log.info("%s signed in", person.id)
        return redirect(pending["next"], f"Welcome, {person.name.split()[0]}!")

    @router.post("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login?signed_out=1", status_code=303)

    return router
