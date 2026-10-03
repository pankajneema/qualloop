"""Tenant context for a request (ADR-004): one transaction per unit of work, scoped by the caller's tenant.

The authentication dependency resolves the session to an `Actor` (see `auth.deps`); this module opens the transaction
with that actor's tenant and identity set as transaction-local GUCs, so RLS applies to everything inside.
"""

from contextlib import AbstractContextManager

from sqlalchemy.orm import Session

from app.core.db import read_tx, tenant_tx
from app.core.permissions import Actor


def actor_tx(actor: Actor, *, write: bool = False) -> AbstractContextManager[Session]:
    """A READ ONLY (default) or read-write transaction as `actor`'s tenant."""
    scope = tenant_tx if write else read_tx
    return scope(actor.tenant_id, actor.type, actor.user_id)
