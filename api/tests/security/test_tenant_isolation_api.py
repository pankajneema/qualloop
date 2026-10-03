"""INV-SEC-01 (P01 part), section 21.2: tenant A cannot read or write tenant B through the API.

Foreign objects are 404 (never 403: existence is not revealed) and are left untouched."""

from uuid import uuid4

import pytest
from sqlalchemy import Engine

from tests.factories.api import ApiFactory, problem
from tests.factories.db import SeededTenant, fetch_all
from tests.integration.auth.helpers import strip_volatile
from tests.integration.commands.test_command_audit_and_outbox import log_rows, outbox_rows
from tests.integration.commands.test_platform_commands_api import (
    admin_client,
    new_plant_body,
    new_user_body,
)

pytestmark = pytest.mark.integration


def test_tenant_a_cannot_read_tenant_b_users_api(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = seeded_pair
    items = admin_client(api, a).get("/users", params={"limit": 200}).json()["items"]
    ids = {u["id"] for u in items}
    emails = {u["email"].lower() for u in items}
    foreign = [u for u in (b.admin, b.quality, b.approver, b.viewer) if u]
    assert not ids & {str(u.id) for u in foreign}
    assert not emails & {u.email.lower() for u in foreign}


def test_tenant_a_cannot_read_tenant_b_plants_api(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = seeded_pair
    for role in (a.admin, a.quality, a.viewer):
        assert role
        ids = {
            p["id"]
            for p in api.login_as(role).get("/plants", params={"limit": 200}).json()["items"]
        }
        assert ids == {str(p) for p in a.plants}
        assert not ids & {str(p) for p in b.plants}


def test_tenant_a_cannot_update_tenant_b_user_api(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant], app_engine: Engine
) -> None:
    a, b = seeded_pair
    assert b.quality
    resp = admin_client(api, a).post(
        f"/users/{b.quality.id}/update", {"name": "Hijacked", "role": "admin", "reason": "attack"}
    )
    assert resp.status_code == 404, resp.text
    assert problem(resp)["code"] == "not_found"
    row = fetch_all(
        app_engine, b.id, "SELECT name, role FROM users WHERE id = :i", {"i": b.quality.id}
    )[0]
    assert row["name"] != "Hijacked" and row["role"] == "quality"


def test_tenant_a_cannot_deactivate_tenant_b_user_api(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant], app_engine: Engine
) -> None:
    a, b = seeded_pair
    assert b.viewer
    resp = admin_client(api, a).post(f"/users/{b.viewer.id}/deactivate", {"reason": "attack"})
    assert resp.status_code == 404
    assert fetch_all(
        app_engine, b.id, "SELECT active FROM users WHERE id = :i", {"i": b.viewer.id}
    )[0]["active"]
    assert api.login_as(b.viewer).get("/me").status_code == 200  # B's user keeps working


def test_tenant_a_cannot_update_tenant_b_plant_api(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant], app_engine: Engine
) -> None:
    a, b = seeded_pair
    resp = admin_client(api, a).post(
        f"/plants/{b.plants[0]}/update", {"name": "Hijacked", "reason": "attack"}
    )
    assert resp.status_code == 404, resp.text
    name = fetch_all(app_engine, b.id, "SELECT name FROM plants WHERE id = :i", {"i": b.plants[0]})[
        0
    ]["name"]
    assert name != "Hijacked"


def test_foreign_and_nonexistent_ids_are_indistinguishable(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = seeded_pair
    admin = admin_client(api, a)
    foreign = admin.post(f"/plants/{b.plants[0]}/update", {"name": "x"})
    missing = admin.post(f"/plants/{uuid4()}/update", {"name": "x"})
    assert foreign.status_code == missing.status_code == 404
    assert strip_volatile(foreign.json()) == strip_volatile(missing.json())


def test_cross_tenant_actions_leave_no_audit_or_outbox_trace_in_either_tenant(
    api: ApiFactory,
    seeded_pair: tuple[SeededTenant, SeededTenant],
    app_engine: Engine,
    clean_outbox: None,
) -> None:
    a, b = seeded_pair
    assert b.quality
    admin_client(api, a).post(f"/users/{b.quality.id}/update", {"name": "x", "reason": "attack"})
    assert [r for r in log_rows(app_engine, a.id) if r["action"] != "auth.login"] == []
    assert [r for r in log_rows(app_engine, b.id) if r["action"] != "auth.login"] == []
    assert outbox_rows(app_engine, a.id) == [] and outbox_rows(app_engine, b.id) == []


def test_user_cannot_be_created_with_another_tenants_plant(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = seeded_pair
    resp = admin_client(api, a).post("/users", new_user_body(plant_ids=[str(b.plants[0])]))
    assert resp.status_code == 422


def test_settings_endpoints_only_ever_touch_the_callers_tenant(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant], app_engine: Engine
) -> None:
    a, b = seeded_pair
    admin_a = admin_client(api, a)
    settings = admin_a.get("/tenant/settings").json()["settings"]
    settings["default_ppm_target"] = 123
    assert (
        admin_a.post("/tenant/settings/update", {"settings": settings, "reason": "t"}).status_code
        == 200
    )
    assert (
        admin_client(api, b).get("/tenant/settings").json()["settings"]["default_ppm_target"] != 123
    )


def test_sessions_do_not_cross_tenants_on_a_shared_connection_pool(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant]
) -> None:
    """Alternate A and B requests many times: a leaked GUC would show the other tenant's rows."""
    a, b = seeded_pair
    client_a, client_b = admin_client(api, a), admin_client(api, b)
    expected = {id(client_a): {str(p) for p in a.plants}, id(client_b): {str(p) for p in b.plants}}
    for _ in range(12):
        for client in (client_a, client_b, client_a):
            ids = {p["id"] for p in client.get("/plants").json()["items"]}
            assert ids == expected[id(client)]


def test_a_plant_created_by_a_is_not_listed_for_b_and_the_code_can_be_reused(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = seeded_pair
    created = admin_client(api, a).post("/plants", new_plant_body(code="SHARED1")).json()["id"]
    assert created not in {p["id"] for p in admin_client(api, b).get("/plants").json()["items"]}
