"""INV-PLT-10 for the P02 commands, over HTTP and listed explicitly (so a route that silently failed to register cannot
make the dynamic route-scan tests pass vacuously), plus the read-side role matrix of API.md 5."""

import re
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from tests.factories.api import ApiFactory, new_key, problem
from tests.factories.db import SeededTenant
from tests.integration.commands.test_command_audit_and_outbox import log_rows, outbox_rows

pytestmark = pytest.mark.integration

PARAM = re.compile(r"\{[^}]+\}")

# Every POST of the P02 plan table (2.2). Imports are Q-only reads and commands.
P02_COMMAND_PATHS = [
    "/suppliers",
    "/suppliers/{id}/update",
    "/suppliers/{id}/archive",
    "/suppliers/{id}/change-status",
    "/suppliers/{id}/contacts",
    "/contacts/{id}/update",
    "/contacts/{id}/set-quality-contact",
    "/contacts/{id}/verify/start",
    "/contacts/{id}/verify/confirm",
    "/contacts/{id}/disable",
    "/contacts/{id}/replace",
    "/contacts/{id}/consents",
    "/customers",
    "/customers/{id}/update",
    "/customers/{id}/archive",
    "/parts",
    "/parts/{id}/update",
    "/parts/{id}/archive",
    "/customer-parts",
    "/customer-parts/{id}/archive",
    "/supplier-parts",
    "/supplier-parts/{id}/update",
    "/supplier-parts/{id}/archive",
    "/imports",
    "/imports/{id}/map",
    "/imports/{id}/validate",
    "/imports/{id}/cancel",
    "/imports/{id}/confirm",
]
IMPORT_READS = [
    "/imports",
    "/imports/{id}",
    "/imports/{id}/preview",
    "/imports/{id}/records",
    "/imports/{id}/report.xlsx",
]
MASTER_READS = [
    "/suppliers",
    "/suppliers/{id}",
    "/suppliers/{id}/contacts",
    "/contacts/{id}",
    "/customers",
    "/parts",
    "/parts/{id}",
    "/supplier-parts",
    "/customer-parts",
]


def concrete(path: str) -> str:
    return PARAM.sub(lambda _m: str(uuid4()), path)


def assert_route(api: ApiFactory, method: str, template: str) -> None:
    """The route exists in the app's OpenAPI document. An unregistered path also answers 404, which would
    otherwise satisfy every "not blocked / not found" assertion below without proving anything."""
    paths = {
        PARAM.sub("{}", p.removeprefix("/api/v1")): item
        for p, item in api.app.openapi()["paths"].items()
    }
    key = PARAM.sub("{}", template)
    assert key in paths and method.lower() in paths[key], (
        f"{method} {template} is not a registered route"
    )


def test_the_plan_lists_twenty_eight_p02_commands() -> None:
    assert len(P02_COMMAND_PATHS) == len(set(P02_COMMAND_PATHS)) == 28


@pytest.mark.parametrize("path", P02_COMMAND_PATHS)
def test_viewer_cannot_call_any_p02_command(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine, path: str
) -> None:
    assert seeded.viewer
    viewer = api.login_as(seeded.viewer)
    logs, events = len(log_rows(app_engine, seeded.id)), len(outbox_rows(app_engine, seeded.id))
    resp = viewer.post(concrete(path), {}, key=new_key())
    assert resp.status_code == 403, f"viewer got {resp.status_code} on POST {path}"
    assert problem(resp)["code"] == "forbidden"
    assert (
        len(log_rows(app_engine, seeded.id)) == logs
        and len(outbox_rows(app_engine, seeded.id)) == events
    )


@pytest.mark.parametrize("path", P02_COMMAND_PATHS)
def test_anonymous_caller_gets_401_on_every_p02_command(api: ApiFactory, path: str) -> None:
    resp = api.anonymous().post(concrete(path), {}, csrf=False)
    assert resp.status_code == 401 and problem(resp)["code"] == "unauthenticated"


@pytest.mark.parametrize("path", [p for p in P02_COMMAND_PATHS if not p.endswith("/change-status")])
def test_quality_and_admin_are_not_blocked_by_authorisation_on_p02_commands(
    api: ApiFactory, seeded: SeededTenant, path: str
) -> None:
    """Admin holds every Q permission (A-70). An empty body must fail validation or lookup, never authorisation."""
    assert_route(api, "POST", path)
    for user in (seeded.quality, seeded.admin):
        assert user
        resp = api.login_as(user).post(concrete(path), {}, key=new_key())
        assert resp.status_code in (404, 422), (
            f"{user.role} POST {path}: {resp.status_code} {resp.text}"
        )


def test_change_status_requires_can_approve_for_every_role(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    assert_route(api, "POST", "/suppliers/{id}/change-status")
    path = concrete("/suppliers/{id}/change-status")
    codes: dict[str, int] = {}
    for label, user in (
        ("admin", seeded.admin),
        ("quality", seeded.quality),
        ("approver", seeded.approver),
        ("viewer", seeded.viewer),
    ):
        assert user
        codes[label] = api.login_as(user).post(path, {}, key=new_key()).status_code
    assert (codes["admin"], codes["quality"], codes["viewer"]) == (403, 403, 403)
    assert codes["approver"] in (404, 422), "the approver is authorised; the empty body then fails"


@pytest.mark.parametrize("path", MASTER_READS)
def test_every_internal_role_can_read_masters(
    api: ApiFactory, seeded: SeededTenant, path: str
) -> None:
    assert_route(api, "GET", path)
    for user in (seeded.admin, seeded.quality, seeded.viewer):
        assert user
        resp = api.login_as(user).get(concrete(path))
        assert resp.status_code in (200, 404), f"{user.role} GET {path}: {resp.status_code}"
        assert resp.status_code != 403


@pytest.mark.parametrize("path", IMPORT_READS)
def test_imports_are_visible_to_quality_and_admin_only(
    api: ApiFactory, seeded: SeededTenant, path: str
) -> None:
    """API.md 5: imports queries are `Q`; the Viewer is denied (A-70 for the report; the rest follows the table)."""
    assert seeded.viewer and seeded.quality and seeded.admin
    assert_route(api, "GET", path)
    assert api.login_as(seeded.viewer).get(concrete(path)).status_code == 403
    for user in (seeded.quality, seeded.admin):
        assert api.login_as(user).get(concrete(path)).status_code in (200, 404)


@pytest.mark.parametrize("path", MASTER_READS + IMPORT_READS)
def test_anonymous_cannot_read_masters_or_imports(api: ApiFactory, path: str) -> None:
    resp = api.anonymous().get(concrete(path))
    assert resp.status_code == 401 and problem(resp)["code"] == "unauthenticated"
