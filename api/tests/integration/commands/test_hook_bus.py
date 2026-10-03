"""ARCHITECTURE 3.1 rule 3: the in-process hook bus. A subscribed hook runs INSIDE the command's transaction, and a hook
that raises rolls back the business row, the audit row, the outbox row and the idempotency reservation."""

from collections import defaultdict
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text

from app.core import hooks
from tests.factories.contract import load
from tests.factories.db import SeededTenant, fetch_all
from tests.integration.commands.probe import actor_for, make_probe_command, run
from tests.integration.commands.test_command_audit_and_outbox import log_rows, outbox_rows

pytestmark = pytest.mark.integration


@pytest.fixture
def isolated_hooks(monkeypatch: pytest.MonkeyPatch) -> defaultdict[str, list[Callable[..., None]]]:
    """A private subscriber table, so nothing this test subscribes outlives it."""
    table: defaultdict[str, list[Callable[..., None]]] = defaultdict(list)
    monkeypatch.setattr(hooks, "_HOOKS", table)
    return table


def admin_command() -> Any:
    permission_cls = load("app.core.permissions", "Permission")
    return make_probe_command(permission_cls(roles=frozenset({"admin"})))


def count(engine: Engine, tenant: SeededTenant, code: str) -> int:
    return len(fetch_all(engine, tenant.id, "SELECT 1 FROM plants WHERE code = :c", {"c": code}))


def test_a_subscribed_hook_runs_during_the_command_inside_its_transaction(
    app_engine: Engine, seeded: SeededTenant, clean_outbox: None, isolated_hooks: Any
) -> None:
    assert seeded.admin
    command = admin_command()
    code, sibling = f"HK{uuid4().hex[:6].upper()}", f"HS{uuid4().hex[:6].upper()}"
    seen: dict[str, Any] = {}

    def hook(session: Any, actor: Any, outcome: Any) -> None:
        seen["actor"] = actor
        seen["action"] = outcome.action
        # same transaction: the session sees the command's uncommitted row ...
        seen["visible_to_hook"] = session.execute(
            text("SELECT count(*) FROM plants WHERE code = :c"), {"c": code}
        ).scalar_one()
        # ... while another connection does not
        seen["visible_outside"] = count(app_engine, seeded, code)
        session.execute(
            text("INSERT INTO plants (tenant_id, name, code) VALUES (:t, 'Hook plant', :c)"),
            {"t": actor.tenant_id, "c": sibling},
        )

    hooks.subscribe(f"command.{command.name}", hook)
    result = run(command, actor_for(seeded.admin), code)

    assert result.status_code == 200
    assert seen["actor"].user_id == seeded.admin.id and seen["action"] == "plant.create"
    assert seen["visible_to_hook"] == 1 and seen["visible_outside"] == 0
    assert count(app_engine, seeded, code) == 1
    assert count(app_engine, seeded, sibling) == 1, "the hook's own write commits with the command"


def test_a_hook_subscribed_to_another_command_does_not_run(
    app_engine: Engine, seeded: SeededTenant, isolated_hooks: Any
) -> None:
    assert seeded.admin
    calls: list[str] = []
    hooks.subscribe("command.some.other_command", lambda *_a, **_k: calls.append("ran"))
    run(admin_command(), actor_for(seeded.admin), f"HO{uuid4().hex[:6].upper()}")
    assert calls == []


def test_a_raising_hook_rolls_back_business_audit_outbox_and_idempotency_rows(
    app_engine: Engine, seeded: SeededTenant, clean_outbox: None, isolated_hooks: Any
) -> None:
    assert seeded.admin
    command = admin_command()
    code, key = f"HR{uuid4().hex[:6].upper()}", str(uuid4())
    audit_before = len(log_rows(app_engine, seeded.id))

    def boom(session: Any, actor: Any, outcome: Any) -> None:
        raise RuntimeError("hook exploded")

    hooks.subscribe(f"command.{command.name}", boom)
    with pytest.raises(RuntimeError, match="hook exploded"):
        run(command, actor_for(seeded.admin), code, key=key)

    assert count(app_engine, seeded, code) == 0, "business row must be rolled back"
    assert len(log_rows(app_engine, seeded.id)) == audit_before, "audit row must be rolled back"
    assert outbox_rows(app_engine, seeded.id) == [], "outbox row must be rolled back"
    assert (
        fetch_all(
            app_engine, seeded.id, "SELECT 1 FROM idempotency_keys WHERE key = :k", {"k": key}
        )
        == []
    ), "the idempotency reservation must be rolled back, so the client can retry"


def test_after_a_raising_hook_the_same_idempotency_key_can_be_used_again(
    app_engine: Engine, seeded: SeededTenant, clean_outbox: None, isolated_hooks: Any
) -> None:
    assert seeded.admin
    command = admin_command()
    code, key = f"HT{uuid4().hex[:6].upper()}", str(uuid4())
    failing = [True]

    def flaky(session: Any, actor: Any, outcome: Any) -> None:
        if failing[0]:
            raise RuntimeError("first attempt fails")

    hooks.subscribe(f"command.{command.name}", flaky)
    with pytest.raises(RuntimeError):
        run(command, actor_for(seeded.admin), code, key=key)
    failing[0] = False
    result = run(command, actor_for(seeded.admin), code, key=key)
    assert result.status_code == 200 and result.replayed is False
    assert count(app_engine, seeded, code) == 1
