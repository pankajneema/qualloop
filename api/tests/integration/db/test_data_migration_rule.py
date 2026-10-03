"""INV-PLT-19 / DATA_MODEL 0.9: row-touching migrations run per tenant, under RLS, with asserted counts and
one activity_log row per tenant. Proven on the real plants/activity_log tables with two tenants."""

import re
from collections.abc import Callable
from uuid import UUID

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, Engine, text

from tests.conftest import API_ROOT
from tests.factories.db import create_plant, create_tenant, tenant_conn

pytestmark = pytest.mark.integration

REVISION = "0042"
DATA_STATEMENT = re.compile(
    r"\b(INSERT\s+INTO|UPDATE\s+[\w.\"]+\s+SET|DELETE\s+FROM)\b", re.IGNORECASE
)


def _two_tenants(app_engine: Engine) -> tuple[UUID, UUID]:
    a, b = create_tenant(app_engine), create_tenant(app_engine)
    for tenant, plants in ((a, 2), (b, 3)):
        for _ in range(plants):
            create_plant(app_engine, tenant)
    return a, b


def _run(
    owner_engine: Engine, a: UUID, b: UUID, expected_after: Callable[[int], int]
) -> dict[UUID, tuple[int, int]]:
    from helpers import data_migration_per_tenant

    def step(conn: Connection) -> None:
        conn.execute(text("UPDATE plants SET address = 'migrated'"))

    def activity(conn: Connection, tenant: UUID, action: str) -> None:
        conn.execute(
            text(
                "INSERT INTO activity_log (tenant_id, object_type, object_id, action, actor_type) "
                "VALUES (:t, 'migration', :t, :a, 'system')"
            ),
            {"t": tenant, "a": action},
        )

    transactional = owner_engine.execution_options(isolation_level="READ COMMITTED")
    with (
        transactional.connect() as conn,
        conn.begin(),
        Operations.context(MigrationContext.configure(conn)),
    ):
        return data_migration_per_tenant(
            REVISION,
            tenant_ids_sql=(
                f"SELECT x FROM app_active_tenant_ids() x WHERE x IN ('{a}'::uuid, '{b}'::uuid)"
            ),
            count_sql="SELECT count(*) FROM plants WHERE address IS DISTINCT FROM 'migrated'",
            step=step,
            expected_after=expected_after,
            write_activity=activity,
        )


def test_data_migrations_set_tenant_guc_and_assert_counts(
    owner_engine: Engine, app_engine: Engine
) -> None:
    a, b = _two_tenants(app_engine)
    result = _run(owner_engine, a, b, lambda before: 0)
    assert result == {a: (2, 0), b: (3, 0)}  # each tenant counted only its own rows
    for tenant in (a, b):
        with tenant_conn(app_engine, tenant) as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM plants WHERE address = 'migrated'")
                ).scalar_one()
                > 0
            )
            logged = conn.execute(
                text("SELECT action, actor_type FROM activity_log WHERE object_type = 'migration'")
            ).all()
        assert [tuple(r) for r in logged] == [(f"migration.{REVISION}", "system")]


def test_data_migration_aborts_and_rolls_back_every_tenant_when_one_count_is_wrong(
    owner_engine: Engine, app_engine: Engine
) -> None:
    a, b = _two_tenants(app_engine)
    with pytest.raises(RuntimeError, match="aborting"):
        _run(owner_engine, a, b, lambda before: before)  # claims "nothing changes": wrong
    for tenant in (a, b):
        with tenant_conn(app_engine, tenant) as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM plants WHERE address = 'migrated'")
                ).scalar_one()
                == 0
            )
            assert (
                conn.execute(
                    text("SELECT count(*) FROM activity_log WHERE object_type = 'migration'")
                ).scalar_one()
                == 0
            )


def test_every_data_changing_migration_uses_the_per_tenant_helper() -> None:
    """Static guard: a migration that INSERTs/UPDATEs/DELETEs rows must go through data_migration_per_tenant."""
    offenders = []
    for path in sorted((API_ROOT / "alembic" / "versions").glob("*.py")):
        source = path.read_text()
        if DATA_STATEMENT.search(source) and "data_migration_per_tenant" not in source:
            offenders.append(path.name)
    assert offenders == []
