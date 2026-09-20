"""Shared dependencies, per the FastAPI bigger-applications layout."""
from typing import Annotated

from fastapi import Depends, Header, Query
from sqlalchemy.orm import Session

from .core.config import Settings, get_settings
from .db.session import get_session

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def page_size(
    limit: Annotated[int, Query(ge=1, le=100, description="Rows per page")] = 25,
) -> int:
    return limit


PageSizeDep = Annotated[int, Depends(page_size)]
CursorDep = Annotated[str | None, Query(description="Opaque cursor from the previous page")]


def idempotency_key(
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> str:
    """POST /dispenses requires a client-supplied key; it is carried in a header so the
    request body stays a pure description of the dispense."""
    return idempotency_key


IdempotencyKeyDep = Annotated[str, Depends(idempotency_key)]


def pharmacist_ref(
    x_pharmacist_ref: Annotated[str | None, Header(alias="X-Pharmacist-Ref")] = None,
) -> str:
    """Stub identity. Auth is out of scope for the brief; this is only for the attempt log."""
    return x_pharmacist_ref or "anonymous"


PharmacistDep = Annotated[str, Depends(pharmacist_ref)]
