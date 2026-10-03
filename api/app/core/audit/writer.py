"""Audit writer: one `activity_log` row with before/after/reason/actor/session/ip, in the caller's transaction.

Written with a Core INSERT and no RETURNING (a supplier-session actor may append but never read the table).
`before`/`after` are the aggregate's public read model (never password hashes or other secrets).
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.core.audit.models import activity_log
from app.core.ids import new_id
from app.core.permissions import Actor


def record_activity(
    session: Session,
    *,
    actor: Actor,
    object_type: str,
    object_id: UUID,
    action: str,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    reason: str | None = None,
) -> None:
    session.execute(
        insert(activity_log).values(
            id=new_id(),
            tenant_id=actor.tenant_id,
            created_by=actor.user_id if actor.type == "user" else None,
            updated_by=actor.user_id if actor.type == "user" else None,
            object_type=object_type,
            object_id=object_id,
            action=action,
            before=dict(before) if before is not None else None,
            after=dict(after) if after is not None else None,
            reason=reason,
            actor_type=actor.type,
            actor_id=actor.user_id if actor.type in ("user", "supplier_session") else None,
            session_id=actor.session_id,
            ip=actor.ip,
        )
    )
