"""INV-PLT-16 for the P02 revision (`0003_masters_imports`): reversible, and it removes exactly the nine P02 tables."""

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from alembic import command
from app.core.config import Settings
from tests.conftest import alembic_config
from tests.factories.db import create_tenant, tenant_conn
from tests.factories.env import owner_url
from tests.factories.rows import MASTERS_TABLES
from tests.integration.db.test_schema_conventions import P01_TABLES, tenant_tables

pytestmark = pytest.mark.integration


def test_the_masters_revision_sits_directly_on_the_platform_revision(settings: Settings) -> None:
    script = ScriptDirectory.from_config(alembic_config(owner_url()))
    children = [r for r in script.walk_revisions() if r.down_revision == "0002"]
    assert len(children) == 1, "exactly one revision follows the platform revision"
    assert children[0].revision.startswith("0003")


def test_upgrade_creates_the_nine_p02_tables_and_downgrade_to_the_platform_revision_removes_them(
    settings: Settings, owner_engine: Engine
) -> None:
    cfg = alembic_config(owner_url())
    command.upgrade(cfg, "head")
    assert tenant_tables(owner_engine) >= P01_TABLES | set(MASTERS_TABLES)
    command.downgrade(cfg, "0002")
    try:
        assert tenant_tables(owner_engine) == P01_TABLES, "P01 tables stay, every P02 table goes"
    finally:
        command.upgrade(cfg, "head")
    assert tenant_tables(owner_engine) >= P01_TABLES | set(MASTERS_TABLES)


def test_after_a_round_trip_the_masters_tables_work_for_the_app_role(
    settings: Settings, owner_engine: Engine, app_engine: Engine
) -> None:
    cfg = alembic_config(owner_url())
    command.downgrade(cfg, "0002")
    command.upgrade(cfg, "head")
    tenant = create_tenant(app_engine)
    with tenant_conn(app_engine, tenant) as conn:
        conn.execute(
            text(
                "INSERT INTO suppliers (tenant_id, code, name, category, status) "
                "VALUES (:t, 'RT1', 'Round trip', 'service', 'approved')"
            ),
            {"t": tenant},
        )
    with tenant_conn(app_engine, tenant) as conn:
        assert conn.execute(text("SELECT count(*) FROM suppliers")).scalar_one() == 1
