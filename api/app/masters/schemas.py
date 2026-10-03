"""Request and read models of the masters module (strict types; commands reject unknown fields)."""

from datetime import datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    StrictInt,
    StringConstraints,
    model_validator,
)

from app.core.platform.schemas import Email, Mobile, Name, Page, Reason, Strict

__all__ = [
    "ContactRead",
    "CustomerPartRead",
    "CustomerRead",
    "Page",
    "PartRead",
    "SupplierPartRead",
    "SupplierRead",
]

Category = Literal["raw_material", "bought_out", "job_work", "service"]
SupplierStatus = Literal["approved", "approved_with_action_plan", "on_watch", "blocked", "inactive"]
SUPPLIER_STATUSES = (
    "approved",
    "approved_with_action_plan",
    "on_watch",
    "blocked",
    "inactive",
)
CATEGORIES = ("raw_material", "bought_out", "job_work", "service")

Gstin = Annotated[str, StringConstraints(pattern=r"^[0-9A-Z]{15}$")]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
PpmTarget = Annotated[StrictInt, Field(gt=0, le=2_147_483_647)]


def _blank_to_none(value: Any) -> Any:
    return None if isinstance(value, str) and not value.strip() else value


OptText = Annotated[ShortText | None, BeforeValidator(_blank_to_none)]


# ----------------------------------------------------------------------------------------------- suppliers
class SupplierCreate(Strict):
    code: Code
    name: Name
    category: Category
    status: SupplierStatus
    gstin: Gstin | None = None
    city: OptText = None
    state: OptText = None


class SupplierUpdate(Strict):
    code: Code | None = None
    name: Name | None = None
    category: Category | None = None
    gstin: Gstin | None = None
    city: OptText = None
    state: OptText = None


class SupplierUpdateInput(BaseModel):
    supplier_id: UUID
    body: SupplierUpdate


class ReasonBody(Strict):
    reason: Reason


class SupplierArchiveInput(BaseModel):
    supplier_id: UUID
    body: ReasonBody


class StatusChange(Strict):
    status: SupplierStatus
    reason: Reason


class StatusChangeInput(BaseModel):
    supplier_id: UUID
    body: StatusChange


class SupplierRead(BaseModel):
    id: UUID
    code: str
    name: str
    gstin: str | None
    city: str | None
    state: str | None
    category: str
    status: str
    status_reason: str | None
    status_changed_by: UUID | None
    status_changed_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------------------------------------ contacts
class ContactCreate(Strict):
    name: Name
    role: OptText = None
    mobile: Mobile | None = None
    email: Email | None = None

    @model_validator(mode="after")
    def _has_destination(self) -> Self:
        if self.mobile is None and self.email is None:
            raise ValueError("give a mobile number or an email address")
        return self


class ContactCreateInput(BaseModel):
    supplier_id: UUID
    body: ContactCreate


class ContactUpdate(Strict):
    name: Name | None = None
    role: OptText = None
    mobile: Mobile | None = None
    email: Email | None = None


class ContactUpdateInput(BaseModel):
    contact_id: UUID
    body: ContactUpdate


class Empty(Strict):
    pass


class ContactIdInput(BaseModel):
    """Pipeline input of commands that take only the path id (and an empty body)."""

    contact_id: UUID
    body: Empty


class ContactDisableInput(BaseModel):
    contact_id: UUID
    body: ReasonBody


class ContactReplace(Strict):
    reason: Reason
    name: Name
    role: OptText = None
    mobile: Mobile | None = None
    email: Email | None = None

    @model_validator(mode="after")
    def _has_destination(self) -> Self:
        if self.mobile is None and self.email is None:
            raise ValueError("give a mobile number or an email address")
        return self


class ContactReplaceInput(BaseModel):
    contact_id: UUID
    body: ContactReplace


class VerifyStart(Strict):
    channel: Literal["mobile", "email"]


class VerifyStartInput(BaseModel):
    contact_id: UUID
    body: VerifyStart


class VerifyConfirm(Strict):
    channel: Literal["mobile", "email"]
    code: Annotated[str, StringConstraints(pattern=r"^[0-9]{6}$")]


class VerifyConfirmInput(BaseModel):
    contact_id: UUID
    body: VerifyConfirm


class ConsentBody(Strict):
    channel: Literal["whatsapp", "email", "sms"]
    status: Literal["opted_in", "opted_out"]
    source: Literal["otp_verification", "import", "manual", "stop_reply", "supplier_link"]


class ConsentInput(BaseModel):
    contact_id: UUID
    body: ConsentBody


class ConsentRead(BaseModel):
    id: UUID
    channel: str
    status: str
    source: str
    consent_at: datetime
    revoked_at: datetime | None


class ContactRead(BaseModel):
    id: UUID
    supplier_id: UUID
    name: str
    role: str | None
    mobile: str | None
    email: str | None
    is_quality_contact: bool
    verified_mobile_at: datetime | None
    verified_email_at: datetime | None
    active: bool
    disabled_at: datetime | None
    disabled_reason: str | None
    replaced_by_contact_id: UUID | None
    needs_reverification: bool
    consents: list[ConsentRead]


# ------------------------------------------------------------------------------------------------ catalogue
class CustomerCreate(Strict):
    name: Name
    code: Code


class CustomerUpdate(Strict):
    name: Name | None = None


class CustomerUpdateInput(BaseModel):
    customer_id: UUID
    body: CustomerUpdate


class CustomerArchiveInput(BaseModel):
    customer_id: UUID
    body: ReasonBody


class CustomerRead(BaseModel):
    id: UUID
    name: str
    code: str
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PartCreate(Strict):
    part_no: Code
    name: Name
    category: OptText = None
    current_revision: OptText = None


class PartUpdate(Strict):
    name: Name | None = None
    category: OptText = None
    current_revision: OptText = None


class PartUpdateInput(BaseModel):
    part_id: UUID
    body: PartUpdate


class PartArchiveInput(BaseModel):
    part_id: UUID
    body: ReasonBody


class PartRead(BaseModel):
    id: UUID
    part_no: str
    name: str
    category: str | None
    current_revision: str | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CustomerPartCreate(Strict):
    customer_id: UUID
    part_id: UUID
    customer_part_no: OptText = None


class CustomerPartArchiveInput(BaseModel):
    link_id: UUID
    body: Empty


class CustomerPartRead(BaseModel):
    id: UUID
    customer_id: UUID
    part_id: UUID
    customer_part_no: str | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SupplierPartCreate(Strict):
    supplier_id: UUID
    part_id: UUID
    supplier_part_no: OptText = None
    ppm_target: PpmTarget | None = None


class SupplierPartUpdate(Strict):
    supplier_part_no: OptText = None
    ppm_target: PpmTarget | None = None


class SupplierPartUpdateInput(BaseModel):
    link_id: UUID
    body: SupplierPartUpdate


class SupplierPartArchiveInput(BaseModel):
    link_id: UUID
    body: Empty


class SupplierPartRead(BaseModel):
    id: UUID
    supplier_id: UUID
    part_id: UUID
    supplier_part_no: str | None
    status: str
    ppm_target: int | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
