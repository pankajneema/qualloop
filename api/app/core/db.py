"""Engine and tenant-scoped transactions (ADR-003, ADR-004).

Every unit of work (request, job, dispatcher cycle) runs in ONE READ COMMITTED transaction whose tenant context is set
with `set_config(name, value, true)`: transaction-local, so nothing survives commit/rollback on a pooled connection.
An unset tenant context sees zero rows and cannot write (fail closed, DB policy).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

from app.core.config import get_settings

_current: ContextVar[Session | None] = ContextVar("current_session", default=None)

_SET_CONTEXT = text(
    "SELECT set_config('app.tenant_id', :tenant_id, true), "
    "set_config('app.actor_type', :actor_type, true), "
    "set_config('app.actor_id', :actor_id, true)"
)


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        pool_size=5,
        isolation_level="READ COMMITTED",  # ADR-003 M1: lock first, then sum in a separate statement
    )


def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


def current_session() -> Session:
    """The session of the enclosing request / `tenant_tx` / job."""
    session = _current.get()
    if session is None:
        raise RuntimeError("no database session: call inside tenant_tx(), read_tx() or a job")
    return session


@contextmanager
def _scoped_session(
    tenant_id: UUID | None, actor_type: str, actor_id: UUID | None, *, read_only: bool
) -> Iterator[Session]:
    session = get_sessionmaker()()

    # The context is applied when the transaction actually begins on a connection, so a unit of work that never
    # touches the database (for example a virus scan) does not hold a connection or an open transaction.
    @event.listens_for(session, "after_begin")
    def _apply_context(
        _session: Session, _transaction: SessionTransaction, connection: Connection
    ) -> None:
        if read_only:
            connection.execute(text("SET TRANSACTION READ ONLY"))
        connection.execute(
            _SET_CONTEXT,
            {
                "tenant_id": str(tenant_id) if tenant_id else "",
                "actor_type": actor_type,
                "actor_id": str(actor_id) if actor_id else "",
            },
        )

    token = _current.set(session)
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        _current.reset(token)
        session.close()


@contextmanager
def tenant_tx(
    tenant_id: UUID, actor_type: str = "system", actor_id: UUID | None = None
) -> Iterator[Session]:
    """One read-write transaction scoped to `tenant_id`: commit on success, rollback on any exception."""
    with _scoped_session(tenant_id, actor_type, actor_id, read_only=False) as session:
        yield session


@contextmanager
def read_tx(
    tenant_id: UUID, actor_type: str = "user", actor_id: UUID | None = None
) -> Iterator[Session]:
    """Like `tenant_tx` but the transaction is READ ONLY (queries; ARCHITECTURE section 4)."""
    with _scoped_session(tenant_id, actor_type, actor_id, read_only=True) as session:
        yield session


@contextmanager
def system_tx() -> Iterator[Session]:
    """A system-actor transaction with NO tenant context, for cross-tenant infrastructure work.

    Only the dispatcher uses it: it claims rows through the definer function `app_claim_outbox_batch` and then switches
    the tenant GUC per row before touching that row. Without a tenant GUC every table is empty to this session."""
    with _scoped_session(None, "system", None, read_only=False) as session:
        yield session


def set_tenant(session: Session, tenant_id: UUID) -> None:
    """Switch the transaction-local tenant GUC (dispatcher per-row updates)."""
    session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
