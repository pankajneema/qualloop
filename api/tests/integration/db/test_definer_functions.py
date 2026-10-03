"""DATA_MODEL 8 / ADR-004 item 8 / INV-PLT-18: the SECURITY DEFINER lookup functions P01 creates."""

import re
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Connection, Engine, text

from tests.factories.db import (
    create_plant,
    create_tenant,
    create_user,
    insert_outbox_event,
    tenant_conn,
)

pytestmark = pytest.mark.integration

P01_DEFINER_FUNCTIONS = {"app_resolve_login", "app_active_tenant_ids", "app_claim_outbox_batch"}
SAFE_SEARCH_PATH = "search_path=pg_catalog, public, pg_temp"
TABLE_WORDS = "tenants|users|plants|activity_log|outbox_events|idempotency_keys|job_dead_letters"


def _definers(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT p.proname, r.rolname, pg_get_function_identity_arguments(p.oid), p.proconfig,
                       p.prosrc, pg_get_function_result(p.oid)
                FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner
                WHERE p.pronamespace = 'public'::regnamespace AND p.prosecdef
                """
            )
        ).all()
    found = [tuple(r) for r in rows]
    assert found, "no SECURITY DEFINER functions exist in schema public"
    return found


def test_p01_creates_exactly_the_three_documented_definer_functions(owner_engine: Engine) -> None:
    assert {d[0] for d in _definers(owner_engine)} == P01_DEFINER_FUNCTIONS


def test_definer_functions_have_safe_search_path(owner_engine: Engine) -> None:
    """INV-PLT-18: pinned search_path and owner qualloop_sysfn."""
    for name, owner, _args, config, _src, _result in _definers(owner_engine):
        assert owner == "qualloop_sysfn", f"{name} owned by {owner}"
        assert config is not None and SAFE_SEARCH_PATH in config, f"{name}: {config}"


def test_definer_functions_reference_tables_only_schema_qualified(owner_engine: Engine) -> None:
    unqualified = re.compile(
        rf"\b(from|join|update|into)\s+(?!public\.)({TABLE_WORDS})\b", re.IGNORECASE
    )
    for name, _o, _a, _c, src, _r in _definers(owner_engine):
        assert not unqualified.search(src), f"{name} has an unqualified table reference"


def test_definer_functions_are_executable_by_app_role_only(owner_engine: Engine) -> None:
    with owner_engine.connect() as conn:
        for name, *_ in _definers(owner_engine):
            grantees = conn.execute(
                text(
                    """
                    SELECT a.grantee, a.privilege_type
                    FROM pg_proc p, aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) a
                    WHERE p.proname = :n AND p.pronamespace = 'public'::regnamespace
                    """
                ),
                {"n": name},
            ).all()
            assert all(g != 0 for g, _ in grantees), f"{name} is executable by PUBLIC"
            app_exec = conn.execute(
                text(
                    "SELECT has_function_privilege('qualloop_app', p.oid, 'EXECUTE') FROM pg_proc p "
                    "WHERE p.proname = :n AND p.pronamespace = 'public'::regnamespace"
                ),
                {"n": name},
            ).scalar_one()
            assert app_exec is True, f"{name} not executable by qualloop_app"


def test_definer_functions_return_ids_and_scheduling_fields_only(owner_engine: Engine) -> None:
    for name, _o, _a, _c, _src, result in _definers(owner_engine):
        assert "password" not in result.lower(), f"{name} returns {result}"
        assert "mobile" not in result.lower(), f"{name} returns {result}"
        assert "email" not in result.lower(), f"{name} returns {result}"


def test_app_resolve_login_maps_email_to_tenant_and_user_case_insensitively(
    app_engine: Engine,
) -> None:
    tenant = create_tenant(app_engine)
    user = create_user(app_engine, tenant, email="Mixed.Case@Example.test")
    with app_engine.connect() as conn:  # no tenant context at all: this is the login path
        for probe in ("mixed.case@example.test", "MIXED.CASE@EXAMPLE.TEST"):
            row = conn.execute(text("SELECT * FROM app_resolve_login(:e)"), {"e": probe}).one()
            ids = {v for v in row if isinstance(v, UUID)}
            assert ids == {tenant, user.id}, f"{probe}: {row}"
            assert all(isinstance(v, UUID) for v in row), "definer must return ids only"
        assert (
            conn.execute(text("SELECT * FROM app_resolve_login('nobody@example.test')")).all() == []
        )


def test_app_resolve_login_does_not_leak_other_columns_to_a_direct_user_query(
    app_engine: Engine,
) -> None:
    tenant = create_tenant(app_engine)
    create_user(app_engine, tenant)
    with app_engine.connect() as conn:  # the sysfn policy is not usable by qualloop_app directly
        assert conn.execute(text("SELECT count(*) FROM users")).scalar_one() == 0


def test_app_active_tenant_ids_lists_every_tenant_without_a_tenant_context(
    app_engine: Engine,
) -> None:
    a, b = create_tenant(app_engine), create_tenant(app_engine)
    with app_engine.connect() as conn:
        ids = {r[0] for r in conn.execute(text("SELECT app_active_tenant_ids()"))}
    assert {a, b} <= ids


def _claim(conn: Connection, limit: int) -> list[tuple[UUID, UUID]]:
    rows = conn.execute(text("SELECT id, tenant_id FROM app_claim_outbox_batch(:n)"), {"n": limit})
    return [(r[0], r[1]) for r in rows]


def test_app_claim_outbox_batch_returns_pending_rows_across_tenants_oldest_first(
    app_engine: Engine, clean_outbox: None
) -> None:
    from datetime import UTC, datetime, timedelta

    a, b = create_tenant(app_engine), create_tenant(app_engine)
    now = datetime.now(UTC)
    oldest = insert_outbox_event(app_engine, a, created_at=now - timedelta(minutes=3))
    middle = insert_outbox_event(app_engine, b, created_at=now - timedelta(minutes=2))
    newest = insert_outbox_event(app_engine, a, created_at=now - timedelta(minutes=1))
    with app_engine.connect() as conn, conn.begin():
        claimed = _claim(conn, 2)
    assert [c[0] for c in claimed] == [oldest, middle]
    assert claimed[1][1] == b
    with app_engine.connect() as conn, conn.begin():
        assert newest in [c[0] for c in _claim(conn, 10)]


def test_app_claim_outbox_batch_skips_processed_and_dead_rows(
    app_engine: Engine, clean_outbox: None
) -> None:
    tenant = create_tenant(app_engine)
    pending = insert_outbox_event(app_engine, tenant)
    dead = insert_outbox_event(app_engine, tenant, attempts=5)
    done = insert_outbox_event(app_engine, tenant)
    with tenant_conn(app_engine, tenant, actor_type="system") as conn:
        conn.execute(
            text("UPDATE outbox_events SET processed_at = now() WHERE id = :i"), {"i": done}
        )
    with app_engine.connect() as conn, conn.begin():
        claimed = {c[0] for c in _claim(conn, 100)}
    assert pending in claimed
    assert dead not in claimed
    assert done not in claimed


def test_outbox_rows_remain_invisible_to_the_app_role_without_tenant_context(
    app_engine: Engine, clean_outbox: None
) -> None:
    tenant = create_tenant(app_engine)
    create_plant(app_engine, tenant)
    insert_outbox_event(app_engine, tenant)
    with app_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM outbox_events")).scalar_one() == 0
