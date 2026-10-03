"""Request and response models of the auth endpoints."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(_Body):
    email: Annotated[str, StringConstraints(max_length=254)]
    password: Annotated[str, StringConstraints(max_length=256)]


class LoginResponse(BaseModel):
    email: str
    name: str
    role: str
    can_approve: bool


class PasswordResetRequest(_Body):
    email: Annotated[str, StringConstraints(max_length=254)]


class PasswordResetConfirm(_Body):
    email: Annotated[str, StringConstraints(max_length=254)]
    otp: Annotated[str, StringConstraints(pattern=r"^[0-9]{6}$")]
    # SPEC-GAP: A-96 - the blueprint names no password policy; conservative minimum length, generous maximum (argon2 cost).
    new_password: Annotated[str, StringConstraints(min_length=12, max_length=128)]


class Accepted(BaseModel):
    status: Literal["accepted"] = "accepted"
