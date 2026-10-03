"""A throwaway, UNREGISTERED command for pipeline tests (so the real route/command tables are never touched).

It inserts one plant (code = the request's `code`) and returns the normal `Outcome`, so `run_command` writes the audit
row, the outbox event and the idempotency row exactly as for a real command."""

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import text

from tests.factories.contract import load
from tests.factories.db import SeededUser


class ProbeIn(BaseModel):
    code: str


class ProbeOut(BaseModel):
    id: UUID
    code: str


def make_probe_command(permission: Any, name: str | None = None) -> Any:
    command_cls = load("app.core.commands.base", "Command")
    outcome_cls = load("app.core.commands.base", "Outcome")
    new_id = load("app.core.ids", "new_id")

    def handle(ctx: Any, data: ProbeIn) -> Any:
        plant_id = new_id()
        ctx.session.execute(
            text(
                "INSERT INTO plants (id, tenant_id, name, code) VALUES (:i, :t, 'Probe plant', :c)"
            ),
            {"i": plant_id, "t": ctx.actor.tenant_id, "c": data.code},
        )
        return outcome_cls(
            response=ProbeOut(id=plant_id, code=data.code),
            object_type="plant",
            object_id=plant_id,
            action="plant.create",
            event_type="PLANT_CREATED",
            after={"code": data.code},
        )

    return command_cls(
        name=name or f"zz.probe_{uuid4().hex[:8]}",
        path="/zz-probe",
        permission=permission,
        handle=handle,
    )


def actor_for(user: SeededUser, **override: Any) -> Any:
    actor_cls = load("app.core.permissions", "Actor")
    fields: dict[str, Any] = {
        "type": "user",
        "user_id": user.id,
        "tenant_id": user.tenant_id,
        "role": user.role,
        "can_approve": user.can_approve,
        "plant_ids": user.plant_ids,
    }
    fields.update(override)
    return actor_cls(**fields)


def run(command: Any, actor: Any, code: str, key: str | None = None) -> Any:
    run_command = load("app.core.commands.base", "run_command")
    return run_command(
        command, ProbeIn(code=code), actor=actor, idempotency_key=key, endpoint="POST /zz-probe"
    )
