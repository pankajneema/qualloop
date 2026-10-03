"""Job identities of the masters module (the implementations are in `jobs.py`, loaded only by the worker)."""

from app.core.jobs import JobRef

SEND_CONTACT_CODE = JobRef("masters.send_contact_code", "notifications")
