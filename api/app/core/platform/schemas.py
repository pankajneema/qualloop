"""Request and response models for the platform commands and queries (strict types, no coercion)."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

_EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
_MOBILE = r"^\+[1-9][0-9]{7,14}$"  # E.164 (A-90)
_PLANT_CODE = r"^[A-Z0-9]{1,10}$"  # A-90; embedded in NCR numbers, so no separators

Role = Literal["admin", "quality", "viewer"]
Email = Annotated[str, StringConstraints(strip_whitespace=True, max_length=254, pattern=_EMAIL)]
Mobile = Annotated[str, StringConstraints(pattern=_MOBILE)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class Strict(BaseModel):
    """Command bodies reject unknown fields (a client cannot smuggle `tenant_id`, `active`, `status`, ...)."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------------------------------- users
class UserCreate(Strict):
    email: Email
    name: Name
    role: Role
    can_approve: StrictBool = False
    plant_ids: list[UUID] = Field(default_factory=list, max_length=200)
    mobile: Mobile | None = None


class UserUpdate(Strict):
    name: Name | None = None
    mobile: Mobile | None = None
    role: Role | None = None
    can_approve: StrictBool | None = None
    plant_ids: list[UUID] | None = Field(default=None, max_length=200)
    reason: Reason | None = None


class UserDeactivate(Strict):
    reason: Reason


class UserUpdateInput(BaseModel):
    """Pipeline input of `users.update`: the path id plus the validated body (both feed the idempotency hash)."""

    user_id: UUID
    body: UserUpdate


class UserDeactivateInput(BaseModel):
    user_id: UUID
    body: UserDeactivate


class UserRead(BaseModel):
    id: UUID
    email: str
    name: str
    mobile: str | None
    role: Role
    can_approve: bool
    plant_ids: list[UUID]
    active: bool


# --------------------------------------------------------------------------------------------------- plants
class PlantCreate(Strict):
    name: Name
    code: Annotated[str, StringConstraints(pattern=_PLANT_CODE)]
    address: Annotated[str, StringConstraints(max_length=1000)] | None = None
    timezone: str = "Asia/Kolkata"


class PlantUpdate(Strict):
    name: Name | None = None
    address: Annotated[str, StringConstraints(max_length=1000)] | None = None
    timezone: str | None = None
    reason: Reason | None = None


class PlantUpdateInput(BaseModel):
    plant_id: UUID
    body: PlantUpdate


class PlantRead(BaseModel):
    id: UUID
    name: str
    code: str
    address: str | None
    timezone: str


# ------------------------------------------------------------------------------------------ tenant settings
PositiveInt = Annotated[StrictInt, Field(gt=0)]


class SlaWindow(Strict):
    containment: PositiveInt | None = None
    final: PositiveInt


class SlaHours(Strict):
    """Calendar hours per severity (blueprint section 9 C6)."""

    critical: SlaWindow = Field(default_factory=lambda: SlaWindow(containment=24, final=7 * 24))
    major: SlaWindow = Field(default_factory=lambda: SlaWindow(containment=48, final=10 * 24))
    minor: SlaWindow = Field(default_factory=lambda: SlaWindow(containment=None, final=15 * 24))


class MinSample(Strict):
    """Minimum sample sizes before a metric is shown as measured (blueprint 12.1)."""

    receipts: PositiveInt = 5
    units: PositiveInt = 1000
    scars_due: PositiveInt = 1


class ScoreWeights(Strict):
    """Score component weights in percent (blueprint 14.1)."""

    quality: Annotated[StrictInt, Field(ge=0, le=100)] = 50
    response: Annotated[StrictInt, Field(ge=0, le=100)] = 20
    repeat: Annotated[StrictInt, Field(ge=0, le=100)] = 15
    documents: Annotated[StrictInt, Field(ge=0, le=100)] = 15

    @model_validator(mode="after")
    def _sum_is_100(self) -> Self:
        # SPEC-GAP: A-95 - blueprint 14.1 lists weights that total 100 but does not say the total is enforced.
        if self.quality + self.response + self.repeat + self.documents != 100:
            raise ValueError("score weights must add up to 100")
        return self


class TenantSettings(Strict):
    """`tenants.settings` (DATA_MODEL 1.1). Missing keys take the blueprint defaults."""

    sla_hours: SlaHours = Field(default_factory=SlaHours)
    default_ppm_target: PositiveInt = 500  # blueprint 14.4 demo value
    min_sample: MinSample = Field(default_factory=MinSample)
    score_weights: ScoreWeights = Field(default_factory=ScoreWeights)


class SettingsUpdate(Strict):
    settings: TenantSettings
    reason: Reason


class SettingsRead(BaseModel):
    settings: TenantSettings


# ------------------------------------------------------------------------------------------------- queries
class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None


class MePlant(BaseModel):
    id: UUID
    name: str
    code: str
    timezone: str


class Me(BaseModel):
    id: UUID
    email: str
    name: str
    role: Role
    can_approve: bool
    plants: list[MePlant]
