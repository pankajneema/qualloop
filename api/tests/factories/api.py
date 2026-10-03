"""HTTP helpers: an authenticated API client with cookie jar, CSRF double-submit and Origin handling."""

from contextlib import ExitStack
from typing import Any, cast
from uuid import uuid4

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.factories.db import SeededUser
from tests.factories.env import API, PASSWORD, origin


class ApiClient:
    """One browser-like session. https base URL so Secure cookies are sent back (ADR-008)."""

    def __init__(self, app: FastAPI, stack: ExitStack, ip: str) -> None:
        self.ip = ip
        self.http = stack.enter_context(
            TestClient(
                app,
                base_url="https://testserver",
                raise_server_exceptions=False,
                client=(ip, 50000),
            )
        )

    # -- cookies --------------------------------------------------------------------------------
    @property
    def csrf_token(self) -> str | None:
        return cast(str | None, self.http.cookies.get("ql_csrf"))

    @property
    def session_token(self) -> str | None:
        return cast(str | None, self.http.cookies.get("ql_session"))

    # -- requests -------------------------------------------------------------------------------
    def login(self, user: SeededUser | str, password: str = PASSWORD) -> httpx.Response:
        email = user if isinstance(user, str) else user.email
        return self.public_post("/auth/login", {"email": email, "password": password})

    def public_post(self, path: str, json: Any = None) -> httpx.Response:
        """POST without cookie-auth CSRF protection (login, password reset): a browser still sends Origin."""
        return cast(
            httpx.Response,
            self.http.post(f"{API}{path}", json=json, headers={"Origin": origin()}),
        )

    def get(self, path: str, **kw: Any) -> httpx.Response:
        return cast(httpx.Response, self.http.get(f"{API}{path}", **kw))

    def post(
        self,
        path: str,
        json: Any = None,
        *,
        key: str | None = None,
        csrf: bool = True,
        with_origin: bool = True,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        hdrs: dict[str, str] = {}
        if with_origin:
            hdrs["Origin"] = origin()
        if csrf and self.csrf_token:
            hdrs["X-CSRF-Token"] = self.csrf_token
        if key:
            hdrs["Idempotency-Key"] = key
        hdrs.update(headers or {})
        if content is not None:
            return cast(
                httpx.Response, self.http.post(f"{API}{path}", content=content, headers=hdrs)
            )
        return cast(httpx.Response, self.http.post(f"{API}{path}", json=json, headers=hdrs))


class ApiFactory:
    def __init__(self, app: FastAPI, stack: ExitStack) -> None:
        self.app = app
        self._stack = stack

    def anonymous(self, ip: str = "203.0.113.10") -> ApiClient:
        return ApiClient(self.app, self._stack, ip)

    def login_as(self, user: SeededUser, ip: str = "203.0.113.10") -> ApiClient:
        client = self.anonymous(ip)
        resp = client.login(user)
        assert resp.status_code == 200, f"login failed: {resp.status_code} {resp.text}"
        return client


def new_key() -> str:
    return str(uuid4())


def problem(resp: httpx.Response) -> dict[str, Any]:
    """Parse and sanity-check an RFC 9457 body."""
    assert resp.headers["content-type"].startswith("application/problem+json"), resp.headers
    body: dict[str, Any] = resp.json()
    assert body["status"] == resp.status_code
    assert body["request_id"] == resp.headers["x-request-id"]
    return body
