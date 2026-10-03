"""INV-PLT-10 / INV-PLT-06 over HTTP: viewer never writes, roles gate commands before validation, and the route
table has no generic state-changing endpoint."""

import re
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from tests.factories.api import ApiFactory, problem
from tests.factories.contract import load
from tests.factories.db import SeededTenant
from tests.integration.commands.test_command_audit_and_outbox import log_rows

pytestmark = pytest.mark.integration

PARAM = re.compile(r"\{[^}]+\}")
ADMIN_COMMANDS = [
    "/users",
    "/users/{id}/update",
    "/users/{id}/deactivate",
    "/plants",
    "/plants/{id}/update",
    "/tenant/settings/update",
]
QUALITY_POSTS = ["/files/upload-url"]  # POST that is not a state-changing command, but Q-only
# POSTs that are not commands needing a role: public or any-authenticated-user (API.md 3.1).
NON_COMMAND_POSTS = {
    "/auth/login",
    "/auth/logout",
    "/auth/password-reset/request",
    "/auth/password-reset/confirm",
    "/files/upload-url",
}
# Whole path segments: `/suppliers` and `/supplier-parts` are internal masters routes, `/supplier/...` and
# `/supplier-access/...` are the supplier-facing families (API.md 4).
PUBLIC_PREFIXES = ("/supplier/", "/supplier-access/", "/webhooks/")


def registered_post_paths() -> list[str]:
    """Every POST route of the real app (relative to /api/v1); [] if the app cannot be built yet."""
    try:
        from app.main import create_app

        app = create_app()
    except Exception:
        return []
    paths = {
        route.path.removeprefix("/api/v1")  # type: ignore[attr-defined]
        for route in app.routes
        if "POST" in (getattr(route, "methods", None) or set())
        and getattr(route, "path", "").startswith("/api/v1")
    }
    return sorted(paths)


DYNAMIC_COMMANDS = [
    p
    for p in registered_post_paths()
    if p not in NON_COMMAND_POSTS and not p.startswith(PUBLIC_PREFIXES)
]
ALL_COMMAND_PATHS = sorted(set(ADMIN_COMMANDS) | set(QUALITY_POSTS) | set(DYNAMIC_COMMANDS))


def concrete(path: str) -> str:
    return PARAM.sub(lambda _m: str(uuid4()), path)


@pytest.mark.parametrize("path", ALL_COMMAND_PATHS)
def test_viewer_cannot_call_any_command(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine, path: str
) -> None:
    assert seeded.viewer
    viewer = api.login_as(seeded.viewer)
    before = len(log_rows(app_engine, seeded.id))
    resp = viewer.post(concrete(path), {})
    body = problem(resp)
    assert resp.status_code == 403, f"viewer got {resp.status_code} on POST {path}"
    assert body["code"] == "forbidden"
    assert len(log_rows(app_engine, seeded.id)) == before  # nothing was audited, so nothing ran


@pytest.mark.parametrize("path", ALL_COMMAND_PATHS)
def test_unauthenticated_caller_gets_401_on_every_command(api: ApiFactory, path: str) -> None:
    resp = api.anonymous().post(concrete(path), {}, csrf=False)
    assert resp.status_code == 401, f"anonymous got {resp.status_code} on POST {path}"
    assert problem(resp)["code"] == "unauthenticated"


@pytest.mark.parametrize("path", sorted(set(ADMIN_COMMANDS)))
def test_quality_user_cannot_call_admin_only_commands(
    api: ApiFactory, seeded: SeededTenant, path: str
) -> None:
    assert seeded.quality and seeded.approver
    for user in (seeded.quality, seeded.approver):  # can_approve does not grant admin commands
        resp = api.login_as(user).post(concrete(path), {})
        assert resp.status_code == 403, (
            f"{user.role} (can_approve={user.can_approve}) got {resp.status_code}"
        )


@pytest.mark.parametrize("path", sorted(set(ADMIN_COMMANDS)))
def test_admin_is_not_blocked_by_authorisation_on_admin_commands(
    api: ApiFactory, seeded: SeededTenant, path: str
) -> None:
    assert seeded.admin
    resp = api.login_as(seeded.admin).post(concrete(path), {})
    assert resp.status_code not in (401, 403), resp.text
    assert resp.status_code in (404, 422), (
        f"empty body must be a validation/lookup error, got {resp.status_code}"
    )


def test_authorisation_precedes_validation_and_object_lookup(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    """A forbidden caller learns nothing about whether an object exists or what a valid body looks like."""
    assert seeded.quality
    quality = api.login_as(seeded.quality)
    unknown = quality.post(f"/users/{uuid4()}/update", {"role": "not-a-role"})
    known = quality.post(f"/users/{seeded.quality.id}/update", {"role": "not-a-role"})
    assert unknown.status_code == known.status_code == 403


def test_quality_can_call_the_upload_url_command_that_viewer_cannot(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    assert seeded.quality and seeded.viewer
    body = {"purpose": "document", "content_type": "application/pdf", "size": 1234}
    assert api.login_as(seeded.quality).post("/files/upload-url", body).status_code == 200
    assert api.login_as(seeded.viewer).post("/files/upload-url", body).status_code == 403


def test_read_endpoints_follow_the_role_matrix(api: ApiFactory, seeded: SeededTenant) -> None:
    """API.md 5: /me any; /users A; /plants and /tenant/settings A,Q,V."""
    matrix = {
        "/me": {"admin": 200, "quality": 200, "viewer": 200},
        "/users": {"admin": 200, "quality": 403, "viewer": 403},
        "/plants": {"admin": 200, "quality": 200, "viewer": 200},
        "/tenant/settings": {"admin": 200, "quality": 200, "viewer": 200},
    }
    users = {"admin": seeded.admin, "quality": seeded.quality, "viewer": seeded.viewer}
    for role, user in users.items():
        assert user
        client = api.login_as(user)
        for path, expected in matrix.items():
            assert client.get(path).status_code == expected[role], f"{role} GET {path}"


def test_logout_is_allowed_for_every_role_including_viewer(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    for user in (seeded.admin, seeded.quality, seeded.viewer):
        assert user
        client = api.login_as(user)
        assert client.post("/auth/logout").status_code in (200, 204)


# --- route table scans ------------------------------------------------------------------------------
def test_route_table_has_no_put_patch_or_delete_on_the_api(api: ApiFactory) -> None:
    assert registered_post_paths(), "the API exposes no POST routes yet; nothing to scan"
    offenders = [
        (sorted(getattr(route, "methods", set())), getattr(route, "path", ""))
        for route in api.app.routes
        if getattr(route, "path", "").startswith("/api/v1")
        and set(getattr(route, "methods", set())) & {"PUT", "PATCH", "DELETE"}
    ]
    assert offenders == []


def test_every_post_route_is_a_registered_command_or_a_documented_non_command(
    api: ApiFactory,
) -> None:
    commands = {c.path for c in load("app.core.commands.base", "all_commands")()}
    posts = {p for p in registered_post_paths() if not p.startswith(PUBLIC_PREFIXES)}
    assert posts, "no POST routes found"
    assert posts - commands - NON_COMMAND_POSTS == set(), (
        "POST route that is neither a command nor documented"
    )
    assert commands <= posts


def _resolve(schema: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if ref:
        return _resolve(components[ref.rsplit("/", 1)[-1]], components)
    return schema


def test_no_route_accepts_status_field_outside_commands(api: ApiFactory) -> None:
    """INV-PLT-06: no generic update endpoint takes a status-like field; state changes use named commands."""
    spec = api.app.openapi()
    components = spec.get("components", {}).get("schemas", {})
    offenders: list[str] = []
    for path, item in spec["paths"].items():
        segments = path.strip("/").split("/")
        if "status" in segments or "set-status" in segments:
            offenders.append(f"{path} (status endpoint)")
        for method, operation in item.items():
            body = (
                operation.get("requestBody", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema")
            )
            if method != "post" or not body or not path.endswith("/update"):
                continue
            props = set(_resolve(body, components).get("properties", {}))
            bad = {
                p
                for p in props
                if p in {"status", "active", "archived_at"}
                or p.startswith("status_")
                or p.endswith("_status")
            }
            if bad:
                offenders.append(f"{path} accepts {sorted(bad)}")
    assert offenders == []
    assert any(p.endswith("/update") for p in spec["paths"]), "scan found no update commands"
