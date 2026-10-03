"""Masters read models (API.md 5): read-only transactions, explicit columns, keyset pagination, no N+1.

Named sorts are backed by the indexes of DATA_MODEL 0.7. Every list answers `{items, next_cursor}`; the cursor is bound to
its sort, so a cursor of another sort is `400`."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, or_, select, tuple_

from app.core.errors import BadRequest, NotFound
from app.core.pagination import DEFAULT_LIMIT, decode_cursor, encode_cursor
from app.core.permissions import Actor
from app.core.tenancy import actor_tx
from app.masters.models import (
    Customer,
    CustomerPart,
    Part,
    Supplier,
    SupplierContact,
    SupplierPart,
)
from app.masters.readmodels import (
    consents_of,
    contact_read,
    customer_part_read,
    customer_read,
    part_read,
    supplier_part_read,
    supplier_read,
)
from app.masters.schemas import (
    ContactRead,
    CustomerPartRead,
    CustomerRead,
    Page,
    PartRead,
    SupplierPartRead,
    SupplierRead,
)

SUPPLIER_SORTS = ("name", "code", "updated_at")
_INVALID_CURSOR = "That page cursor is not valid. Start again from the first page."


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _id_cursor(cursor: str | None, sort: str) -> UUID | None:
    if cursor is None:
        return None
    keys = decode_cursor(cursor, sort)
    try:
        return UUID(str(keys[0]))
    except (IndexError, ValueError) as exc:
        raise BadRequest(_INVALID_CURSOR) from exc


def _next(items_ids: list[UUID], more: bool, sort: str) -> str | None:
    return encode_cursor([str(items_ids[-1])], sort) if more and items_ids else None


# ---------------------------------------------------------------------------------------------- suppliers
def list_suppliers(
    actor: Actor,
    *,
    q: str | None,
    status: str | None,
    category: str | None,
    archived: bool,
    sort: str,
    limit: int,
    cursor: str | None,
) -> Page[SupplierRead]:
    if sort not in SUPPLIER_SORTS:
        raise BadRequest(f"Sort by one of: {', '.join(SUPPLIER_SORTS)}.")
    name_key = func.lower(Supplier.name).label(
        "name_key"
    )  # the DB's own lower(): the cursor must match it
    query: Select[Any] = select(Supplier, name_key).where(Supplier.tenant_id == actor.tenant_id)
    if not archived:
        query = query.where(Supplier.archived_at.is_(None))
    if status:
        query = query.where(Supplier.status == status)
    if category:
        query = query.where(Supplier.category == category)
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        query = query.where(
            or_(
                Supplier.name.ilike(pattern, escape="\\"),
                Supplier.code.ilike(pattern, escape="\\"),
                Supplier.gstin.ilike(pattern, escape="\\"),
            )
        )
    keys = decode_cursor(cursor, sort) if cursor is not None else None
    try:
        if sort == "name":
            order: list[Any] = [func.lower(Supplier.name), Supplier.id]
            if keys is not None:
                query = query.where(
                    tuple_(func.lower(Supplier.name), Supplier.id)
                    > tuple_(str(keys[0]), UUID(str(keys[1])))
                )
        elif sort == "code":
            order = [Supplier.code, Supplier.id]
            if keys is not None:
                query = query.where(
                    tuple_(Supplier.code, Supplier.id) > tuple_(str(keys[0]), UUID(str(keys[1])))
                )
        else:
            order = [Supplier.updated_at.desc(), Supplier.id.desc()]
            if keys is not None:
                query = query.where(
                    tuple_(Supplier.updated_at, Supplier.id)
                    < tuple_(datetime.fromisoformat(str(keys[0])), UUID(str(keys[1])))
                )
    except (IndexError, ValueError, TypeError) as exc:
        raise BadRequest(_INVALID_CURSOR) from exc
    with actor_tx(actor) as db:
        rows = db.execute(query.order_by(*order).limit(limit + 1)).all()
    page = rows[:limit]
    items = [supplier_read(r.Supplier) for r in page]
    next_cursor = None
    if len(rows) > limit and page:
        last = page[-1]
        marker: Any = (
            last.name_key
            if sort == "name"
            else last.Supplier.code
            if sort == "code"
            else last.Supplier.updated_at.isoformat()
        )
        next_cursor = encode_cursor([marker, str(last.Supplier.id)], sort)
    return Page[SupplierRead](items=items, next_cursor=next_cursor)


def get_supplier(actor: Actor, supplier_id: UUID) -> SupplierRead:
    with actor_tx(actor) as db:
        row = db.execute(
            select(Supplier).where(
                Supplier.tenant_id == actor.tenant_id, Supplier.id == supplier_id
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFound("We could not find that supplier.")
        return supplier_read(row)


# ----------------------------------------------------------------------------------------------- contacts
def list_contacts(
    actor: Actor, supplier_id: UUID, limit: int = DEFAULT_LIMIT, cursor: str | None = None
) -> Page[ContactRead]:
    after = _id_cursor(cursor, "id")
    with actor_tx(actor) as db:
        exists = db.scalar(
            select(Supplier.id).where(
                Supplier.tenant_id == actor.tenant_id, Supplier.id == supplier_id
            )
        )
        if exists is None:
            raise NotFound("We could not find that supplier.")
        query = select(SupplierContact).where(
            SupplierContact.tenant_id == actor.tenant_id, SupplierContact.supplier_id == supplier_id
        )
        if after is not None:
            query = query.where(SupplierContact.id > after)
        rows = db.scalars(query.order_by(SupplierContact.id).limit(limit + 1)).all()
        page = rows[:limit]
        consents = consents_of(
            db, actor.tenant_id, [c.id for c in page]
        )  # one query for the whole page
        items = [contact_read(c, consents[c.id]) for c in page]
    return Page[ContactRead](
        items=items, next_cursor=_next([c.id for c in page], len(rows) > limit, "id")
    )


def get_contact(actor: Actor, contact_id: UUID) -> ContactRead:
    with actor_tx(actor) as db:
        row = db.execute(
            select(SupplierContact).where(
                SupplierContact.tenant_id == actor.tenant_id, SupplierContact.id == contact_id
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFound("We could not find that contact.")
        return contact_read(row, consents_of(db, actor.tenant_id, [row.id])[row.id])


# ----------------------------------------------------------------------------------------------- catalogue
def list_customers(
    actor: Actor, *, archived: bool, limit: int, cursor: str | None
) -> Page[CustomerRead]:
    after = _id_cursor(cursor, "id")
    query = select(Customer).where(Customer.tenant_id == actor.tenant_id)
    if not archived:
        query = query.where(Customer.archived_at.is_(None))
    if after is not None:
        query = query.where(Customer.id > after)
    with actor_tx(actor) as db:
        rows = db.scalars(query.order_by(Customer.id).limit(limit + 1)).all()
    page = rows[:limit]
    return Page[CustomerRead](
        items=[customer_read(r) for r in page],
        next_cursor=_next([r.id for r in page], len(rows) > limit, "id"),
    )


def list_parts(
    actor: Actor, *, archived: bool, sort: str, limit: int, cursor: str | None
) -> Page[PartRead]:
    if sort != "part_no":
        raise BadRequest("Sort by: part_no.")
    keys = decode_cursor(cursor, sort) if cursor is not None else None
    query = select(Part).where(Part.tenant_id == actor.tenant_id)
    if not archived:
        query = query.where(Part.archived_at.is_(None))
    if keys is not None:
        try:
            query = query.where(
                tuple_(Part.part_no, Part.id) > tuple_(str(keys[0]), UUID(str(keys[1])))
            )
        except (IndexError, ValueError) as exc:
            raise BadRequest(_INVALID_CURSOR) from exc
    with actor_tx(actor) as db:
        rows = db.scalars(query.order_by(Part.part_no, Part.id).limit(limit + 1)).all()
    page = rows[:limit]
    next_cursor = (
        encode_cursor([page[-1].part_no, str(page[-1].id)], sort)
        if len(rows) > limit and page
        else None
    )
    return Page[PartRead](items=[part_read(r) for r in page], next_cursor=next_cursor)


def get_part(actor: Actor, part_id: UUID) -> PartRead:
    with actor_tx(actor) as db:
        row = db.execute(
            select(Part).where(Part.tenant_id == actor.tenant_id, Part.id == part_id)
        ).scalar_one_or_none()
        if row is None:
            raise NotFound("We could not find that part.")
        return part_read(row)


def list_customer_parts(
    actor: Actor,
    *,
    customer_id: UUID | None,
    part_id: UUID | None,
    archived: bool,
    limit: int,
    cursor: str | None,
) -> Page[CustomerPartRead]:
    after = _id_cursor(cursor, "id")
    query = select(CustomerPart).where(CustomerPart.tenant_id == actor.tenant_id)
    if customer_id is not None:
        query = query.where(CustomerPart.customer_id == customer_id)
    if part_id is not None:
        query = query.where(CustomerPart.part_id == part_id)
    if not archived:
        query = query.where(CustomerPart.archived_at.is_(None))
    if after is not None:
        query = query.where(CustomerPart.id > after)
    with actor_tx(actor) as db:
        rows = db.scalars(query.order_by(CustomerPart.id).limit(limit + 1)).all()
    page = rows[:limit]
    return Page[CustomerPartRead](
        items=[customer_part_read(r) for r in page],
        next_cursor=_next([r.id for r in page], len(rows) > limit, "id"),
    )


def list_supplier_parts(
    actor: Actor,
    *,
    supplier_id: UUID | None,
    part_id: UUID | None,
    archived: bool,
    limit: int,
    cursor: str | None,
) -> Page[SupplierPartRead]:
    """A picker: archived links and links to archived parts are hidden unless `archived` is true."""
    after = _id_cursor(cursor, "id")
    query = (
        select(SupplierPart)
        .join(Part, (Part.tenant_id == SupplierPart.tenant_id) & (Part.id == SupplierPart.part_id))
        .where(SupplierPart.tenant_id == actor.tenant_id)
    )
    if supplier_id is not None:
        query = query.where(SupplierPart.supplier_id == supplier_id)
    if part_id is not None:
        query = query.where(SupplierPart.part_id == part_id)
    if not archived:
        query = query.where(SupplierPart.archived_at.is_(None), Part.archived_at.is_(None))
    if after is not None:
        query = query.where(SupplierPart.id > after)
    with actor_tx(actor) as db:
        rows = db.scalars(query.order_by(SupplierPart.id).limit(limit + 1)).all()
    page = rows[:limit]
    return Page[SupplierPartRead](
        items=[supplier_part_read(r) for r in page],
        next_cursor=_next([r.id for r in page], len(rows) > limit, "id"),
    )
