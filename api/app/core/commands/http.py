"""HTTP glue for commands: run one and turn the result into a response."""

from fastapi import Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.commands.base import Command, run_command
from app.core.permissions import Actor

IDEMPOTENCY_HEADER = "Idempotency-Key"


def idempotency_key_header(
    idempotency_key: str | None = Header(
        default=None, alias=IDEMPOTENCY_HEADER, min_length=1, max_length=255
    ),
) -> str | None:
    """`Idempotency-Key` request header (API.md 1.6): optional on most commands, required on money/capture commands."""
    return idempotency_key


def execute[In: BaseModel, Out: BaseModel](
    command: Command[In, Out],
    data: In,
    *,
    request: Request,
    actor: Actor,
    idempotency_key: str | None,
) -> JSONResponse:
    result = run_command(
        command,
        data,
        actor=actor,
        idempotency_key=idempotency_key,
        endpoint=f"{request.method} {request.url.path}",
    )
    response = JSONResponse(result.body, status_code=result.status_code)
    if result.replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return response
