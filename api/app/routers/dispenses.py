"""Dispense endpoints — the delicate part of the system.

The algorithm (idempotency, locking, rule evaluation) lives entirely in
`app.services.dispensing`; this router only translates HTTP in and out of it.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..core.problems import CONTENT_TYPE
from ..dependencies import CursorDep, IdempotencyKeyDep, PageSizeDep, SessionDep
from ..schemas.common import Page
from ..schemas.dispense import DispenseCreate, DispenseRead
from ..services import dispensing

router = APIRouter(prefix="/dispenses", tags=["dispenses"])


@router.post("", status_code=201)
def create_dispense(
    payload: DispenseCreate,
    db: SessionDep,
    idempotency_key: IdempotencyKeyDep,
) -> JSONResponse:
    """Idempotent: a repeated Idempotency-Key with the same body replays the stored
    response (its original status, accepted or rejected) instead of dispensing again.
    """
    outcome = dispensing.create_dispense(db, payload, idempotency_key)
    media_type = CONTENT_TYPE if outcome.status >= 400 else "application/json"
    return JSONResponse(outcome.body, status_code=outcome.status, media_type=media_type)


@router.get("", response_model=Page[DispenseRead])
def list_dispenses(
    db: SessionDep,
    limit: PageSizeDep,
    cursor: CursorDep = None,
    patient_ref: str | None = None,
    medicine_code: str | None = None,
) -> Page[DispenseRead]:
    items, next_cursor = dispensing.list_dispenses(db, patient_ref, medicine_code, limit, cursor)
    return Page(items=items, page_size=limit, next_cursor=next_cursor)
