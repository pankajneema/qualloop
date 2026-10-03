"""P02 commands are registered with the permissions of API.md 3.2 / 3.3 / 2 (#9, #10, #11, #24), and the events they
emit are in the registry (ARCHITECTURE 7)."""

import re
from typing import Any
from uuid import uuid4

import pytest

from tests.factories.contract import load

PARAM = re.compile(r"\{[^}]+\}")

QUALITY_COMMANDS = [
    "/suppliers",
    "/suppliers/{id}/update",
    "/suppliers/{id}/archive",
    "/suppliers/{id}/contacts",
    "/contacts/{id}/update",
    "/contacts/{id}/set-quality-contact",
    "/contacts/{id}/verify/start",
    "/contacts/{id}/verify/confirm",
    "/contacts/{id}/disable",
    "/contacts/{id}/replace",
    "/contacts/{id}/consents",
    "/customers",
    "/customers/{id}/update",
    "/customers/{id}/archive",
    "/parts",
    "/parts/{id}/update",
    "/parts/{id}/archive",
    "/customer-parts",
    "/customer-parts/{id}/archive",
    "/supplier-parts",
    "/supplier-parts/{id}/update",
    "/supplier-parts/{id}/archive",
    "/imports",
    "/imports/{id}/map",
    "/imports/{id}/validate",
    "/imports/{id}/cancel",
    "/imports/{id}/confirm",
]
CAN_APPROVE_COMMANDS = ["/suppliers/{id}/change-status"]


def by_path() -> dict[str, Any]:
    return {PARAM.sub("{id}", c.path): c for c in load("app.core.commands.base", "all_commands")()}


@pytest.mark.parametrize("path", QUALITY_COMMANDS)
def test_quality_commands_are_registered_post_with_quality_permission(path: str) -> None:
    command = by_path().get(path)
    assert command is not None, f"POST {path} is not a registered command"
    assert command.method == "POST"
    permission = command.permission
    assert "quality" in permission.roles and "viewer" not in permission.roles
    assert permission.requires_can_approve is False and permission.admin_or_can_approve is False


@pytest.mark.parametrize("path", CAN_APPROVE_COMMANDS)
def test_change_status_is_registered_with_quality_and_can_approve(path: str) -> None:
    command = by_path().get(path)
    assert command is not None
    permission = command.permission
    assert "quality" in permission.roles and permission.requires_can_approve is True


def test_no_masters_command_can_be_called_by_the_ai_or_a_supplier_session() -> None:
    check = load("app.core.permissions", "check_permission")
    actor_cls = load("app.core.permissions", "Actor")
    forbidden = load("app.core.errors", "Forbidden")
    for path in QUALITY_COMMANDS + CAN_APPROVE_COMMANDS:
        command = by_path()[path]
        for kind in ("ai", "supplier_session"):
            who = actor_cls(
                type=kind,
                user_id=uuid4(),
                tenant_id=uuid4(),
                role="admin",
                can_approve=True,
                plant_ids=(),
            )
            with pytest.raises(forbidden):
                check(command.permission, who, command=True)


DERIVED = [
    "SUPPLIER_CREATED",
    "SUPPLIER_UPDATED",
    "SUPPLIER_ARCHIVED",
    "CONTACT_VERIFIED",
    "CONTACT_DISABLED",
    "CONTACT_REPLACED",
    "IMPORT_CONFIRMED",
]


@pytest.mark.parametrize("event", DERIVED)
def test_p02_derived_events_are_registered_with_an_emitter(event: str) -> None:
    spec = load("app.core.outbox.registry", "get")(event)
    assert spec is not None, f"{event} missing from the event registry"
    assert spec.derived is True and spec.emitters, event


def test_supplier_status_changed_is_a_blueprint_event_with_an_emitter() -> None:
    spec = load("app.core.outbox.registry", "get")("SUPPLIER_STATUS_CHANGED")
    assert spec is not None and spec.derived is False and spec.emitters
