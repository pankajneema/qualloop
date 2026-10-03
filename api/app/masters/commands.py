"""Masters commands (API.md 3.2): suppliers, contacts and consent, customers, parts and their links.

Each handler locks the aggregate, validates, mutates; `run_command` writes the audit row and the outbox event in the same
transaction. Supplier `status*` columns are written ONLY by `_change_status` (INV-MST-03)."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core import hooks, ratelimit
from app.core.audit.writer import record_activity
from app.core.commands.base import Command, CommandContext, Outcome, register
from app.core.errors import (
    Conflict,
    Forbidden,
    InvalidTransition,
    NotFound,
    RateLimited,
    ValidationFailed,
    field_error,
)
from app.core.ids import new_id
from app.core.jobs import enqueue
from app.core.permissions import QUALITY, Permission
from app.core.platform.schemas import Strict
from app.masters import channels, otp
from app.masters.job_refs import SEND_CONTACT_CODE
from app.masters.models import (
    ContactConsent,
    Customer,
    CustomerPart,
    Part,
    Supplier,
    SupplierContact,
    SupplierPart,
)
from app.masters.readmodels import (
    consents_of,
    contact_audit,
    contact_read,
    customer_part_read,
    customer_read,
    part_read,
    supplier_part_read,
    supplier_read,
)
from app.masters.schemas import (
    ConsentInput,
    ContactCreateInput,
    ContactDisableInput,
    ContactIdInput,
    ContactRead,
    ContactReplaceInput,
    ContactUpdateInput,
    CustomerArchiveInput,
    CustomerCreate,
    CustomerPartArchiveInput,
    CustomerPartCreate,
    CustomerPartRead,
    CustomerRead,
    CustomerUpdateInput,
    PartArchiveInput,
    PartCreate,
    PartRead,
    PartUpdateInput,
    StatusChangeInput,
    SupplierArchiveInput,
    SupplierCreate,
    SupplierPartArchiveInput,
    SupplierPartCreate,
    SupplierPartRead,
    SupplierPartUpdateInput,
    SupplierRead,
    SupplierUpdateInput,
    VerifyConfirmInput,
    VerifyStartInput,
)

NOTHING_TO_CHANGE = ValidationFailed(
    "There is nothing to change.", errors=[field_error("body", "empty", "Send at least one field.")]
)


class CodeRequested(Strict):
    """Answer of `verify/start`: the code goes out through a worker, never in this response."""

    channel: str
    expires_in_seconds: int


# ------------------------------------------------------------------------------------------------ helpers
def _lock[M](ctx: CommandContext, model: type[M], object_id: UUID, what: str) -> M:
    row = ctx.session.execute(
        select(model)
        .where(model.tenant_id == ctx.actor.tenant_id, model.id == object_id)  # type: ignore[attr-defined]
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise NotFound(f"We could not find that {what}.")
    return row


def _find[M](session: Session, model: type[M], tenant_id: UUID, object_id: UUID, what: str) -> M:
    row = session.execute(
        select(model).where(model.tenant_id == tenant_id, model.id == object_id)  # type: ignore[attr-defined]
    ).scalar_one_or_none()
    if row is None:
        raise NotFound(f"We could not find that {what}.")
    return row


def _changes(requested: dict[str, Any], *, clearable: set[str]) -> dict[str, Any]:
    """Fields to write: an explicit null clears only nullable columns; for required columns it means "leave as is"."""
    return {k: v for k, v in requested.items() if v is not None or k in clearable}


def _duplicate(field: str, message: str) -> Conflict:
    return Conflict(message, errors=[field_error(field, "duplicate", message)])


def _save(session: Session, row: Any) -> None:
    session.flush()
    session.refresh(row)


def _touch(ctx: CommandContext, model: Any, object_id: UUID) -> None:
    """Write the row (audit columns) so its transaction id matches the audit row, even when nothing else changed."""
    ctx.session.execute(
        update(model)
        .where(model.tenant_id == ctx.actor.tenant_id, model.id == object_id)
        .values(updated_by=ctx.actor.user_id, updated_at=func.now())
    )
    ctx.session.expire_all()


def _dump(read: Any) -> dict[str, Any]:
    result: dict[str, Any] = read.model_dump(mode="json")
    return result


# ---------------------------------------------------------------------------------------------- suppliers
def _create_supplier(ctx: CommandContext, data: SupplierCreate) -> Outcome[SupplierRead]:
    session, actor = ctx.session, ctx.actor
    # A-116: without can_approve only `approved` may be chosen; otherwise create would bypass the +CA status gate.
    # SPEC-GAP: A-116
    if data.status != "approved" and not actor.can_approve:
        raise Forbidden("You do not have permission to do this.")
    if session.scalar(
        select(Supplier.id).where(Supplier.tenant_id == actor.tenant_id, Supplier.code == data.code)
    ):
        raise _duplicate("code", "A supplier with this code already exists.")
    supplier = Supplier(
        id=new_id(),
        tenant_id=actor.tenant_id,
        code=data.code,
        name=data.name,
        gstin=data.gstin,
        city=data.city,
        state=data.state,
        category=data.category,
        status=data.status,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    session.add(supplier)
    _save(session, supplier)
    read = supplier_read(supplier)
    return Outcome(
        response=read,
        object_type="supplier",
        object_id=supplier.id,
        action="supplier.create",
        event_type="SUPPLIER_CREATED",
        after=_dump(read),
        payload={"supplier_id": str(supplier.id)},
        status_code=201,
    )


def _update_supplier(ctx: CommandContext, data: SupplierUpdateInput) -> Outcome[SupplierRead]:
    session, actor = ctx.session, ctx.actor
    supplier = _lock(ctx, Supplier, data.supplier_id, "supplier")
    before = supplier_read(supplier)
    changes = _changes(
        data.body.model_dump(exclude_unset=True), clearable={"gstin", "city", "state"}
    )
    if not changes:
        raise NOTHING_TO_CHANGE
    new_code = changes.get("code")
    if new_code is not None and new_code != supplier.code:
        taken = session.scalar(
            select(Supplier.id).where(
                Supplier.tenant_id == actor.tenant_id,
                Supplier.code == new_code,
                Supplier.id != supplier.id,
            )
        )
        if taken is not None:
            raise _duplicate("code", "A supplier with this code already exists.")
    for name, value in changes.items():
        setattr(supplier, name, value)
    supplier.updated_by = actor.user_id
    _save(session, supplier)
    after = supplier_read(supplier)
    return Outcome(
        response=after,
        object_type="supplier",
        object_id=supplier.id,
        action="supplier.update",
        event_type="SUPPLIER_UPDATED",
        before=_dump(before),
        after=_dump(after),
        payload={"supplier_id": str(supplier.id)},
    )


def _archive_supplier(ctx: CommandContext, data: SupplierArchiveInput) -> Outcome[SupplierRead]:
    supplier = _lock(ctx, Supplier, data.supplier_id, "supplier")
    if supplier.archived_at is not None:
        raise InvalidTransition("This supplier is already archived.")
    before = supplier_read(supplier)
    supplier.archived_at = datetime.now(UTC)
    supplier.updated_by = ctx.actor.user_id
    _save(ctx.session, supplier)
    after = supplier_read(supplier)
    return Outcome(
        response=after,
        object_type="supplier",
        object_id=supplier.id,
        action="supplier.archive",
        event_type="SUPPLIER_ARCHIVED",
        before=_dump(before),
        after=_dump(after),
        reason=data.body.reason,
        payload={"supplier_id": str(supplier.id)},
    )


def _change_status(ctx: CommandContext, data: StatusChangeInput) -> Outcome[SupplierRead]:
    """The only writer of `suppliers.status*` (INV-MST-03). Q + can_approve, reason required (blueprint 15.6)."""
    actor = ctx.actor
    supplier = _lock(ctx, Supplier, data.supplier_id, "supplier")
    if supplier.status == data.body.status:
        raise InvalidTransition(
            f"This supplier is already {supplier.status}. Choose a different status."
        )
    before = supplier_read(supplier)
    supplier.status = data.body.status
    supplier.status_reason = data.body.reason
    supplier.status_changed_by = actor.user_id
    supplier.status_changed_at = datetime.now(UTC)
    supplier.updated_by = actor.user_id
    _save(ctx.session, supplier)
    after = supplier_read(supplier)
    return Outcome(
        response=after,
        object_type="supplier",
        object_id=supplier.id,
        action="supplier.change_status",
        event_type="SUPPLIER_STATUS_CHANGED",
        before=_dump(before),
        after=_dump(after),
        reason=data.body.reason,
        payload={
            "supplier_id": str(supplier.id),
            "from_status": before.status,
            "to_status": after.status,
        },
    )


# ----------------------------------------------------------------------------------------------- contacts
def _contact_view(ctx: CommandContext, contact: SupplierContact) -> ContactRead:
    consents = consents_of(ctx.session, ctx.actor.tenant_id, [contact.id])[contact.id]
    return contact_read(contact, consents)


def _require_active(contact: SupplierContact) -> None:
    if not contact.active:
        raise InvalidTransition("This contact is disabled. Add or replace a contact instead.")


def _create_contact(ctx: CommandContext, data: ContactCreateInput) -> Outcome[ContactRead]:
    actor, body = ctx.actor, data.body
    _find(ctx.session, Supplier, actor.tenant_id, data.supplier_id, "supplier")
    contact = SupplierContact(
        id=new_id(),
        tenant_id=actor.tenant_id,
        supplier_id=data.supplier_id,
        name=body.name,
        role=body.role,
        mobile=body.mobile,
        email=body.email,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    ctx.session.add(contact)
    _save(ctx.session, contact)
    read = _contact_view(ctx, contact)
    return Outcome(
        response=read,
        object_type="contact",
        object_id=contact.id,
        action="contact.create",
        event_type="CONTACT_CREATED",
        after=contact_audit(read),
        payload={"contact_id": str(contact.id), "supplier_id": str(contact.supplier_id)},
        status_code=201,
    )


def _update_contact(ctx: CommandContext, data: ContactUpdateInput) -> Outcome[ContactRead]:
    contact = _lock(ctx, SupplierContact, data.contact_id, "contact")
    _require_active(contact)
    before = _contact_view(ctx, contact)
    changes = _changes(
        data.body.model_dump(exclude_unset=True), clearable={"role", "mobile", "email"}
    )
    if not changes:
        raise NOTHING_TO_CHANGE
    for name, value in changes.items():
        setattr(contact, name, value)
    # Phone reassignment protection (blueprint 8 C2): a different number or address is unverified again.
    if contact.mobile != before.mobile:
        contact.verified_mobile_at = None
    if contact.email != before.email:
        contact.verified_email_at = None
    if contact.mobile is None and contact.email is None:
        raise ValidationFailed(
            "A contact needs a mobile number or an email address.",
            errors=[field_error("mobile", "required", "Keep a mobile number or an email address.")],
        )
    contact.updated_by = ctx.actor.user_id
    _save(ctx.session, contact)
    after = _contact_view(ctx, contact)
    return Outcome(
        response=after,
        object_type="contact",
        object_id=contact.id,
        action="contact.update",
        event_type="CONTACT_UPDATED",
        before=contact_audit(before),
        after=contact_audit(after),
        payload={"contact_id": str(contact.id)},
    )


def _set_quality_contact(ctx: CommandContext, data: ContactIdInput) -> Outcome[ContactRead]:
    session, actor = ctx.session, ctx.actor
    contact = _lock(ctx, SupplierContact, data.contact_id, "contact")
    _require_active(contact)
    _lock(
        ctx, Supplier, contact.supplier_id, "supplier"
    )  # serialise "exactly one quality contact per supplier"
    before = _contact_view(ctx, contact)
    previous = session.scalars(
        select(SupplierContact)
        .where(
            SupplierContact.tenant_id == actor.tenant_id,
            SupplierContact.supplier_id == contact.supplier_id,
            SupplierContact.is_quality_contact.is_(True),
            SupplierContact.id != contact.id,
        )
        .with_for_update()
    ).all()
    for other in previous:
        other_before = _contact_view(ctx, other)
        other.is_quality_contact = False
        other.updated_by = actor.user_id
        _save(session, other)
        record_activity(
            session,
            actor=actor,
            object_type="contact",
            object_id=other.id,
            action="contact.unset_quality_contact",
            before=contact_audit(other_before),
            after=contact_audit(_contact_view(ctx, other)),
        )
    contact.is_quality_contact = True
    contact.updated_by = actor.user_id
    _save(session, contact)
    after = _contact_view(ctx, contact)
    return Outcome(
        response=after,
        object_type="contact",
        object_id=contact.id,
        action="contact.set_quality_contact",
        event_type="CONTACT_QUALITY_SET",
        before=contact_audit(before),
        after=contact_audit(after),
        payload={"contact_id": str(contact.id), "supplier_id": str(contact.supplier_id)},
    )


def _disable_contact(ctx: CommandContext, data: ContactDisableInput) -> Outcome[ContactRead]:
    contact = _lock(ctx, SupplierContact, data.contact_id, "contact")
    if not contact.active:
        raise InvalidTransition("This contact is already disabled.")
    before = _contact_view(ctx, contact)
    contact.active = False
    contact.disabled_at = datetime.now(UTC)
    contact.disabled_reason = data.body.reason
    contact.updated_by = ctx.actor.user_id
    _save(ctx.session, contact)
    # INV-MST-05: the contact's access ends in the same transaction (P05 subscribes links and sessions).
    hooks.publish("contact.revoke_access", ctx.session, contact.id)
    after = _contact_view(ctx, contact)
    return Outcome(
        response=after,
        object_type="contact",
        object_id=contact.id,
        action="contact.disable",
        event_type="CONTACT_DISABLED",
        before=contact_audit(before),
        after=contact_audit(after),
        reason=data.body.reason,
        payload={"contact_id": str(contact.id)},
    )


def _replace_contact(ctx: CommandContext, data: ContactReplaceInput) -> Outcome[ContactRead]:
    """Create the new contact, disable the old one and link them (INV-MST-04). The old row and its history stay."""
    session, actor, body = ctx.session, ctx.actor, data.body
    old = _lock(ctx, SupplierContact, data.contact_id, "contact")
    if not old.active:
        raise InvalidTransition("This contact is already disabled or replaced.")
    before = _contact_view(ctx, old)
    new = SupplierContact(
        id=new_id(),
        tenant_id=actor.tenant_id,
        supplier_id=old.supplier_id,
        name=body.name,
        role=body.role,
        mobile=body.mobile,
        email=body.email,
        is_quality_contact=old.is_quality_contact,  # the quality-contact role passes to the replacement
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    session.add(new)
    session.flush()
    old.active = False
    old.is_quality_contact = False
    old.disabled_at = datetime.now(UTC)
    old.disabled_reason = body.reason
    old.replaced_by_contact_id = new.id
    old.updated_by = actor.user_id
    _save(session, old)
    session.refresh(new)
    hooks.publish("contact.revoke_access", session, old.id)
    hooks.publish("contact.replaced", session, old.id, new.id)  # P05: SCAR reassignment
    old_after = _contact_view(ctx, old)
    new_read = _contact_view(ctx, new)
    return Outcome(
        response=new_read,
        object_type="contact",
        object_id=old.id,
        action="contact.replace",
        event_type="CONTACT_REPLACED",
        before=contact_audit(before),
        after={**contact_audit(old_after), "replacement": contact_audit(new_read)},
        reason=body.reason,
        payload={"contact_id": str(old.id), "replacement_contact_id": str(new.id)},
        status_code=201,
    )


def _verify_start(ctx: CommandContext, data: VerifyStartInput) -> Outcome[CodeRequested]:
    """Ask for a verification code (A-78). Validates and counts the send; a worker delivers it (INV-PLT-11)."""
    channel = data.body.channel
    contact = _lock(ctx, SupplierContact, data.contact_id, "contact")
    _require_active(contact)
    destination = contact.email if channel == "email" else contact.mobile
    if not destination:
        raise ValidationFailed(
            f"This contact has no {channel} on file.",
            errors=[field_error("channel", "no_destination", f"Add a {channel} first.")],
        )
    if channel == "mobile" and not channels.mobile_channel_available():
        # SPEC-GAP: A-110 - real mobile delivery arrives in P05.
        raise ValidationFailed(
            "Mobile verification is not available yet. Verify by email instead.",
            errors=[field_error("channel", "unavailable", "Choose email.")],
        )
    wait = ratelimit.reserve(
        [otp.send_counter_key(contact.id)],
        limit=otp.SEND_LIMIT,
        window_seconds=otp.SEND_WINDOW_SECONDS,
    )
    if wait:
        raise RateLimited(wait, "Too many codes were sent to this contact. Try again later.")
    tenant_id, contact_id, nonce = str(ctx.actor.tenant_id), str(contact.id), str(new_id())
    response = CodeRequested(channel=channel, expires_in_seconds=otp.TTL_SECONDS)

    def send_code() -> None:  # runs after the commit: a rolled-back request never sends anything
        enqueue(
            SEND_CONTACT_CODE,
            tenant_id=tenant_id,
            contact_id=contact_id,
            channel=channel,
            request_nonce=nonce,
        )

    return Outcome(
        response=response,
        object_type="contact",
        object_id=contact.id,
        action="contact.request_code",
        event_type="CONTACT_CODE_REQUESTED",
        after={"channel": channel},
        payload={"contact_id": contact_id, "channel": channel},
        status_code=202,
        after_commit=(send_code,),
    )


_BAD_CODE = "That code is not right or has expired. Ask for a new code."


def _verify_confirm(ctx: CommandContext, data: VerifyConfirmInput) -> Outcome[ContactRead]:
    channel = data.body.channel
    contact = _lock(ctx, SupplierContact, data.contact_id, "contact")
    _require_active(contact)
    invalid = ValidationFailed(_BAD_CODE, errors=[field_error("code", "invalid", _BAD_CODE)])
    if not otp.attempt(contact.id, channel, data.body.code):
        raise invalid  # wrong, expired, burnt and never-requested codes look the same
    before = _contact_view(ctx, contact)
    now = datetime.now(UTC)
    if channel == "email":
        contact.verified_email_at = now
    else:
        contact.verified_mobile_at = now
    contact.updated_by = ctx.actor.user_id
    _save(ctx.session, contact)
    after = _contact_view(ctx, contact)
    return Outcome(
        response=after,
        object_type="contact",
        object_id=contact.id,
        action="contact.verify_confirm",
        event_type="CONTACT_VERIFIED",
        before=contact_audit(before),
        after=contact_audit(after),
        payload={"contact_id": str(contact.id), "channel": channel},
    )


def _record_consent(ctx: CommandContext, data: ConsentInput) -> Outcome[ContactRead]:
    session, actor, body = ctx.session, ctx.actor, data.body
    contact = _lock(ctx, SupplierContact, data.contact_id, "contact")
    _require_active(contact)
    before = _contact_view(ctx, contact)
    latest = session.scalars(
        select(ContactConsent)
        .where(
            ContactConsent.tenant_id == actor.tenant_id,
            ContactConsent.contact_id == contact.id,
            ContactConsent.channel == body.channel,
        )
        .order_by(ContactConsent.consent_at.desc(), ContactConsent.id.desc())
        .with_for_update()
    ).first()
    now = datetime.now(UTC)
    if body.status == "opted_in":
        if latest is not None and latest.status == "opted_in":
            raise Conflict(
                "This contact has already opted in on this channel.",
                errors=[field_error("status", "already_opted_in", "Nothing to record.")],
            )
        session.add(
            ContactConsent(
                id=new_id(),
                tenant_id=actor.tenant_id,
                contact_id=contact.id,
                channel=body.channel,
                status="opted_in",
                source=body.source,
                consent_at=now,
                created_by=actor.user_id,
                updated_by=actor.user_id,
            )
        )
    elif latest is not None and latest.status == "opted_in":
        latest.status = "opted_out"
        latest.revoked_at = now
        latest.updated_by = actor.user_id
    elif latest is not None:
        raise Conflict(
            "This contact has already opted out on this channel.",
            errors=[field_error("status", "already_opted_out", "Nothing to record.")],
        )
    else:
        session.add(
            ContactConsent(
                id=new_id(),
                tenant_id=actor.tenant_id,
                contact_id=contact.id,
                channel=body.channel,
                status="opted_out",
                source=body.source,
                consent_at=now,
                revoked_at=now,
                created_by=actor.user_id,
                updated_by=actor.user_id,
            )
        )
    session.flush()
    _touch(ctx, SupplierContact, contact.id)
    contact = _find(session, SupplierContact, actor.tenant_id, contact.id, "contact")
    after = _contact_view(ctx, contact)
    return Outcome(
        response=after,
        object_type="contact",
        object_id=contact.id,
        action="contact.consent",
        event_type="CONSENT_RECORDED",
        before=contact_audit(before),
        after=contact_audit(after),
        payload={"contact_id": str(contact.id), "channel": body.channel, "status": body.status},
    )


# ------------------------------------------------------------------------------------------- customers
def _create_customer(ctx: CommandContext, data: CustomerCreate) -> Outcome[CustomerRead]:
    actor = ctx.actor
    if ctx.session.scalar(
        select(Customer.id).where(Customer.tenant_id == actor.tenant_id, Customer.code == data.code)
    ):
        raise _duplicate("code", "A customer with this code already exists.")
    customer = Customer(
        id=new_id(),
        tenant_id=actor.tenant_id,
        name=data.name,
        code=data.code,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    ctx.session.add(customer)
    _save(ctx.session, customer)
    read = customer_read(customer)
    return Outcome(
        response=read,
        object_type="customer",
        object_id=customer.id,
        action="customer.create",
        event_type="CUSTOMER_CREATED",
        after=_dump(read),
        payload={"customer_id": str(customer.id)},
        status_code=201,
    )


def _update_customer(ctx: CommandContext, data: CustomerUpdateInput) -> Outcome[CustomerRead]:
    customer = _lock(ctx, Customer, data.customer_id, "customer")
    before = customer_read(customer)
    changes = _changes(data.body.model_dump(exclude_unset=True), clearable=set())
    if not changes:
        raise NOTHING_TO_CHANGE
    for name, value in changes.items():
        setattr(customer, name, value)
    customer.updated_by = ctx.actor.user_id
    _save(ctx.session, customer)
    after = customer_read(customer)
    return Outcome(
        response=after,
        object_type="customer",
        object_id=customer.id,
        action="customer.update",
        event_type="CUSTOMER_UPDATED",
        before=_dump(before),
        after=_dump(after),
        payload={"customer_id": str(customer.id)},
    )


def _archive_customer(ctx: CommandContext, data: CustomerArchiveInput) -> Outcome[CustomerRead]:
    customer = _lock(ctx, Customer, data.customer_id, "customer")
    if customer.archived_at is not None:
        raise InvalidTransition("This customer is already archived.")
    before = customer_read(customer)
    customer.archived_at = datetime.now(UTC)
    customer.updated_by = ctx.actor.user_id
    _save(ctx.session, customer)
    after = customer_read(customer)
    return Outcome(
        response=after,
        object_type="customer",
        object_id=customer.id,
        action="customer.archive",
        event_type="CUSTOMER_ARCHIVED",
        before=_dump(before),
        after=_dump(after),
        reason=data.body.reason,
        payload={"customer_id": str(customer.id)},
    )


# ----------------------------------------------------------------------------------------------- parts
def _create_part(ctx: CommandContext, data: PartCreate) -> Outcome[PartRead]:
    actor = ctx.actor
    if ctx.session.scalar(
        select(Part.id).where(Part.tenant_id == actor.tenant_id, Part.part_no == data.part_no)
    ):
        raise _duplicate("part_no", "A part with this part number already exists.")
    part = Part(
        id=new_id(),
        tenant_id=actor.tenant_id,
        part_no=data.part_no,
        name=data.name,
        category=data.category,
        current_revision=data.current_revision,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    ctx.session.add(part)
    _save(ctx.session, part)
    read = part_read(part)
    return Outcome(
        response=read,
        object_type="part",
        object_id=part.id,
        action="part.create",
        event_type="PART_CREATED",
        after=_dump(read),
        payload={"part_id": str(part.id)},
        status_code=201,
    )


def _update_part(ctx: CommandContext, data: PartUpdateInput) -> Outcome[PartRead]:
    part = _lock(ctx, Part, data.part_id, "part")
    before = part_read(part)
    changes = _changes(
        data.body.model_dump(exclude_unset=True), clearable={"category", "current_revision"}
    )
    if not changes:
        raise NOTHING_TO_CHANGE
    for name, value in changes.items():
        setattr(part, name, value)
    part.updated_by = ctx.actor.user_id
    _save(ctx.session, part)
    after = part_read(part)
    return Outcome(
        response=after,
        object_type="part",
        object_id=part.id,
        action="part.update",
        event_type="PART_UPDATED",
        before=_dump(before),
        after=_dump(after),
        payload={"part_id": str(part.id)},
    )


def _archive_part(ctx: CommandContext, data: PartArchiveInput) -> Outcome[PartRead]:
    part = _lock(ctx, Part, data.part_id, "part")
    if part.archived_at is not None:
        raise InvalidTransition("This part is already archived.")
    before = part_read(part)
    part.archived_at = datetime.now(UTC)
    part.updated_by = ctx.actor.user_id
    _save(ctx.session, part)
    after = part_read(part)
    return Outcome(
        response=after,
        object_type="part",
        object_id=part.id,
        action="part.archive",
        event_type="PART_ARCHIVED",
        before=_dump(before),
        after=_dump(after),
        reason=data.body.reason,
        payload={"part_id": str(part.id)},
    )


# ------------------------------------------------------------------------------------------ customer_parts
def _live(row: Any, what: str) -> None:
    if row.archived_at is not None:
        raise Conflict(f"This {what} is archived and cannot be linked.")


def _link_customer_part(ctx: CommandContext, data: CustomerPartCreate) -> Outcome[CustomerPartRead]:
    session, actor = ctx.session, ctx.actor
    customer = _find(session, Customer, actor.tenant_id, data.customer_id, "customer")
    part = _find(session, Part, actor.tenant_id, data.part_id, "part")
    _live(customer, "customer")
    _live(part, "part")
    existing = session.execute(
        select(CustomerPart)
        .where(
            CustomerPart.tenant_id == actor.tenant_id,
            CustomerPart.customer_id == customer.id,
            CustomerPart.part_id == part.id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if existing is not None:
        if existing.archived_at is None:
            raise Conflict("This customer and part are already linked.")
        # A-119: an archived pair comes back as the same row. SPEC-GAP: A-119
        before = customer_part_read(existing)
        existing.archived_at = None
        if data.customer_part_no is not None:
            existing.customer_part_no = data.customer_part_no
        existing.updated_by = actor.user_id
        _save(session, existing)
        after = customer_part_read(existing)
        return Outcome(
            response=after,
            object_type="customer_part",
            object_id=existing.id,
            action="customer_part.restore",
            event_type="CUSTOMER_PART_LINKED",
            before=_dump(before),
            after=_dump(after),
            payload={"customer_part_id": str(existing.id)},
        )
    link = CustomerPart(
        id=new_id(),
        tenant_id=actor.tenant_id,
        customer_id=customer.id,
        part_id=part.id,
        customer_part_no=data.customer_part_no,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    session.add(link)
    _save(session, link)
    read = customer_part_read(link)
    return Outcome(
        response=read,
        object_type="customer_part",
        object_id=link.id,
        action="customer_part.create",
        event_type="CUSTOMER_PART_LINKED",
        after=_dump(read),
        payload={"customer_part_id": str(link.id)},
        status_code=201,
    )


def _archive_customer_part(
    ctx: CommandContext, data: CustomerPartArchiveInput
) -> Outcome[CustomerPartRead]:
    link = _lock(ctx, CustomerPart, data.link_id, "link")
    if link.archived_at is not None:
        raise InvalidTransition("This link is already archived.")
    before = customer_part_read(link)
    link.archived_at = datetime.now(UTC)
    link.updated_by = ctx.actor.user_id
    _save(ctx.session, link)
    after = customer_part_read(link)
    return Outcome(
        response=after,
        object_type="customer_part",
        object_id=link.id,
        action="customer_part.archive",
        event_type="CUSTOMER_PART_ARCHIVED",
        before=_dump(before),
        after=_dump(after),
        payload={"customer_part_id": str(link.id)},
    )


# ------------------------------------------------------------------------------------------ supplier_parts
def _link_supplier_part(ctx: CommandContext, data: SupplierPartCreate) -> Outcome[SupplierPartRead]:
    session, actor = ctx.session, ctx.actor
    supplier = _find(session, Supplier, actor.tenant_id, data.supplier_id, "supplier")
    part = _find(session, Part, actor.tenant_id, data.part_id, "part")
    _live(supplier, "supplier")
    _live(part, "part")
    existing = session.execute(
        select(SupplierPart)
        .where(
            SupplierPart.tenant_id == actor.tenant_id,
            SupplierPart.supplier_id == supplier.id,
            SupplierPart.part_id == part.id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if existing is not None:
        if existing.archived_at is None:
            raise Conflict("This supplier and part are already linked.")
        before = supplier_part_read(existing)  # A-119: restore the archived pair. SPEC-GAP: A-119
        existing.archived_at = None
        existing.status = "active"  # A-117
        if data.supplier_part_no is not None:
            existing.supplier_part_no = data.supplier_part_no
        if data.ppm_target is not None:
            existing.ppm_target = data.ppm_target
        existing.updated_by = actor.user_id
        _save(session, existing)
        after = supplier_part_read(existing)
        return Outcome(
            response=after,
            object_type="supplier_part",
            object_id=existing.id,
            action="supplier_part.restore",
            event_type="SUPPLIER_PART_LINKED",
            before=_dump(before),
            after=_dump(after),
            payload={"supplier_part_id": str(existing.id)},
        )
    link = SupplierPart(
        id=new_id(),
        tenant_id=actor.tenant_id,
        supplier_id=supplier.id,
        part_id=part.id,
        supplier_part_no=data.supplier_part_no,
        status="active",  # A-117 (SPEC-GAP: A-117): created active; unlinking is archive
        ppm_target=data.ppm_target,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    session.add(link)
    _save(session, link)
    read = supplier_part_read(link)
    return Outcome(
        response=read,
        object_type="supplier_part",
        object_id=link.id,
        action="supplier_part.create",
        event_type="SUPPLIER_PART_LINKED",
        after=_dump(read),
        payload={"supplier_part_id": str(link.id)},
        status_code=201,
    )


def _update_supplier_part(
    ctx: CommandContext, data: SupplierPartUpdateInput
) -> Outcome[SupplierPartRead]:
    link = _lock(ctx, SupplierPart, data.link_id, "link")
    before = supplier_part_read(link)
    changes = _changes(
        data.body.model_dump(exclude_unset=True), clearable={"supplier_part_no", "ppm_target"}
    )
    if not changes:
        raise NOTHING_TO_CHANGE
    for name, value in changes.items():
        setattr(link, name, value)
    link.updated_by = ctx.actor.user_id
    _save(ctx.session, link)
    after = supplier_part_read(link)
    return Outcome(
        response=after,
        object_type="supplier_part",
        object_id=link.id,
        action="supplier_part.update",
        event_type="SUPPLIER_PART_UPDATED",
        before=_dump(before),
        after=_dump(after),
        payload={"supplier_part_id": str(link.id)},
    )


def _archive_supplier_part(
    ctx: CommandContext, data: SupplierPartArchiveInput
) -> Outcome[SupplierPartRead]:
    link = _lock(ctx, SupplierPart, data.link_id, "link")
    if link.archived_at is not None:
        raise InvalidTransition("This link is already archived.")
    before = supplier_part_read(link)
    link.archived_at = datetime.now(UTC)
    link.updated_by = ctx.actor.user_id
    _save(ctx.session, link)
    after = supplier_part_read(link)
    return Outcome(
        response=after,
        object_type="supplier_part",
        object_id=link.id,
        action="supplier_part.archive",
        event_type="SUPPLIER_PART_ARCHIVED",
        before=_dump(before),
        after=_dump(after),
        payload={"supplier_part_id": str(link.id)},
    )


# ------------------------------------------------------------------------------------------------ registry
APPROVER = Permission(QUALITY.roles, requires_can_approve=True)


def _cmd(name: str, path: str, handler: Any, permission: Permission = QUALITY) -> Command[Any, Any]:
    return register(Command(name, path, permission, handler))


CREATE_SUPPLIER = _cmd("suppliers.create", "/suppliers", _create_supplier)
UPDATE_SUPPLIER = _cmd("suppliers.update", "/suppliers/{id}/update", _update_supplier)
ARCHIVE_SUPPLIER = _cmd("suppliers.archive", "/suppliers/{id}/archive", _archive_supplier)
CHANGE_STATUS = _cmd(
    "suppliers.change_status", "/suppliers/{id}/change-status", _change_status, APPROVER
)
CREATE_CONTACT = _cmd("contacts.create", "/suppliers/{id}/contacts", _create_contact)
UPDATE_CONTACT = _cmd("contacts.update", "/contacts/{id}/update", _update_contact)
SET_QUALITY_CONTACT = _cmd(
    "contacts.set_quality_contact", "/contacts/{id}/set-quality-contact", _set_quality_contact
)
VERIFY_START = _cmd("contacts.verify_start", "/contacts/{id}/verify/start", _verify_start)
VERIFY_CONFIRM = _cmd("contacts.verify_confirm", "/contacts/{id}/verify/confirm", _verify_confirm)
DISABLE_CONTACT = _cmd("contacts.disable", "/contacts/{id}/disable", _disable_contact)
REPLACE_CONTACT = _cmd("contacts.replace", "/contacts/{id}/replace", _replace_contact)
RECORD_CONSENT = _cmd("contacts.consents", "/contacts/{id}/consents", _record_consent)
CREATE_CUSTOMER = _cmd("customers.create", "/customers", _create_customer)
UPDATE_CUSTOMER = _cmd("customers.update", "/customers/{id}/update", _update_customer)
ARCHIVE_CUSTOMER = _cmd("customers.archive", "/customers/{id}/archive", _archive_customer)
CREATE_PART = _cmd("parts.create", "/parts", _create_part)
UPDATE_PART = _cmd("parts.update", "/parts/{id}/update", _update_part)
ARCHIVE_PART = _cmd("parts.archive", "/parts/{id}/archive", _archive_part)
LINK_CUSTOMER_PART = _cmd("customer_parts.create", "/customer-parts", _link_customer_part)
ARCHIVE_CUSTOMER_PART = _cmd(
    "customer_parts.archive", "/customer-parts/{id}/archive", _archive_customer_part
)
LINK_SUPPLIER_PART = _cmd("supplier_parts.create", "/supplier-parts", _link_supplier_part)
UPDATE_SUPPLIER_PART = _cmd(
    "supplier_parts.update", "/supplier-parts/{id}/update", _update_supplier_part
)
ARCHIVE_SUPPLIER_PART = _cmd(
    "supplier_parts.archive", "/supplier-parts/{id}/archive", _archive_supplier_part
)
