"""API.md 1.3 / ADR-008: role sets, +CA, A-or-CA, plant scope (A-04), AI and supplier actors, viewer on commands."""

from typing import Any
from uuid import uuid4

import pytest

from tests.factories.contract import load

PLANT_A = uuid4()
PLANT_B = uuid4()

# API.md 3.1: the platform commands every phase must keep registered.
P01_COMMAND_PATHS = {
    "/users",
    "/users/{id}/update",
    "/users/{id}/deactivate",
    "/plants",
    "/plants/{id}/update",
    "/tenant/settings/update",
}


def actor(
    role: str = "quality",
    *,
    can_approve: bool = False,
    kind: str = "user",
    plant_ids: tuple[Any, ...] = (),
) -> Any:
    return load("app.core.permissions", "Actor")(
        type=kind,
        user_id=uuid4(),
        tenant_id=uuid4(),
        role=role,
        can_approve=can_approve,
        plant_ids=plant_ids,
    )


def permission(roles: set[str], **kw: Any) -> Any:
    return load("app.core.permissions", "Permission")(roles=frozenset(roles), **kw)


def check(perm: Any, who: Any, *, command: bool = True) -> None:
    load("app.core.permissions", "check_permission")(perm, who, command=command)


def denied() -> Any:
    return load("app.core.errors", "Forbidden")


def test_quality_role_permission_allows_quality_and_admin_but_not_viewer() -> None:
    perm = permission({"quality"})
    check(perm, actor("quality"))
    check(perm, actor("admin"))  # A-70: Admin holds every Q permission
    with pytest.raises(denied()):
        check(perm, actor("viewer"))


def test_admin_only_permission_rejects_quality_even_with_can_approve() -> None:
    perm = permission({"admin"})
    check(perm, actor("admin"))
    with pytest.raises(denied()):
        check(perm, actor("quality", can_approve=True))


def test_viewer_is_rejected_on_a_command_even_if_the_permission_lists_viewer() -> None:
    perm = permission({"viewer", "quality"})
    with pytest.raises(denied()):
        check(perm, actor("viewer"), command=True)


def test_viewer_is_allowed_on_a_query_that_lists_viewer() -> None:
    check(permission({"admin", "quality", "viewer"}), actor("viewer"), command=False)


def test_viewer_is_rejected_on_a_query_that_does_not_list_viewer() -> None:
    with pytest.raises(denied()):
        check(permission({"admin"}), actor("viewer"), command=False)


@pytest.mark.parametrize(
    ("role", "can_approve", "allowed"),
    [
        ("quality", True, True),
        ("quality", False, False),
        ("admin", True, True),
        ("admin", False, False),  # "+CA additionally requires" the flag; admin does not imply it
        ("viewer", True, False),
    ],
)
def test_requires_can_approve_matrix(role: str, can_approve: bool, allowed: bool) -> None:
    perm = permission({"quality"}, requires_can_approve=True)
    who = actor(role, can_approve=can_approve)
    if allowed:
        check(perm, who)
    else:
        with pytest.raises(denied()):
            check(perm, who)


@pytest.mark.parametrize(
    ("role", "can_approve", "allowed"),
    [
        ("admin", False, True),
        ("quality", True, True),
        ("quality", False, False),
        ("viewer", True, False),
    ],
)
def test_admin_or_can_approve_matrix(role: str, can_approve: bool, allowed: bool) -> None:
    perm = permission({"quality"}, admin_or_can_approve=True)
    who = actor(role, can_approve=can_approve)
    if allowed:
        check(perm, who)
    else:
        with pytest.raises(denied()):
            check(perm, who)


@pytest.mark.parametrize("role", ["admin", "quality", "viewer"])
def test_ai_actor_is_denied_whatever_role_flags_or_permission_it_claims(role: str) -> None:
    perm = permission({"admin", "quality", "viewer"})
    with pytest.raises(denied()):
        check(perm, actor(role, can_approve=True, kind="ai"))
    with pytest.raises(denied()):
        check(perm, actor(role, can_approve=True, kind="ai"), command=False)


def test_supplier_session_actor_is_denied_on_internal_permissions() -> None:
    with pytest.raises(denied()):
        check(permission({"quality"}), actor("quality", kind="supplier_session"), command=False)


def test_denied_permission_is_http_403_forbidden() -> None:
    with pytest.raises(denied()) as excinfo:
        check(permission({"admin"}), actor("quality"))
    assert excinfo.value.status == 403
    assert excinfo.value.code == "forbidden"


def test_plant_scope_admin_sees_every_plant() -> None:
    in_scope = load("app.core.permissions", "plant_in_scope")
    assert in_scope(actor("admin"), PLANT_A)
    assert in_scope(actor("admin", plant_ids=()), PLANT_B)


@pytest.mark.parametrize("role", ["quality", "viewer"])
def test_plant_scope_quality_and_viewer_see_only_their_plants(role: str) -> None:
    in_scope = load("app.core.permissions", "plant_in_scope")
    who = actor(role, plant_ids=(PLANT_A,))
    assert in_scope(who, PLANT_A)
    assert not in_scope(who, PLANT_B)


def test_plant_scope_user_without_plants_sees_none() -> None:
    """A-04 conservative reading: plant_ids restricts; an empty list restricts to nothing."""
    in_scope = load("app.core.permissions", "plant_in_scope")
    assert not in_scope(actor("quality", plant_ids=()), PLANT_A)


def test_every_registered_command_has_a_permission_without_viewer_and_ai() -> None:
    commands = load("app.core.commands.base", "all_commands")()
    assert commands, "no commands registered"
    for command in commands:
        roles = set(command.permission.roles)
        assert roles, f"{command.name} has an empty role set"
        assert "viewer" not in roles, f"{command.name} lists viewer"
        assert "ai" not in roles, f"{command.name} lists ai"


def test_platform_commands_are_registered_with_their_api_paths() -> None:
    commands = load("app.core.commands.base", "all_commands")()
    assert {c.path for c in commands} >= P01_COMMAND_PATHS
    assert all(c.method == "POST" for c in commands)


def test_ai_actor_denied_on_every_command() -> None:
    """INV-AI-02: AI never changes state; every command's permission excludes the ai actor type."""
    commands = load("app.core.commands.base", "all_commands")()
    assert commands
    for command in commands:
        with pytest.raises(denied()):
            check(command.permission, actor("admin", can_approve=True, kind="ai"))


def test_supplier_session_actor_denied_on_every_internal_command() -> None:
    commands = load("app.core.commands.base", "all_commands")()
    for command in commands:
        with pytest.raises(denied()):
            check(command.permission, actor("admin", can_approve=True, kind="supplier_session"))


def test_viewer_denied_on_every_registered_command_at_permission_level() -> None:
    commands = load("app.core.commands.base", "all_commands")()
    for command in commands:
        with pytest.raises(denied()):
            check(command.permission, actor("viewer", can_approve=True))


def test_can_approve_commands_reject_without_flag() -> None:
    """Every command flagged +CA rejects admin and quality users that lack can_approve (vacuous until a +CA command exists)."""
    commands = load("app.core.commands.base", "all_commands")()
    for command in (c for c in commands if c.permission.requires_can_approve):
        for role in ("admin", "quality"):
            with pytest.raises(denied()):
                check(command.permission, actor(role, can_approve=False))
