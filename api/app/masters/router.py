"""HTTP routes of the masters module: commands are POST, queries are GET (API.md 1.1, 3.2, 5)."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse

from app.core.auth.deps import require
from app.core.commands.http import execute, idempotency_key_header
from app.core.pagination import DEFAULT_LIMIT, CursorParam, LimitParam
from app.core.permissions import ANY_USER, QUALITY, Actor
from app.core.routing import api_router
from app.masters import commands, queries
from app.masters.commands import APPROVER, CodeRequested
from app.masters.schemas import (
    Category,
    ConsentBody,
    ConsentInput,
    ContactCreate,
    ContactCreateInput,
    ContactDisableInput,
    ContactIdInput,
    ContactRead,
    ContactReplace,
    ContactReplaceInput,
    ContactUpdate,
    ContactUpdateInput,
    CustomerArchiveInput,
    CustomerCreate,
    CustomerPartArchiveInput,
    CustomerPartCreate,
    CustomerPartRead,
    CustomerRead,
    CustomerUpdate,
    CustomerUpdateInput,
    Empty,
    Page,
    PartArchiveInput,
    PartCreate,
    PartRead,
    PartUpdate,
    PartUpdateInput,
    ReasonBody,
    StatusChange,
    StatusChangeInput,
    SupplierArchiveInput,
    SupplierCreate,
    SupplierPartArchiveInput,
    SupplierPartCreate,
    SupplierPartRead,
    SupplierPartUpdate,
    SupplierPartUpdateInput,
    SupplierRead,
    SupplierStatus,
    SupplierUpdate,
    SupplierUpdateInput,
    VerifyConfirm,
    VerifyConfirmInput,
    VerifyStart,
    VerifyStartInput,
)

router = api_router(tags=["masters"])

QualityActor = Annotated[Actor, Depends(require(QUALITY))]
ApproverActor = Annotated[Actor, Depends(require(APPROVER))]
Reader = Annotated[Actor, Depends(require(ANY_USER, command=False))]
IdempotencyKey = Annotated[str | None, Depends(idempotency_key_header)]


# ----------------------------------------------------------------------------------------------- suppliers
@router.post("/suppliers", response_model=SupplierRead, status_code=201)
def create_supplier(
    body: SupplierCreate, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.CREATE_SUPPLIER, body, request=request, actor=actor, idempotency_key=key
    )


@router.post("/suppliers/{id}/update", response_model=SupplierRead)
def update_supplier(
    id: UUID, body: SupplierUpdate, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.UPDATE_SUPPLIER,
        SupplierUpdateInput(supplier_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.post("/suppliers/{id}/archive", response_model=SupplierRead)
def archive_supplier(
    id: UUID, body: ReasonBody, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.ARCHIVE_SUPPLIER,
        SupplierArchiveInput(supplier_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.post("/suppliers/{id}/change-status", response_model=SupplierRead)
def change_status(
    id: UUID, body: StatusChange, request: Request, actor: ApproverActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.CHANGE_STATUS,
        StatusChangeInput(supplier_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.get("/suppliers", response_model=Page[SupplierRead])
def list_suppliers(
    actor: Reader,
    q: Annotated[str | None, Query(max_length=200)] = None,
    status: SupplierStatus | None = None,
    category: Category | None = None,
    archived: bool = False,
    sort: str = "name",
    limit: LimitParam = DEFAULT_LIMIT,
    cursor: CursorParam = None,
) -> Page[SupplierRead]:
    return queries.list_suppliers(
        actor,
        q=q,
        status=status,
        category=category,
        archived=archived,
        sort=sort,
        limit=limit,
        cursor=cursor,
    )


@router.get("/suppliers/{id}", response_model=SupplierRead)
def get_supplier(id: UUID, actor: Reader) -> SupplierRead:
    return queries.get_supplier(actor, id)


# ------------------------------------------------------------------------------------------------ contacts
@router.post("/suppliers/{id}/contacts", response_model=ContactRead, status_code=201)
def create_contact(
    id: UUID, body: ContactCreate, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.CREATE_CONTACT,
        ContactCreateInput(supplier_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.post("/contacts/{id}/update", response_model=ContactRead)
def update_contact(
    id: UUID, body: ContactUpdate, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.UPDATE_CONTACT,
        ContactUpdateInput(contact_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.post("/contacts/{id}/set-quality-contact", response_model=ContactRead)
def set_quality_contact(
    id: UUID, body: Empty, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.SET_QUALITY_CONTACT,
        ContactIdInput(contact_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.post("/contacts/{id}/verify/start", response_model=CodeRequested, status_code=202)
def verify_start(
    id: UUID, body: VerifyStart, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.VERIFY_START,
        VerifyStartInput(contact_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.post("/contacts/{id}/verify/confirm", response_model=ContactRead)
def verify_confirm(
    id: UUID, body: VerifyConfirm, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.VERIFY_CONFIRM,
        VerifyConfirmInput(contact_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.post("/contacts/{id}/disable", response_model=ContactRead)
def disable_contact(
    id: UUID, body: ReasonBody, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.DISABLE_CONTACT,
        ContactDisableInput(contact_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.post("/contacts/{id}/replace", response_model=ContactRead, status_code=201)
def replace_contact(
    id: UUID, body: ContactReplace, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.REPLACE_CONTACT,
        ContactReplaceInput(contact_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.post("/contacts/{id}/consents", response_model=ContactRead)
def record_consent(
    id: UUID, body: ConsentBody, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.RECORD_CONSENT,
        ConsentInput(contact_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.get("/suppliers/{id}/contacts", response_model=Page[ContactRead])
def list_contacts(
    id: UUID, actor: Reader, limit: LimitParam = DEFAULT_LIMIT, cursor: CursorParam = None
) -> Page[ContactRead]:
    return queries.list_contacts(actor, id, limit, cursor)


@router.get("/contacts/{id}", response_model=ContactRead)
def get_contact(id: UUID, actor: Reader) -> ContactRead:
    return queries.get_contact(actor, id)


# ------------------------------------------------------------------------------------------------ customers
@router.post("/customers", response_model=CustomerRead, status_code=201)
def create_customer(
    body: CustomerCreate, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.CREATE_CUSTOMER, body, request=request, actor=actor, idempotency_key=key
    )


@router.post("/customers/{id}/update", response_model=CustomerRead)
def update_customer(
    id: UUID, body: CustomerUpdate, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.UPDATE_CUSTOMER,
        CustomerUpdateInput(customer_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.post("/customers/{id}/archive", response_model=CustomerRead)
def archive_customer(
    id: UUID, body: ReasonBody, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.ARCHIVE_CUSTOMER,
        CustomerArchiveInput(customer_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.get("/customers", response_model=Page[CustomerRead])
def list_customers(
    actor: Reader,
    archived: bool = False,
    limit: LimitParam = DEFAULT_LIMIT,
    cursor: CursorParam = None,
) -> Page[CustomerRead]:
    return queries.list_customers(actor, archived=archived, limit=limit, cursor=cursor)


# --------------------------------------------------------------------------------------------------- parts
@router.post("/parts", response_model=PartRead, status_code=201)
def create_part(
    body: PartCreate, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(commands.CREATE_PART, body, request=request, actor=actor, idempotency_key=key)


@router.post("/parts/{id}/update", response_model=PartRead)
def update_part(
    id: UUID, body: PartUpdate, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.UPDATE_PART,
        PartUpdateInput(part_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.post("/parts/{id}/archive", response_model=PartRead)
def archive_part(
    id: UUID, body: ReasonBody, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.ARCHIVE_PART,
        PartArchiveInput(part_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.get("/parts", response_model=Page[PartRead])
def list_parts(
    actor: Reader,
    archived: bool = False,
    sort: str = "part_no",
    limit: LimitParam = DEFAULT_LIMIT,
    cursor: CursorParam = None,
) -> Page[PartRead]:
    return queries.list_parts(actor, archived=archived, sort=sort, limit=limit, cursor=cursor)


@router.get("/parts/{id}", response_model=PartRead)
def get_part(id: UUID, actor: Reader) -> PartRead:
    return queries.get_part(actor, id)


# ------------------------------------------------------------------------------------------- customer parts
@router.post("/customer-parts", response_model=CustomerPartRead, status_code=201)
def link_customer_part(
    body: CustomerPartCreate, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.LINK_CUSTOMER_PART, body, request=request, actor=actor, idempotency_key=key
    )


@router.post("/customer-parts/{id}/archive", response_model=CustomerPartRead)
def archive_customer_part(
    id: UUID, body: Empty, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.ARCHIVE_CUSTOMER_PART,
        CustomerPartArchiveInput(link_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.get("/customer-parts", response_model=Page[CustomerPartRead])
def list_customer_parts(
    actor: Reader,
    customer_id: UUID | None = None,
    part_id: UUID | None = None,
    archived: bool = False,
    limit: LimitParam = DEFAULT_LIMIT,
    cursor: CursorParam = None,
) -> Page[CustomerPartRead]:
    return queries.list_customer_parts(
        actor,
        customer_id=customer_id,
        part_id=part_id,
        archived=archived,
        limit=limit,
        cursor=cursor,
    )


# ------------------------------------------------------------------------------------------- supplier parts
@router.post("/supplier-parts", response_model=SupplierPartRead, status_code=201)
def link_supplier_part(
    body: SupplierPartCreate, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.LINK_SUPPLIER_PART, body, request=request, actor=actor, idempotency_key=key
    )


@router.post("/supplier-parts/{id}/update", response_model=SupplierPartRead)
def update_supplier_part(
    id: UUID, body: SupplierPartUpdate, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.UPDATE_SUPPLIER_PART,
        SupplierPartUpdateInput(link_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.post("/supplier-parts/{id}/archive", response_model=SupplierPartRead)
def archive_supplier_part(
    id: UUID, body: Empty, request: Request, actor: QualityActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.ARCHIVE_SUPPLIER_PART,
        SupplierPartArchiveInput(link_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.get("/supplier-parts", response_model=Page[SupplierPartRead])
def list_supplier_parts(
    actor: Reader,
    supplier_id: UUID | None = None,
    part_id: UUID | None = None,
    archived: bool = False,
    limit: LimitParam = DEFAULT_LIMIT,
    cursor: CursorParam = None,
) -> Page[SupplierPartRead]:
    return queries.list_supplier_parts(
        actor,
        supplier_id=supplier_id,
        part_id=part_id,
        archived=archived,
        limit=limit,
        cursor=cursor,
    )
