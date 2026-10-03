"""INV-PLT-04: every command authorises, then writes activity_log and outbox_events in the SAME transaction.

Same-transaction is proven two ways: (1) xmin of the business row, the audit row, the outbox row and the
idempotency row are identical; (2) a failure at any later step leaves none of them behind."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, text

from tests.factories.api import ApiClient, ApiFactory, new_key, problem
from tests.factories.db import SeededTenant, fetch_all, tenant_conn
from tests.integration.commands.test_platform_commands_api import (
    admin_client,
    new_plant_body,
    new_user_body,
)

pytestmark = pytest.mark.integration

CLIENT_IP = "203.0.113.10"


def log_rows(engine: Engine, tenant: UUID, object_id: UUID | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM activity_log WHERE tenant_id = :t"
    params: dict[str, Any] = {"t": tenant}
    if object_id:
        sql += " AND object_id = :o"
        params["o"] = object_id
    return fetch_all(engine, tenant, sql + " ORDER BY created_at, id", params)


def outbox_rows(
    engine: Engine, tenant: UUID, aggregate_id: UUID | None = None
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM outbox_events WHERE tenant_id = :t"
    params: dict[str, Any] = {"t": tenant}
    if aggregate_id:
        sql += " AND aggregate_id = :a"
        params["a"] = aggregate_id
    return fetch_all(engine, tenant, sql + " ORDER BY created_at, id", params)


def xmin(engine: Engine, tenant: UUID, table: str, where: str, params: dict[str, Any]) -> str:
    rows = fetch_all(engine, tenant, f"SELECT xmin::text AS x FROM {table} WHERE {where}", params)
    assert len(rows) == 1, f"{table} where {where}: {len(rows)} rows"
    return str(rows[0]["x"])


# =================================================================================================
# Platform command catalogue: object_type / action prefix / event
# =================================================================================================
def _create_user(c: ApiClient, t: SeededTenant) -> tuple[Any, ...]:
    r = c.post("/users", new_user_body())
    return r, "user", UUID(r.json()["id"]) if r.status_code < 300 else None, "USER_CREATED", "users"


def _update_user(c: ApiClient, t: SeededTenant) -> tuple[Any, ...]:
    assert t.quality
    r = c.post(f"/users/{t.quality.id}/update", {"role": "admin", "reason": "Promoted"})
    return r, "user", t.quality.id, "USER_UPDATED", "users"


def _deactivate_user(c: ApiClient, t: SeededTenant) -> tuple[Any, ...]:
    assert t.viewer
    r = c.post(f"/users/{t.viewer.id}/deactivate", {"reason": "Left"})
    return r, "user", t.viewer.id, "USER_DEACTIVATED", "users"


def _create_plant(c: ApiClient, t: SeededTenant) -> tuple[Any, ...]:
    r = c.post("/plants", new_plant_body())
    return (
        r,
        "plant",
        UUID(r.json()["id"]) if r.status_code < 300 else None,
        "PLANT_CREATED",
        "plants",
    )


def _update_plant(c: ApiClient, t: SeededTenant) -> tuple[Any, ...]:
    r = c.post(f"/plants/{t.plants[0]}/update", {"name": "Renamed", "reason": "Rebrand"})
    return r, "plant", t.plants[0], "PLANT_UPDATED", "plants"


def _update_settings(c: ApiClient, t: SeededTenant) -> tuple[Any, ...]:
    current = c.get("/tenant/settings").json()["settings"]
    current["default_ppm_target"] = 640
    r = c.post("/tenant/settings/update", {"settings": current, "reason": "Contract change"})
    return r, "tenant", t.id, "TENANT_SETTINGS_UPDATED", "tenants"


COMMANDS = [
    pytest.param(_create_user, id="user-create"),
    pytest.param(_update_user, id="user-update"),
    pytest.param(_deactivate_user, id="user-deactivate"),
    pytest.param(_create_plant, id="plant-create"),
    pytest.param(_update_plant, id="plant-update"),
    pytest.param(_update_settings, id="settings-update"),
]


@pytest.mark.parametrize("command", COMMANDS)
def test_command_writes_activity_log_and_outbox_in_same_transaction(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine, clean_outbox: None, command: Any
) -> None:
    admin = admin_client(api, seeded)
    response, object_type, object_id, event, table = command(admin, seeded)
    assert response.status_code in (200, 201), response.text
    object_id = object_id or UUID(response.json()["id"])
    audit = [
        r for r in log_rows(app_engine, seeded.id, object_id) if r["object_type"] == object_type
    ]
    events = outbox_rows(app_engine, seeded.id, object_id)
    assert len(audit) == 1, f"expected one activity_log row for {object_type}, got {len(audit)}"
    assert len(events) == 1, f"expected one outbox event, got {len(events)}"
    assert events[0]["event_type"] == event
    assert events[0]["processed_at"] is None and events[0]["attempts"] == 0
    business = xmin(app_engine, seeded.id, table, "id = :i", {"i": object_id})
    assert xmin(app_engine, seeded.id, "activity_log", "id = :i", {"i": audit[0]["id"]}) == business
    assert (
        xmin(app_engine, seeded.id, "outbox_events", "id = :i", {"i": events[0]["id"]}) == business
    )


def test_idempotency_row_is_written_in_the_same_transaction_as_the_business_change(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    admin = admin_client(api, seeded)
    key = new_key()
    resp = admin.post("/plants", new_plant_body(), key=key)
    assert resp.status_code in (200, 201)
    plant = UUID(resp.json()["id"])
    assert seeded.admin
    business = xmin(app_engine, seeded.id, "plants", "id = :i", {"i": plant})
    assert xmin(app_engine, seeded.id, "idempotency_keys", "key = :k", {"k": key}) == business


@contextmanager
def failing_insert(
    owner_engine: Engine, table: str, tenant: UUID, extra: str = ""
) -> Iterator[None]:
    """Make every write for this tenant into `table` fail, using a NOT VALID CHECK (enforced on new rows).

    `extra` narrows the failure (e.g. only when response_status is set)."""
    name = f"zz_block_{table}"
    predicate = f"tenant_id <> '{tenant}'::uuid" + (f" OR {extra}" if extra else "")
    with owner_engine.connect() as conn:
        conn.execute(
            text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({predicate}) NOT VALID")
        )
    try:
        yield
    finally:
        with owner_engine.connect() as conn:
            conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}"))


FAILURES = [
    pytest.param("outbox_events", "", id="outbox-write-fails"),
    pytest.param("activity_log", "", id="activity-log-write-fails"),
    pytest.param(
        "idempotency_keys", "response_status IS NULL", id="idempotent-response-store-fails"
    ),
]


@pytest.mark.parametrize(("table", "extra"), FAILURES)
def test_command_failure_rolls_back_activity_log_and_outbox(
    api: ApiFactory,
    seeded: SeededTenant,
    app_engine: Engine,
    owner_engine: Engine,
    table: str,
    extra: str,
) -> None:
    """A step after the mutation fails: the plant row, the audit row, the outbox row and the idempotency
    reservation must all be gone; a retry with the same key then succeeds as a fresh request."""
    admin = admin_client(api, seeded)
    body = new_plant_body()
    key = new_key()
    with failing_insert(owner_engine, table, seeded.id, extra):
        resp = admin.post("/plants", body, key=key)
    assert not 200 <= resp.status_code < 300, resp.text
    problem(resp)
    assert (
        fetch_all(
            app_engine, seeded.id, "SELECT 1 FROM plants WHERE code = :c", {"c": body["code"]}
        )
        == []
    )
    assert [r for r in log_rows(app_engine, seeded.id) if r["object_type"] == "plant"] == []
    assert outbox_rows(app_engine, seeded.id) == []
    assert (
        fetch_all(
            app_engine, seeded.id, "SELECT 1 FROM idempotency_keys WHERE key = :k", {"k": key}
        )
        == []
    )
    retry = admin.post("/plants", body, key=key)
    assert retry.status_code in (200, 201), retry.text
    assert "idempotency-replayed" not in retry.headers  # a failed attempt is never replayed


def test_a_validation_failure_writes_no_audit_no_outbox_and_no_idempotency_row(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    admin = admin_client(api, seeded)
    before = len(log_rows(app_engine, seeded.id))
    key = new_key()
    resp = admin.post("/plants", new_plant_body(code="bad code"), key=key)
    assert resp.status_code == 422
    assert len(log_rows(app_engine, seeded.id)) == before
    assert outbox_rows(app_engine, seeded.id) == []
    assert (
        fetch_all(
            app_engine, seeded.id, "SELECT 1 FROM idempotency_keys WHERE key = :k", {"k": key}
        )
        == []
    )


# =================================================================================================
# activity_log content
# =================================================================================================
def test_activity_log_records_actor_session_and_ip(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.admin
    admin = api.login_as(seeded.admin, ip=CLIENT_IP)
    resp = admin.post("/plants", new_plant_body())
    plant = UUID(resp.json()["id"])
    first = log_rows(app_engine, seeded.id, plant)[0]
    assert first["actor_type"] == "user"
    assert first["actor_id"] == seeded.admin.id
    assert first["session_id"] is not None
    assert str(first["ip"]) == CLIENT_IP
    assert first["tenant_id"] == seeded.id
    second_resp = admin.post(f"/plants/{plant}/update", {"name": "Again", "reason": "r"})
    assert second_resp.status_code == 200
    rows = log_rows(app_engine, seeded.id, plant)
    assert len(rows) == 2
    assert rows[1]["session_id"] == first["session_id"]  # same login, same session
    other_login = api.login_as(seeded.admin, ip=CLIENT_IP)
    other_login.post(f"/plants/{plant}/update", {"name": "Third", "reason": "r"})
    assert log_rows(app_engine, seeded.id, plant)[2]["session_id"] != first["session_id"]


def test_activity_log_create_has_no_before_and_an_after_snapshot(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    body = new_plant_body(address="Plot 7")
    resp = admin_client(api, seeded).post("/plants", body)
    row = log_rows(app_engine, seeded.id, UUID(resp.json()["id"]))[0]
    assert row["object_type"] == "plant" and row["action"].startswith("plant.")
    assert row["before"] is None
    assert row["after"]["code"] == body["code"] and row["after"]["name"] == body["name"]


def test_activity_log_update_captures_before_after_and_reason(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    plant = seeded.plants[0]
    old = fetch_all(app_engine, seeded.id, "SELECT name FROM plants WHERE id = :i", {"i": plant})[
        0
    ]["name"]
    resp = admin_client(api, seeded).post(
        f"/plants/{plant}/update", {"name": "After Name", "reason": "Renamed after merger"}
    )
    assert resp.status_code == 200
    row = log_rows(app_engine, seeded.id, plant)[-1]
    assert row["before"]["name"] == old
    assert row["after"]["name"] == "After Name"
    assert row["reason"] == "Renamed after merger"


def test_role_change_audit_row_shows_before_after_and_reason(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.quality
    admin_client(api, seeded).post(
        f"/users/{seeded.quality.id}/update", {"role": "admin", "reason": "Cover for leave"}
    )
    row = log_rows(app_engine, seeded.id, seeded.quality.id)[-1]
    assert (row["before"]["role"], row["after"]["role"]) == ("quality", "admin")
    assert row["reason"] == "Cover for leave"
    assert row["actor_id"] == seeded.admin.id  # type: ignore[union-attr]


def test_activity_log_snapshots_never_contain_password_hashes(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.quality
    admin = admin_client(api, seeded)
    admin.post(f"/users/{seeded.quality.id}/update", {"name": "Renamed", "reason": "r"})
    admin.post(f"/users/{seeded.quality.id}/deactivate", {"reason": "r"})
    dumps = [
        json.dumps(r["before"]) + json.dumps(r["after"]) for r in log_rows(app_engine, seeded.id)
    ]
    assert dumps and not any("argon2" in d or "password" in d for d in dumps)


def test_created_by_and_updated_by_record_the_acting_user(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.admin
    resp = admin_client(api, seeded).post("/plants", new_plant_body())
    plant = UUID(resp.json()["id"])
    row = fetch_all(
        app_engine,
        seeded.id,
        "SELECT created_by, updated_by FROM plants WHERE id = :i",
        {"i": plant},
    )[0]
    assert (row["created_by"], row["updated_by"]) == (seeded.admin.id, seeded.admin.id)


# =================================================================================================
# outbox content
# =================================================================================================
def test_outbox_event_has_a_uuid7_event_id_the_aggregate_and_ids_only_payload(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine, clean_outbox: None
) -> None:
    body = new_user_body(name="Sensitive Name", mobile="+919800011122")
    resp = admin_client(api, seeded).post("/users", body)
    user = UUID(resp.json()["id"])
    event = outbox_rows(app_engine, seeded.id, user)[0]
    assert event["event_type"] == "USER_CREATED"
    assert event["aggregate_type"] == "user" and event["aggregate_id"] == user
    assert event["event_id"].version == 7
    dumped = json.dumps(event["payload"]).lower()
    for pii in (body["email"].lower(), "sensitive name", "+919800011122", "argon2"):
        assert pii not in dumped
    assert isinstance(event["payload"], dict)


def test_every_command_event_has_a_distinct_event_id(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine, clean_outbox: None
) -> None:
    admin = admin_client(api, seeded)
    for _ in range(4):
        admin.post("/plants", new_plant_body())
    ids = [e["event_id"] for e in outbox_rows(app_engine, seeded.id)]
    assert len(ids) == 4 and len(set(ids)) == 4


def test_event_types_written_by_commands_are_all_registered() -> None:
    from tests.factories.contract import load

    registry = load("app.core.outbox.registry", "get")
    for event in (
        "USER_CREATED",
        "USER_UPDATED",
        "USER_DEACTIVATED",
        "PLANT_CREATED",
        "PLANT_UPDATED",
        "TENANT_SETTINGS_UPDATED",
    ):
        assert registry(event) is not None


def test_login_is_audited_as_a_session_start(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.admin
    client = api.anonymous(CLIENT_IP)
    assert client.login(seeded.admin).status_code == 200
    rows = [
        r for r in log_rows(app_engine, seeded.id, seeded.admin.id) if r["action"] == "auth.login"
    ]
    assert len(rows) == 1
    assert rows[0]["actor_type"] == "user" and rows[0]["actor_id"] == seeded.admin.id
    assert rows[0]["session_id"] is not None and str(rows[0]["ip"]) == CLIENT_IP


def test_audit_rows_of_one_tenant_are_invisible_to_another(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant], app_engine: Engine
) -> None:
    a, b = seeded_pair
    admin_client(api, a).post("/plants", new_plant_body())
    assert [r for r in log_rows(app_engine, b.id) if r["object_type"] == "plant"] == []
    with tenant_conn(app_engine, b.id) as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM activity_log WHERE tenant_id = :a"), {"a": a.id}
            ).scalar_one()
            == 0
        )
