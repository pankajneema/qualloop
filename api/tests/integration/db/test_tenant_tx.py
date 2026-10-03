"""ADR-004 item 3 / ADR-003: tenant_tx() and read_tx() set transaction-local GUCs on a READ COMMITTED transaction."""

from typing import Any
from uuid import uuid4

import psycopg.errors
import pytest
from sqlalchemy import Engine, text

from app.core.db import get_engine
from tests.factories.contract import load
from tests.factories.db import create_plant, create_tenant, fetch_all
from tests.factories.dberr import expect_db_error

pytestmark = pytest.mark.integration


def tenant_tx(*args: Any, **kw: Any) -> Any:
    return load("app.core.db", "tenant_tx")(*args, **kw)


def read_tx(*args: Any, **kw: Any) -> Any:
    return load("app.core.db", "read_tx")(*args, **kw)


def test_tenant_tx_sets_tenant_actor_type_and_actor_id_for_the_transaction(
    app_engine: Engine, engine_env: None
) -> None:
    tenant, actor = create_tenant(app_engine), uuid4()
    with tenant_tx(tenant, actor_type="user", actor_id=actor) as session:
        values = session.execute(
            text(
                "SELECT current_setting('app.tenant_id', true), current_setting('app.actor_type', true), "
                "current_setting('app.actor_id', true)"
            )
        ).one()
    assert tuple(values) == (str(tenant), "user", str(actor))


def test_tenant_tx_defaults_to_the_system_actor_without_an_actor_id(
    app_engine: Engine, engine_env: None
) -> None:
    tenant = create_tenant(app_engine)
    with tenant_tx(tenant) as session:
        values = session.execute(
            text(
                "SELECT current_setting('app.actor_type', true), nullif(current_setting('app.actor_id', true), '')"
            )
        ).one()
    assert tuple(values) == ("system", None)


def test_tenant_tx_runs_at_read_committed(app_engine: Engine, engine_env: None) -> None:
    """ADR-003 M1: lock-then-sum in separate statements relies on a fresh snapshot per statement."""
    with tenant_tx(create_tenant(app_engine)) as session:
        assert session.execute(text("SHOW transaction_isolation")).scalar_one() == "read committed"


def test_tenant_tx_commits_on_success_and_rolls_back_on_exception(
    app_engine: Engine, engine_env: None
) -> None:
    tenant = create_tenant(app_engine)
    with tenant_tx(tenant) as session:
        session.execute(
            text("INSERT INTO plants (tenant_id, name, code) VALUES (:t, 'kept', 'KEEP1')"),
            {"t": tenant},
        )
    with pytest.raises(RuntimeError, match="boom"), tenant_tx(tenant) as session:
        session.execute(
            text("INSERT INTO plants (tenant_id, name, code) VALUES (:t, 'lost', 'LOST1')"),
            {"t": tenant},
        )
        raise RuntimeError("boom")
    codes = {r["code"] for r in fetch_all(app_engine, tenant, "SELECT code FROM plants")}
    assert codes == {"KEEP1"}


def test_tenant_tx_shows_only_its_tenants_rows(app_engine: Engine, engine_env: None) -> None:
    a, b = create_tenant(app_engine), create_tenant(app_engine)
    pa, pb = create_plant(app_engine, a), create_plant(app_engine, b)
    with tenant_tx(a) as session:
        assert {r[0] for r in session.execute(text("SELECT id FROM plants"))} == {pa}
    with tenant_tx(b) as session:
        assert {r[0] for r in session.execute(text("SELECT id FROM plants"))} == {pb}


def test_tenant_tx_cannot_write_another_tenants_rows(app_engine: Engine, engine_env: None) -> None:
    a, b = create_tenant(app_engine), create_tenant(app_engine)
    with (
        expect_db_error(psycopg.errors.InsufficientPrivilege, "row-level security"),
        tenant_tx(a) as session,
    ):
        session.execute(
            text("INSERT INTO plants (tenant_id, name, code) VALUES (:t, 'x', 'XSS1')"), {"t": b}
        )


def test_guc_does_not_survive_tenant_tx_on_the_reused_pooled_connection(
    app_engine: Engine, engine_env: None
) -> None:
    tenant = create_tenant(app_engine)
    create_plant(app_engine, tenant)
    with tenant_tx(tenant) as session:
        pid_inside = session.execute(text("SELECT pg_backend_pid()")).scalar_one()
        assert session.execute(text("SELECT count(*) FROM plants")).scalar_one() == 1
    with get_engine().connect() as conn:  # next checkout from the same pool, no tenant_tx
        pid_after = conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
        leaked = conn.execute(text("SELECT current_setting('app.tenant_id', true)")).scalar_one()
        rows = conn.execute(text("SELECT count(*) FROM plants")).scalar_one()
    assert pid_after == pid_inside, "pool did not reuse the connection; the test proves nothing"
    assert leaked in (None, "") and rows == 0


def test_read_tx_is_read_only_and_tenant_scoped(app_engine: Engine, engine_env: None) -> None:
    a, b = create_tenant(app_engine), create_tenant(app_engine)
    pa = create_plant(app_engine, a)
    create_plant(app_engine, b)
    with read_tx(a) as session:
        assert {r[0] for r in session.execute(text("SELECT id FROM plants"))} == {pa}
    with expect_db_error(psycopg.errors.ReadOnlySqlTransaction), read_tx(a) as session:
        session.execute(
            text("INSERT INTO plants (tenant_id, name, code) VALUES (:t, 'x', 'RO1')"), {"t": a}
        )


def test_current_session_is_available_inside_tenant_tx_and_refused_outside(
    app_engine: Engine, engine_env: None
) -> None:
    current_session = load("app.core.db", "current_session")
    with pytest.raises(RuntimeError):
        current_session()
    tenant = create_tenant(app_engine)
    with tenant_tx(tenant) as session:
        assert current_session() is session
    with pytest.raises(RuntimeError):
        current_session()
