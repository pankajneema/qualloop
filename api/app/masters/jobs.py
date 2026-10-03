"""Masters jobs (queue `notifications`): deliver a contact verification code. No database transaction is open during
Redis or SMTP I/O (ADR-006)."""

from uuid import UUID

import structlog
from sqlalchemy import select

from app.core.db import tenant_tx
from app.core.jobs import job
from app.masters import channels, otp
from app.masters.job_refs import SEND_CONTACT_CODE
from app.masters.models import SupplierContact

log = structlog.get_logger("masters.jobs")


@job(SEND_CONTACT_CODE, own_transaction=True)
def send_contact_code(tenant_id: str, contact_id: str, channel: str, request_nonce: str) -> None:
    """Send the code of one `verify/start` request to the contact's email or mobile number on file."""
    cid = UUID(contact_id)
    with tenant_tx(UUID(tenant_id), "system") as session:
        row = session.execute(
            select(SupplierContact.mobile, SupplierContact.email, SupplierContact.active).where(
                SupplierContact.tenant_id == UUID(tenant_id), SupplierContact.id == cid
            )
        ).first()
    destination = (
        None if row is None or not row.active else (row.email if channel == "email" else row.mobile)
    )
    if not destination:
        log.info("contact_code_skipped", contact_id=contact_id, channel=channel)
        return
    code = otp.code_for_request(request_nonce, cid, channel)
    if not otp.store(cid, channel, code, request_nonce):
        log.info("contact_code_superseded", contact_id=contact_id)
        return
    channels.send_code(
        channel=channel,
        to=destination,
        code=code,
        ttl_minutes=otp.TTL_SECONDS // 60,
        idempotency_key=f"contact-code:{request_nonce}:{channel}",
    )
