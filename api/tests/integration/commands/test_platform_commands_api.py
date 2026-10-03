"""API.md 3.1 platform commands over HTTP: happy path, validation, authorisation, tenant isolation."""

import re
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine

from tests.factories.api import ApiClient, ApiFactory, problem
from tests.factories.db import SeededTenant, create_plant, create_tenant, create_user, fetch_all

pytestmark = pytest.mark.integration

OK = (200, 201)
UUID7 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def admin_client(api: ApiFactory, t: SeededTenant) -> ApiClient:
    assert t.admin
    return api.login_as(t.admin)


def new_user_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "email": f"new.{uuid4().hex[:10]}@example.test",
        "name": "New Person",
        "role": "quality",
    }
    body.update(over)
    return body


def new_plant_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"name": "Chakan Plant", "code": f"C{uuid4().hex[:5].upper()}"}
    body.update(over)
    return body


# =================================================================================================
# POST /users
# =================================================================================================
def test_admin_creates_a_user_and_gets_the_read_model_without_password_hash(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    admin = admin_client(api, seeded)
    body = new_user_body(
        can_approve=True, plant_ids=[str(seeded.plants[0])], mobile="+919876543210", role="quality"
    )
    resp = admin.post("/users", body)
    assert resp.status_code in OK, resp.text
    data = resp.json()
    assert UUID7.match(data["id"])
    assert data["email"].lower() == body["email"].lower()
    assert (data["name"], data["role"], data["can_approve"], data["active"]) == (
        "New Person",
        "quality",
        True,
        True,
    )
    assert data["plant_ids"] == [str(seeded.plants[0])]
    assert data["mobile"] == "+919876543210"
    assert "password_hash" not in data and "password" not in data
    rows = fetch_all(
        app_engine, seeded.id, "SELECT * FROM users WHERE id = :i", {"i": UUID(data["id"])}
    )
    assert len(rows) == 1
    assert rows[0]["password_hash"] is None  # first password is set through the reset flow
    assert rows[0]["tenant_id"] == seeded.id


def test_created_user_belongs_to_the_callers_tenant_even_if_the_body_claims_another(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant], app_engine: Engine
) -> None:
    a, b = seeded_pair
    resp = admin_client(api, a).post("/users", new_user_body(tenant_id=str(b.id)))
    if resp.status_code in OK:
        assert fetch_all(
            app_engine, a.id, "SELECT 1 FROM users WHERE id = :i", {"i": UUID(resp.json()["id"])}
        )
        assert not fetch_all(
            app_engine, b.id, "SELECT 1 FROM users WHERE id = :i", {"i": UUID(resp.json()["id"])}
        )
    else:
        assert resp.status_code == 422  # unknown field rejected: also acceptable


@pytest.mark.parametrize(
    "override",
    [
        {"email": "not-an-email"},
        {"email": ""},
        {"name": ""},
        {"role": "owner"},
        {"role": "supplier"},
        {"mobile": "98765 43210"},
        {"mobile": "9876543210"},
        {"can_approve": "true"},  # strict types: no string-to-bool coercion
        {"plant_ids": "abc"},
        {"plant_ids": ["not-a-uuid"]},
    ],
    ids=lambda o: next(iter(o)) + "=" + str(next(iter(o.values())))[:12],
)
def test_create_user_rejects_invalid_input_with_422_validation_error(
    api: ApiFactory, seeded: SeededTenant, override: dict[str, Any]
) -> None:
    resp = admin_client(api, seeded).post("/users", new_user_body(**override))
    body = problem(resp)
    assert resp.status_code == 422
    assert body["code"] == "validation_error"
    assert body["errors"], body


def test_create_user_rejects_a_plant_from_another_tenant_without_creating_the_user(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant], app_engine: Engine
) -> None:
    a, b = seeded_pair
    body = new_user_body(plant_ids=[str(b.plants[0])])
    resp = admin_client(api, a).post("/users", body)
    assert resp.status_code == 422, resp.text
    assert problem(resp)["code"] in {"validation_error", "invariant_violation"}
    assert not fetch_all(
        app_engine, a.id, "SELECT 1 FROM users WHERE email = :e", {"e": body["email"]}
    )


def test_create_user_rejects_a_duplicate_email_in_any_case_without_500(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    admin = admin_client(api, seeded)
    email = f"dup.{uuid4().hex[:8]}@example.test"
    assert admin.post("/users", new_user_body(email=email)).status_code in OK
    resp = admin.post("/users", new_user_body(email=email.upper()))
    assert resp.status_code in (409, 422), resp.text
    problem(resp)


def test_create_user_rejects_an_email_already_used_in_another_tenant(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = seeded_pair
    assert b.quality
    resp = admin_client(api, a).post("/users", new_user_body(email=b.quality.email))
    assert resp.status_code in (409, 422), resp.text  # A-03: email is globally unique


# =================================================================================================
# POST /users/{id}/update
# =================================================================================================
def test_update_user_name_and_mobile_needs_no_reason(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.quality
    resp = admin_client(api, seeded).post(
        f"/users/{seeded.quality.id}/update", {"name": "Renamed Q", "mobile": "+919812345678"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Renamed Q"
    row = fetch_all(
        app_engine,
        seeded.id,
        "SELECT name, mobile FROM users WHERE id = :i",
        {"i": seeded.quality.id},
    )[0]
    assert (row["name"], row["mobile"]) == ("Renamed Q", "+919812345678")


@pytest.mark.parametrize("change", [{"role": "admin"}, {"can_approve": True}])
def test_update_user_role_or_can_approve_requires_a_reason(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine, change: dict[str, Any]
) -> None:
    assert seeded.quality
    admin = admin_client(api, seeded)
    resp = admin.post(f"/users/{seeded.quality.id}/update", change)
    body = problem(resp)
    assert resp.status_code == 422
    assert body["code"] == "validation_error"
    assert "reason" in {e["field"] for e in body["errors"]}
    row = fetch_all(
        app_engine,
        seeded.id,
        "SELECT role, can_approve FROM users WHERE id = :i",
        {"i": seeded.quality.id},
    )[0]
    assert (row["role"], row["can_approve"]) == ("quality", False)  # unchanged
    ok = admin.post(
        f"/users/{seeded.quality.id}/update", {**change, "reason": "Promoted to Head of Quality"}
    )
    assert ok.status_code == 200, ok.text
    row = fetch_all(
        app_engine,
        seeded.id,
        "SELECT role, can_approve FROM users WHERE id = :i",
        {"i": seeded.quality.id},
    )[0]
    assert (row["role"], row["can_approve"]) != ("quality", False)


def test_update_user_plant_ids_validates_tenant_membership(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = seeded_pair
    assert a.quality
    resp = admin_client(api, a).post(
        f"/users/{a.quality.id}/update", {"plant_ids": [str(b.plants[0])], "reason": "Move user"}
    )
    assert resp.status_code == 422, resp.text
    ok = admin_client(api, a).post(
        f"/users/{a.quality.id}/update", {"plant_ids": [str(a.plants[1])], "reason": "Move user"}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["plant_ids"] == [str(a.plants[1])]


def test_update_unknown_user_is_404_not_found(api: ApiFactory, seeded: SeededTenant) -> None:
    resp = admin_client(api, seeded).post(f"/users/{uuid4()}/update", {"name": "Ghost"})
    assert problem(resp)["code"] == "not_found"
    assert resp.status_code == 404


def test_update_cannot_change_active_state_only_deactivate_does(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    """INV-PLT-06: state changes only via named commands."""
    assert seeded.quality
    resp = admin_client(api, seeded).post(
        f"/users/{seeded.quality.id}/update", {"active": False, "reason": "try to deactivate"}
    )
    assert resp.status_code in (200, 422)
    active = fetch_all(
        app_engine, seeded.id, "SELECT active FROM users WHERE id = :i", {"i": seeded.quality.id}
    )[0]["active"]
    assert active is True


# =================================================================================================
# POST /users/{id}/deactivate
# =================================================================================================
def test_deactivate_user_requires_a_reason(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.quality
    resp = admin_client(api, seeded).post(f"/users/{seeded.quality.id}/deactivate", {})
    body = problem(resp)
    assert resp.status_code == 422
    assert "reason" in {e["field"] for e in body["errors"]}
    assert fetch_all(
        app_engine, seeded.id, "SELECT active FROM users WHERE id = :i", {"i": seeded.quality.id}
    )[0]["active"]


def test_deactivate_user_sets_active_false_and_returns_the_read_model(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.quality
    resp = admin_client(api, seeded).post(
        f"/users/{seeded.quality.id}/deactivate", {"reason": "Left the company"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["active"] is False
    assert not fetch_all(
        app_engine, seeded.id, "SELECT active FROM users WHERE id = :i", {"i": seeded.quality.id}
    )[0]["active"]


def test_deactivate_unknown_user_is_404(api: ApiFactory, seeded: SeededTenant) -> None:
    resp = admin_client(api, seeded).post(f"/users/{uuid4()}/deactivate", {"reason": "x"})
    assert resp.status_code == 404


# =================================================================================================
# POST /plants, /plants/{id}/update
# =================================================================================================
def test_admin_creates_a_plant_with_default_timezone(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    body = new_plant_body(address="MIDC, Chakan, Pune")
    resp = admin_client(api, seeded).post("/plants", body)
    assert resp.status_code in OK, resp.text
    data = resp.json()
    assert UUID7.match(data["id"])
    assert (data["name"], data["code"], data["address"]) == (
        body["name"],
        body["code"],
        "MIDC, Chakan, Pune",
    )
    assert data["timezone"] == "Asia/Kolkata"
    assert fetch_all(
        app_engine, seeded.id, "SELECT 1 FROM plants WHERE id = :i", {"i": UUID(data["id"])}
    )


def test_create_plant_accepts_an_iana_timezone_and_rejects_unknown_ones(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    admin = admin_client(api, seeded)
    ok = admin.post("/plants", new_plant_body(timezone="America/New_York"))
    assert ok.status_code in OK and ok.json()["timezone"] == "America/New_York"
    for bad in ("Mars/Olympus_Mons", "IST", "", "UTC+5:30"):
        resp = admin.post("/plants", new_plant_body(timezone=bad))
        body = problem(resp)
        assert resp.status_code == 422, bad
        assert "timezone" in {e["field"] for e in body["errors"]}


@pytest.mark.parametrize("code", ["pune1", "AB-1", "ABCDEFGHIJK", "", "P 1", "P_1"])
def test_create_plant_rejects_invalid_codes(
    api: ApiFactory, seeded: SeededTenant, code: str
) -> None:
    resp = admin_client(api, seeded).post("/plants", new_plant_body(code=code))
    body = problem(resp)
    assert resp.status_code == 422
    assert "code" in {e["field"] for e in body["errors"]}


def test_create_plant_rejects_duplicate_code_within_the_tenant_but_allows_it_in_another(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = seeded_pair
    admin_a, admin_b = admin_client(api, a), admin_client(api, b)
    assert admin_a.post("/plants", new_plant_body(code="DUPE1")).status_code in OK
    again = admin_a.post("/plants", new_plant_body(code="DUPE1"))
    assert again.status_code in (409, 422), again.text
    problem(again)
    assert admin_b.post("/plants", new_plant_body(code="DUPE1")).status_code in OK


def test_update_plant_changes_name_address_and_timezone(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    plant = seeded.plants[0]
    resp = admin_client(api, seeded).post(
        f"/plants/{plant}/update",
        {
            "name": "Pune Main",
            "address": "Hinjewadi",
            "timezone": "Asia/Kolkata",
            "reason": "Rebrand",
        },
    )
    assert resp.status_code == 200, resp.text
    row = fetch_all(
        app_engine, seeded.id, "SELECT name, address FROM plants WHERE id = :i", {"i": plant}
    )[0]
    assert (row["name"], row["address"]) == ("Pune Main", "Hinjewadi")


def test_update_plant_rejects_an_unknown_timezone(api: ApiFactory, seeded: SeededTenant) -> None:
    resp = admin_client(api, seeded).post(
        f"/plants/{seeded.plants[0]}/update", {"timezone": "Nowhere/City"}
    )
    assert resp.status_code == 422


def test_update_unknown_plant_is_404(api: ApiFactory, seeded: SeededTenant) -> None:
    assert (
        admin_client(api, seeded).post(f"/plants/{uuid4()}/update", {"name": "x"}).status_code
        == 404
    )


# =================================================================================================
# Tenant settings
# =================================================================================================
def test_get_settings_returns_documented_defaults_for_a_new_tenant(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    resp = admin_client(api, seeded).get("/tenant/settings")
    assert resp.status_code == 200, resp.text
    settings = resp.json()["settings"]
    assert settings["min_sample"] == {
        "receipts": 5,
        "units": 1000,
        "scars_due": 1,
    }  # blueprint 12.1
    assert settings["score_weights"] == {
        "quality": 50,
        "response": 20,
        "repeat": 15,
        "documents": 15,
    }  # 14.1
    sla = settings[
        "sla_hours"
    ]  # blueprint 9 C6 severity policy: containment / final 8D, calendar hours
    assert sla["critical"] == {"containment": 24, "final": 7 * 24}
    assert sla["major"] == {"containment": 48, "final": 10 * 24}
    assert sla["minor"]["final"] == 15 * 24
    assert sla["minor"]["containment"] is None
    assert settings["default_ppm_target"] > 0


def test_update_settings_requires_a_reason(api: ApiFactory, seeded: SeededTenant) -> None:
    admin = admin_client(api, seeded)
    current = admin.get("/tenant/settings").json()["settings"]
    resp = admin.post("/tenant/settings/update", {"settings": current})
    body = problem(resp)
    assert resp.status_code == 422
    assert "reason" in {e["field"] for e in body["errors"]}


def test_update_settings_persists_and_is_returned_by_get(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    admin = admin_client(api, seeded)
    current = admin.get("/tenant/settings").json()["settings"]
    current["default_ppm_target"] = 750
    current["min_sample"]["receipts"] = 8
    resp = admin.post(
        "/tenant/settings/update", {"settings": current, "reason": "Pilot agreement 2026-10"}
    )
    assert resp.status_code == 200, resp.text
    again = admin.get("/tenant/settings").json()["settings"]
    assert again["default_ppm_target"] == 750
    assert again["min_sample"]["receipts"] == 8
    assert again["score_weights"] == current["score_weights"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.update(default_ppm_target=0),
        lambda s: s.update(default_ppm_target=-5),
        lambda s: s.update(default_ppm_target=500.5),
        lambda s: s.update(default_ppm_target="500"),
        lambda s: s["min_sample"].update(receipts="five"),
        lambda s: s["min_sample"].update(units=-1),
    ],
    ids=[
        "ppm-zero",
        "ppm-negative",
        "ppm-float",
        "ppm-string",
        "receipts-string",
        "units-negative",
    ],
)
def test_update_settings_rejects_invalid_values_strictly(
    api: ApiFactory, seeded: SeededTenant, mutate: Any
) -> None:
    admin = admin_client(api, seeded)
    current = admin.get("/tenant/settings").json()["settings"]
    mutate(current)
    resp = admin.post("/tenant/settings/update", {"settings": current, "reason": "test"})
    assert resp.status_code == 422, resp.text
    assert problem(resp)["code"] == "validation_error"
    assert admin.get("/tenant/settings").json()["settings"]["default_ppm_target"] > 0


# =================================================================================================
# Reads: /me, /users, /plants
# =================================================================================================
def test_me_returns_the_session_user_role_can_approve_and_plants(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    assert seeded.approver
    resp = api.login_as(seeded.approver).get("/me")
    assert resp.status_code == 200, resp.text
    me = resp.json()
    assert me["email"] == seeded.approver.email
    assert (me["role"], me["can_approve"]) == ("quality", True)
    assert "password_hash" not in me
    plants = {p["id"] if isinstance(p, dict) else p for p in me["plants"]}
    assert plants == {str(p) for p in seeded.plants}


def test_me_requires_authentication(api: ApiFactory) -> None:
    resp = api.anonymous().get("/me")
    assert resp.status_code == 401
    assert problem(resp)["code"] == "unauthenticated"


def test_users_list_is_tenant_scoped_keyset_paginated_and_never_exposes_password_hash(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant], app_engine: Engine
) -> None:
    a, b = seeded_pair
    for _ in range(5):
        create_user(app_engine, a.id)
    admin = admin_client(api, a)
    collected: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(10):
        resp = admin.get("/users", params={"limit": 3, **({"cursor": cursor} if cursor else {})})
        assert resp.status_code == 200, resp.text
        page = resp.json()
        assert 0 < len(page["items"]) <= 3
        collected.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert cursor is None, "pagination never terminated"
    ids = [u["id"] for u in collected]
    assert len(ids) == len(set(ids)) == 4 + 5  # 4 seeded users + 5 added, each exactly once
    assert not ({str(b.admin.id)} & set(ids) if b.admin else set())
    assert all("password_hash" not in u and "password" not in u for u in collected)


def test_list_default_limit_is_fifty_and_limit_is_bounded(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    admin = admin_client(api, seeded)
    assert admin.get("/users").json()["next_cursor"] is None  # 4 users < 50
    for bad in (0, 201, -1):
        resp = admin.get("/users", params={"limit": bad})
        assert resp.status_code in (400, 422), bad
        problem(resp)
    assert admin.get("/users", params={"limit": 200}).status_code == 200


def test_tampered_or_garbage_cursor_is_400_bad_request(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    admin = admin_client(api, seeded)
    for cursor in ("garbage", "e30", "eyJrIjogWyJ4Il19.deadbeef"):
        resp = admin.get("/users", params={"cursor": cursor})
        assert resp.status_code == 400, cursor
        assert problem(resp)["code"] == "bad_request"


def test_plants_list_returns_only_the_tenants_plants_to_every_role(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = seeded_pair
    for user in (a.admin, a.quality, a.viewer):
        assert user
        resp = api.login_as(user).get("/plants")
        assert resp.status_code == 200, (user.role, resp.text)
        ids = {p["id"] for p in resp.json()["items"]}
        assert ids == {str(p) for p in a.plants}
        assert not ids & {str(p) for p in b.plants}


def test_new_tenant_without_plants_gets_an_empty_list(api: ApiFactory, app_engine: Engine) -> None:
    tenant = create_tenant(app_engine)
    admin = create_user(app_engine, tenant, role="admin")
    create_plant(app_engine, create_tenant(app_engine))  # someone else's plant exists
    page = api.login_as(admin).get("/plants").json()
    assert page == {"items": [], "next_cursor": None}
