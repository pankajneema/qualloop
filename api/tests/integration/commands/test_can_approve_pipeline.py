"""INV-PLT-10 / API.md 1.3 (+CA): a command flagged `requires_can_approve` rejects admin and quality users without the
`can_approve` flag BEFORE anything is written, and runs for those who have it.

`tests/unit/test_permissions.py::test_can_approve_commands_reject_without_flag` loops over registered +CA commands, and
P01 registers none, so it asserts nothing yet. This test registers its own throwaway +CA command and drives it through the
real `run_command` pipeline (an unregistered `Command`, so the route table is untouched)."""

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from tests.factories.contract import load
from tests.factories.db import SeededTenant, create_user, fetch_all
from tests.integration.commands.probe import actor_for, make_probe_command, run
from tests.integration.commands.test_command_audit_and_outbox import log_rows, outbox_rows

pytestmark = pytest.mark.integration


def plus_ca_command() -> Any:
    permission_cls = load("app.core.permissions", "Permission")
    return make_probe_command(
        permission_cls(roles=frozenset({"quality"}), requires_can_approve=True)
    )


def rows_for(engine: Engine, tenant: SeededTenant, code: str) -> tuple[int, int, int]:
    plants = fetch_all(engine, tenant.id, "SELECT 1 FROM plants WHERE code = :c", {"c": code})
    return len(plants), len(log_rows(engine, tenant.id)), len(outbox_rows(engine, tenant.id))


def test_the_probe_command_really_is_a_plus_ca_command() -> None:
    command = plus_ca_command()
    assert command.permission.requires_can_approve is True


@pytest.mark.parametrize("role", ["quality", "admin"])
def test_user_without_can_approve_gets_403_and_nothing_is_written(
    app_engine: Engine, seeded: SeededTenant, clean_outbox: None, role: str
) -> None:
    """Admin does not bypass +CA (API.md 1.3): admin without the flag is refused like quality."""
    user = create_user(app_engine, seeded.id, role=role, can_approve=False)
    code = f"CA{uuid4().hex[:6].upper()}"
    audit_before, outbox_before = (
        len(log_rows(app_engine, seeded.id)),
        len(outbox_rows(app_engine, seeded.id)),
    )
    forbidden = load("app.core.errors", "Forbidden")

    with pytest.raises(forbidden) as excinfo:
        run(plus_ca_command(), actor_for(user), code, key=str(uuid4()))

    assert excinfo.value.status == 403
    plants, audit, outbox = rows_for(app_engine, seeded, code)
    assert plants == 0, "the handler must not have run"
    assert (audit, outbox) == (audit_before, outbox_before), (
        "no activity_log / outbox rows for a refused command"
    )
    assert fetch_all(app_engine, seeded.id, "SELECT 1 FROM idempotency_keys") == []


@pytest.mark.parametrize("role", ["quality", "admin"])
def test_user_with_can_approve_runs_the_command_and_it_is_audited(
    app_engine: Engine, seeded: SeededTenant, clean_outbox: None, role: str
) -> None:
    user = create_user(app_engine, seeded.id, role=role, can_approve=True)
    code = f"CB{uuid4().hex[:6].upper()}"

    result = run(plus_ca_command(), actor_for(user), code)

    assert result.status_code == 200 and result.body["code"] == code
    plants, audit, outbox = rows_for(app_engine, seeded, code)
    assert plants == 1
    assert audit >= 1 and outbox >= 1


def test_viewer_with_can_approve_is_still_refused_because_viewers_never_run_commands(
    app_engine: Engine, seeded: SeededTenant
) -> None:
    viewer = create_user(app_engine, seeded.id, role="viewer", can_approve=True)
    code = f"CC{uuid4().hex[:6].upper()}"
    with pytest.raises(load("app.core.errors", "Forbidden")):
        run(plus_ca_command(), actor_for(viewer), code)
    assert rows_for(app_engine, seeded, code)[0] == 0


def test_the_can_approve_flag_of_the_actor_is_what_counts_not_the_one_in_the_database_row(
    app_engine: Engine, seeded: SeededTenant
) -> None:
    """The request layer loads the flag fresh from the database for every request; `run_command` trusts its actor."""
    user = create_user(app_engine, seeded.id, role="quality", can_approve=True)
    code = f"CD{uuid4().hex[:6].upper()}"
    with pytest.raises(load("app.core.errors", "Forbidden")):
        run(plus_ca_command(), actor_for(user, can_approve=False), code)
    assert rows_for(app_engine, seeded, code)[0] == 0
