"""Constraints, triggers and grants of the P01 tables (DATA_MODEL 1.1-1.5, 9, 0.6, 0.8)."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg.errors
import pytest
from sqlalchemy import Connection, Engine, text

from tests.factories.db import (
    create_plant,
    create_tenant,
    create_user,
    insert_outbox_event,
    tenant_conn,
)
from tests.factories.dberr import expect_db_error
from tests.factories.rows import INSERTERS

pytestmark = pytest.mark.integration


def _plant(conn: Connection, tenant: UUID, code: str, name: str = "P") -> None:
    conn.execute(
        text("INSERT INTO plants (tenant_id, name, code) VALUES (:t, :n, :c)"),
        {"t": tenant, "n": name, "c": code},
    )


def _user(conn: Connection, tenant: UUID, **cols: object) -> None:
    values = {"email": f"u.{uuid4().hex}@example.test", "name": "U", "role": "quality", **cols}
    names = ", ".join(values)
    binds = ", ".join(f":{k}" for k in values)
    conn.execute(
        text(f"INSERT INTO users (tenant_id, {names}) VALUES (:t, {binds})"),
        {"t": tenant, **values},
    )


# --- tenants ---------------------------------------------------------------------------------------
def test_tenant_check_requires_tenant_id_equal_to_id(app_engine: Engine) -> None:
    tid = uuid4()
    with expect_db_error(psycopg.errors.CheckViolation), tenant_conn(app_engine, tid) as conn:
        conn.execute(
            text("INSERT INTO tenants (id, tenant_id, name, plan) VALUES (:i, :t, 'x', 'p')"),
            {"i": uuid4(), "t": tid},
        )


def test_tenant_settings_must_be_a_json_object(app_engine: Engine) -> None:
    tid = uuid4()
    with expect_db_error(psycopg.errors.CheckViolation), tenant_conn(app_engine, tid) as conn:
        conn.execute(
            text(
                "INSERT INTO tenants (id, tenant_id, name, plan, settings) "
                "VALUES (:t, :t, 'x', 'p', '[]'::jsonb)"
            ),
            {"t": tid},
        )


def test_tenant_settings_default_to_an_empty_object(app_engine: Engine) -> None:
    tid = create_tenant(app_engine)
    with tenant_conn(app_engine, tid) as conn:
        assert conn.execute(text("SELECT settings FROM tenants")).scalar_one() == {}


# --- plants ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("code", ["A", "A1", "PLANT01", "ABCDEFGHIJ", "0123456789"])
def test_plant_code_accepts_one_to_ten_uppercase_alphanumerics(
    app_engine: Engine, code: str
) -> None:
    tid = create_tenant(app_engine)
    with tenant_conn(app_engine, tid) as conn:
        _plant(conn, tid, code)


@pytest.mark.parametrize("code", ["", "abc", "AB-1", "A B", "ABCDEFGHIJK", "PLANT_1", "ÄB"])
def test_plant_code_rejects_lowercase_separators_and_over_ten_characters(
    app_engine: Engine, code: str
) -> None:
    tid = create_tenant(app_engine)
    with expect_db_error(psycopg.errors.CheckViolation), tenant_conn(app_engine, tid) as conn:
        _plant(conn, tid, code)


def test_plant_code_is_unique_per_tenant_but_reusable_across_tenants(app_engine: Engine) -> None:
    a, b = create_tenant(app_engine), create_tenant(app_engine)
    create_plant(app_engine, a, code="PUNE1")
    create_plant(app_engine, b, code="PUNE1")
    with expect_db_error(psycopg.errors.UniqueViolation), tenant_conn(app_engine, a) as conn:
        _plant(conn, a, "PUNE1")


def test_plant_timezone_defaults_to_asia_kolkata_and_address_is_optional(
    app_engine: Engine,
) -> None:
    tid = create_tenant(app_engine)
    with tenant_conn(app_engine, tid) as conn:
        _plant(conn, tid, "DEF1")
        row = conn.execute(text("SELECT timezone, address FROM plants")).one()
    assert tuple(row) == ("Asia/Kolkata", None)


def test_row_id_defaults_to_a_uuid_v7_when_the_application_omits_it(app_engine: Engine) -> None:
    tid = create_tenant(app_engine)
    with tenant_conn(app_engine, tid) as conn:
        new_id = conn.execute(
            text("INSERT INTO plants (tenant_id, name, code) VALUES (:t, 'x', 'ID7') RETURNING id"),
            {"t": tid},
        ).scalar_one()
    assert new_id.version == 7


# --- users -----------------------------------------------------------------------------------------
def test_user_email_is_globally_unique_case_insensitively_across_tenants(
    app_engine: Engine,
) -> None:
    """A-03: login resolves the tenant from the email, so it must be unique across tenants."""
    a, b = create_tenant(app_engine), create_tenant(app_engine)
    token = uuid4().hex[:10]
    create_user(app_engine, a, email=f"Shared.Person.{token}@Example.test")
    with expect_db_error(psycopg.errors.UniqueViolation), tenant_conn(app_engine, b) as conn:
        _user(conn, b, email=f"shared.person.{token}@example.TEST")


@pytest.mark.parametrize("role", ["owner", "Admin", "", "supplier"])
def test_user_role_must_be_admin_quality_or_viewer(app_engine: Engine, role: str) -> None:
    tid = create_tenant(app_engine)
    with expect_db_error(psycopg.errors.CheckViolation), tenant_conn(app_engine, tid) as conn:
        _user(conn, tid, role=role)


@pytest.mark.parametrize("mobile", ["+919876543210", "+14155552671", "+4915112345678"])
def test_user_mobile_accepts_e164(app_engine: Engine, mobile: str) -> None:
    tid = create_tenant(app_engine)
    with tenant_conn(app_engine, tid) as conn:
        _user(conn, tid, mobile=mobile)


@pytest.mark.parametrize(
    "mobile", ["9876543210", "+0123456789", "+91", "+91 98765 43210", "+9198765432101234"]
)
def test_user_mobile_rejects_non_e164(app_engine: Engine, mobile: str) -> None:
    tid = create_tenant(app_engine)
    with expect_db_error(psycopg.errors.CheckViolation), tenant_conn(app_engine, tid) as conn:
        _user(conn, tid, mobile=mobile)


def test_user_defaults_are_can_approve_false_active_true_no_plants_no_password(
    app_engine: Engine,
) -> None:
    tid = create_tenant(app_engine)
    with tenant_conn(app_engine, tid) as conn:
        _user(conn, tid)
        row = conn.execute(
            text("SELECT can_approve, active, plant_ids, password_hash, mobile FROM users")
        ).one()
    assert tuple(row) == (False, True, [], None, None)


def test_user_plant_ids_must_exist_in_tenant_db(app_engine: Engine) -> None:
    """INV-PLT-09: trg_users_plant_ids_valid on insert and update; foreign and unknown plants rejected."""
    a, b = create_tenant(app_engine), create_tenant(app_engine)
    own = create_plant(app_engine, a)
    foreign = create_plant(app_engine, b)
    with tenant_conn(app_engine, a) as conn:
        _user(conn, a, plant_ids=[own])  # valid
    with expect_db_error(psycopg.Error, "plant"), tenant_conn(app_engine, a) as conn:
        _user(conn, a, plant_ids=[foreign])
    with expect_db_error(psycopg.Error, "plant"), tenant_conn(app_engine, a) as conn:
        _user(conn, a, plant_ids=[uuid4()])
    with expect_db_error(psycopg.Error, "plant"), tenant_conn(app_engine, a) as conn:
        _user(conn, a, plant_ids=[own, foreign])  # one bad element poisons the array
    seeded = create_user(app_engine, a, plant_ids=(own,))
    with expect_db_error(psycopg.Error, "plant"), tenant_conn(app_engine, a) as conn:
        conn.execute(
            text("UPDATE users SET plant_ids = :p WHERE id = :i"), {"p": [foreign], "i": seeded.id}
        )


def test_user_plant_ids_empty_array_is_always_valid(app_engine: Engine) -> None:
    tid = create_tenant(app_engine)
    with tenant_conn(app_engine, tid) as conn:
        _user(conn, tid, plant_ids=[])


# --- updated_at / created_at -----------------------------------------------------------------------
def test_updated_at_trigger_moves_updated_at_but_not_created_at(app_engine: Engine) -> None:
    tid = create_tenant(app_engine)
    pid = create_plant(app_engine, tid)
    with tenant_conn(app_engine, tid) as conn:
        before = conn.execute(
            text("SELECT created_at, updated_at FROM plants WHERE id = :i"), {"i": pid}
        ).one()
    with tenant_conn(app_engine, tid) as conn:
        conn.execute(text("UPDATE plants SET name = 'renamed' WHERE id = :i"), {"i": pid})
    with tenant_conn(app_engine, tid) as conn:
        after = conn.execute(
            text("SELECT created_at, updated_at FROM plants WHERE id = :i"), {"i": pid}
        ).one()
    assert after.created_at == before.created_at
    assert after.updated_at > before.updated_at


def test_updated_at_cannot_be_forged_by_the_client(app_engine: Engine) -> None:
    tid = create_tenant(app_engine)
    pid = create_plant(app_engine, tid)
    forged = datetime(2001, 1, 1, tzinfo=UTC)
    with tenant_conn(app_engine, tid) as conn:
        conn.execute(
            text("UPDATE plants SET name = 'z', updated_at = :f WHERE id = :i"),
            {"f": forged, "i": pid},
        )
        stored = conn.execute(
            text("SELECT updated_at FROM plants WHERE id = :i"), {"i": pid}
        ).scalar_one()
    assert stored > forged


# --- activity_log ----------------------------------------------------------------------------------
def _log(conn: Connection, tenant: UUID, **cols: object) -> None:
    values: dict[str, object] = {
        "object_type": "plant",
        "object_id": uuid4(),
        "action": "plant.create",
        "actor_type": "user",
        "actor_id": uuid4(),
        **cols,
    }
    names = ", ".join(values)
    binds = ", ".join(f":{k}" for k in values)
    conn.execute(
        text(f"INSERT INTO activity_log (tenant_id, {names}) VALUES (:t, {binds})"),
        {"t": tenant, **values},
    )


def test_activity_log_accepts_the_four_actor_types_with_their_required_ids(
    app_engine: Engine,
) -> None:
    tid = create_tenant(app_engine)
    with tenant_conn(app_engine, tid) as conn:
        _log(conn, tid, actor_type="user", actor_id=uuid4())
        _log(conn, tid, actor_type="system", actor_id=None)
        _log(conn, tid, actor_type="ai", actor_id=None)
        _log(conn, tid, actor_type="supplier_session", actor_id=uuid4(), session_id=uuid4())


@pytest.mark.parametrize(
    "bad",
    [
        {"actor_type": "robot"},
        {"actor_type": "user", "actor_id": None},
        {"actor_type": "supplier_session", "actor_id": None, "session_id": None},
        {"actor_type": "supplier_session", "session_id": None},
    ],
    ids=["unknown-actor", "user-without-id", "supplier-without-ids", "supplier-without-session"],
)
def test_activity_log_actor_checks_reject_inconsistent_rows(
    app_engine: Engine, bad: dict[str, object]
) -> None:
    tid = create_tenant(app_engine)
    with expect_db_error(psycopg.errors.CheckViolation), tenant_conn(app_engine, tid) as conn:
        _log(conn, tid, **bad)


def test_activity_log_before_and_after_are_json_objects_or_null(app_engine: Engine) -> None:
    tid = create_tenant(app_engine)
    with tenant_conn(app_engine, tid) as conn:
        conn.execute(
            text(
                "INSERT INTO activity_log (tenant_id, object_type, object_id, action, actor_type, "
                "before, after, ip, reason) VALUES (:t, 'plant', :o, 'plant.update', 'system', "
                "CAST(:b AS jsonb), NULL, '203.0.113.7', 'because')"
            ),
            {"t": tid, "o": uuid4(), "b": json.dumps({"name": "old"})},
        )
    with expect_db_error(psycopg.errors.CheckViolation), tenant_conn(app_engine, tid) as conn:
        conn.execute(
            text(
                "INSERT INTO activity_log (tenant_id, object_type, object_id, action, actor_type, after) "
                "VALUES (:t, 'plant', :o, 'x', 'system', '[1]'::jsonb)"
            ),
            {"t": tid, "o": uuid4()},
        )


def test_activity_log_update_rejected_db(app_engine: Engine) -> None:
    """INV-PLT-05: the app role has no UPDATE privilege on activity_log."""
    tid = create_tenant(app_engine)
    with tenant_conn(app_engine, tid) as conn:
        INSERTERS["activity_log"](conn, tid)
    with (
        expect_db_error(psycopg.errors.InsufficientPrivilege, "permission denied"),
        tenant_conn(app_engine, tid) as conn,
    ):
        conn.execute(text("UPDATE activity_log SET action = 'tampered'"))


def test_activity_log_delete_rejected_db(app_engine: Engine) -> None:
    tid = create_tenant(app_engine)
    with tenant_conn(app_engine, tid) as conn:
        INSERTERS["activity_log"](conn, tid)
    with (
        expect_db_error(psycopg.errors.InsufficientPrivilege, "permission denied"),
        tenant_conn(app_engine, tid) as conn,
    ):
        conn.execute(text("DELETE FROM activity_log"))


@pytest.mark.parametrize("verb", ["UPDATE", "DELETE"])
def test_activity_log_append_only_trigger_blocks_even_when_privileges_are_granted(
    app_engine: Engine, owner_engine: Engine, verb: str
) -> None:
    """Defence in depth (DATA_MODEL 0.6): trg_append_only raises even if a grant is mistakenly added."""
    tid = create_tenant(app_engine)
    with tenant_conn(app_engine, tid) as conn:
        INSERTERS["activity_log"](conn, tid)
    with owner_engine.connect() as owner:
        owner.execute(text(f"GRANT {verb} ON activity_log TO qualloop_app"))
    try:
        statement = (
            "UPDATE activity_log SET action = 'tampered'"
            if verb == "UPDATE"
            else "DELETE FROM activity_log"
        )
        with (
            expect_db_error(psycopg.errors.IntegrityConstraintViolation, "append-only"),
            tenant_conn(app_engine, tid) as conn,
        ):
            conn.execute(text(statement))
    finally:
        with owner_engine.connect() as owner:
            owner.execute(text(f"REVOKE {verb} ON activity_log FROM qualloop_app"))


# --- outbox_events ---------------------------------------------------------------------------------
def test_outbox_event_id_is_unique_per_tenant(app_engine: Engine) -> None:
    tid = create_tenant(app_engine)
    event_id = uuid4()
    sql = text(
        "INSERT INTO outbox_events (tenant_id, event_id, aggregate_type, aggregate_id, event_type, payload) "
        "VALUES (:t, :e, 'plant', :a, 'PLANT_CREATED', '{}'::jsonb)"
    )
    with tenant_conn(app_engine, tid) as conn:
        conn.execute(sql, {"t": tid, "e": event_id, "a": uuid4()})
    with expect_db_error(psycopg.errors.UniqueViolation), tenant_conn(app_engine, tid) as conn:
        conn.execute(sql, {"t": tid, "e": event_id, "a": uuid4()})


def test_outbox_attempts_default_zero_and_never_negative(app_engine: Engine) -> None:
    tid = create_tenant(app_engine)
    row = insert_outbox_event(app_engine, tid)
    with tenant_conn(app_engine, tid) as conn:
        assert (
            conn.execute(
                text("SELECT attempts FROM outbox_events WHERE id = :i"), {"i": row}
            ).scalar_one()
            == 0
        )
    with expect_db_error(psycopg.errors.CheckViolation), tenant_conn(app_engine, tid) as conn:
        conn.execute(text("UPDATE outbox_events SET attempts = -1 WHERE id = :i"), {"i": row})


def test_outbox_payload_must_be_a_json_object(app_engine: Engine) -> None:
    tid = create_tenant(app_engine)
    with expect_db_error(psycopg.errors.CheckViolation), tenant_conn(app_engine, tid) as conn:
        conn.execute(
            text(
                "INSERT INTO outbox_events (tenant_id, event_id, aggregate_type, aggregate_id, event_type, "
                "payload) VALUES (:t, :e, 'plant', :a, 'PLANT_CREATED', '[]'::jsonb)"
            ),
            {"t": tid, "e": uuid4(), "a": uuid4()},
        )


def test_outbox_dispatch_columns_are_updatable_but_the_event_itself_is_immutable(
    app_engine: Engine,
) -> None:
    tid = create_tenant(app_engine)
    row = insert_outbox_event(app_engine, tid)
    with tenant_conn(app_engine, tid, actor_type="system") as conn:
        conn.execute(
            text(
                "UPDATE outbox_events SET processed_at = now(), attempts = 2, last_error = 'e' WHERE id = :i"
            ),
            {"i": row},
        )
    for column, value in [
        ("payload", "'{}'::jsonb"),
        ("event_type", "'X'"),
        ("event_id", "gen_random_uuid()"),
        ("aggregate_id", "gen_random_uuid()"),
        ("tenant_id", "tenant_id"),
        ("created_at", "now()"),
    ]:
        with (
            expect_db_error(psycopg.errors.InsufficientPrivilege, "permission denied"),
            tenant_conn(app_engine, tid, actor_type="system") as conn,
        ):
            conn.execute(
                text(f"UPDATE outbox_events SET {column} = {value} WHERE id = :i"), {"i": row}
            )


# --- idempotency_keys / job_dead_letters -----------------------------------------------------------
def test_idempotency_key_is_unique_per_tenant_and_actor(app_engine: Engine) -> None:
    tid = create_tenant(app_engine)
    actor, other = uuid4(), uuid4()
    sql = text(
        "INSERT INTO idempotency_keys (tenant_id, actor_id, key, endpoint, request_hash, expires_at) "
        "VALUES (:t, :a, 'k-1', 'POST /plants', 'h', :x)"
    )
    expires = datetime.now(UTC) + timedelta(hours=24)
    with tenant_conn(app_engine, tid) as conn:
        conn.execute(sql, {"t": tid, "a": actor, "x": expires})
        conn.execute(sql, {"t": tid, "a": other, "x": expires})  # same key, different actor: fine
    with expect_db_error(psycopg.errors.UniqueViolation), tenant_conn(app_engine, tid) as conn:
        conn.execute(sql, {"t": tid, "a": actor, "x": expires})


def test_idempotency_response_columns_are_nullable_until_the_command_completes(
    app_engine: Engine,
) -> None:
    tid = create_tenant(app_engine)
    with tenant_conn(app_engine, tid) as conn:
        INSERTERS["idempotency_keys"](conn, tid)
        row = conn.execute(
            text("SELECT response_status, response_body FROM idempotency_keys")
        ).one()
    assert tuple(row) == (None, None)


def test_dead_letter_message_id_is_unique_per_tenant(app_engine: Engine) -> None:
    tid = create_tenant(app_engine)
    sql = text(
        "INSERT INTO job_dead_letters (tenant_id, queue, actor_name, message_id, payload, attempts, "
        "last_error, dead_lettered_at) VALUES (:t, 'default', 'a', 'm-1', '{}'::jsonb, 5, 'e', now())"
    )
    with tenant_conn(app_engine, tid) as conn:
        conn.execute(sql, {"t": tid})
    with expect_db_error(psycopg.errors.UniqueViolation), tenant_conn(app_engine, tid) as conn:
        conn.execute(sql, {"t": tid})


def test_dead_letter_only_resolution_columns_are_updatable(app_engine: Engine) -> None:
    tid = create_tenant(app_engine)
    with tenant_conn(app_engine, tid) as conn:
        INSERTERS["job_dead_letters"](conn, tid)
    with tenant_conn(app_engine, tid) as conn:
        conn.execute(
            text("UPDATE job_dead_letters SET resolved_at = now(), resolved_by = :u"),
            {"u": uuid4()},
        )
    for column, value in [
        ("last_error", "'changed'"),
        ("attempts", "1"),
        ("payload", "'{}'::jsonb"),
    ]:
        with (
            expect_db_error(psycopg.errors.InsufficientPrivilege, "permission denied"),
            tenant_conn(app_engine, tid) as conn,
        ):
            conn.execute(text(f"UPDATE job_dead_letters SET {column} = {value}"))


# --- grants ----------------------------------------------------------------------------------------
def _domain_tables(owner_engine: Engine) -> list[str]:
    from tests.integration.db.test_schema_conventions import tenant_tables

    return sorted(tenant_tables(owner_engine))


def test_app_role_has_no_delete_privilege_on_domain_tables(owner_engine: Engine) -> None:
    """INV-PLT-07: no hard deletes. Only idempotency_keys (expiry cleanup) grants DELETE."""
    with owner_engine.connect() as conn:
        for table in _domain_tables(owner_engine):
            can_delete = conn.execute(
                text("SELECT has_table_privilege('qualloop_app', CAST(:t AS regclass), 'DELETE')"),
                {"t": f"public.{table}"},
            ).scalar_one()
            assert can_delete is (table == "idempotency_keys"), f"{table}: DELETE={can_delete}"


def test_app_role_cannot_truncate_or_alter_any_table(owner_engine: Engine) -> None:
    with owner_engine.connect() as conn:
        for table in _domain_tables(owner_engine):
            for privilege in ("TRUNCATE", "REFERENCES", "TRIGGER"):
                assert (
                    conn.execute(
                        text(
                            "SELECT has_table_privilege('qualloop_app', CAST(:t AS regclass), :p)"
                        ),
                        {"t": f"public.{table}", "p": privilege},
                    ).scalar_one()
                    is False
                ), f"{table} grants {privilege}"


def test_tenant_update_privilege_is_limited_to_name_plan_settings_and_audit_columns(
    owner_engine: Engine,
) -> None:
    with owner_engine.connect() as conn:
        allowed = {
            col
            for (col,) in conn.execute(
                text(
                    "SELECT attname FROM pg_attribute WHERE attrelid = 'public.tenants'::regclass "
                    "AND attnum > 0 AND NOT attisdropped "
                    "AND has_column_privilege('qualloop_app', 'public.tenants', attname, 'UPDATE')"
                )
            )
        }
    assert allowed == {"name", "plan", "settings", "updated_at", "updated_by"}


def test_activity_log_grants_are_select_and_insert_only(owner_engine: Engine) -> None:
    with owner_engine.connect() as conn:
        privileges = {
            p: conn.execute(
                text("SELECT has_table_privilege('qualloop_app', 'public.activity_log', :p)"),
                {"p": p},
            ).scalar_one()
            for p in ("SELECT", "INSERT", "UPDATE", "DELETE")
        }
    assert privileges == {"SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False}


def test_public_has_no_temp_or_create_privilege(owner_engine: Engine) -> None:
    """INV-PLT-18 (D-3): PUBLIC may not create temp tables in the database or objects in schema public."""
    with owner_engine.connect() as conn:
        public_acl = (
            conn.execute(
                text(
                    "SELECT privilege_type FROM pg_database d, aclexplode(d.datacl) a "
                    "WHERE d.datname = current_database() AND a.grantee = 0"
                )
            )
            .scalars()
            .all()
        )
        schema_acl = (
            conn.execute(
                text(
                    "SELECT privilege_type FROM pg_namespace n, aclexplode(n.nspacl) a "
                    "WHERE n.nspname = 'public' AND a.grantee = 0"
                )
            )
            .scalars()
            .all()
        )
        app_create = conn.execute(
            text("SELECT has_schema_privilege('qualloop_app', 'public', 'CREATE')")
        ).scalar_one()
    assert "TEMPORARY" not in public_acl
    assert "CREATE" not in schema_acl
    assert app_create is False
