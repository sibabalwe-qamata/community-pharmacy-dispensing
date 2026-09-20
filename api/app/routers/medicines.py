from fastapi import APIRouter, Query

from ..dependencies import CursorDep, PageSizeDep, SessionDep
from ..schemas.common import Page
from ..schemas.medicine import MedicineDetail, MedicineSummary
from ..schemas.rule import RuleRead
from ..services.catalogue import get_medicine_with_current_rule, search_medicines

router = APIRouter(prefix="/medicines", tags=["medicines"])


@router.get("", response_model=Page[MedicineSummary])
def list_medicines(
    db: SessionDep,
    limit: PageSizeDep,
    cursor: CursorDep = None,
    q: str | None = Query(None, description="Partial, case-insensitive match against name or code"),
) -> Page[MedicineSummary]:
    rows, next_cursor = search_medicines(db, q, limit, cursor)
    return Page(
        items=[MedicineSummary.model_validate(row) for row in rows],
        page_size=limit,
        next_cursor=next_cursor,
    )


@router.get("/{code}", response_model=MedicineDetail)
def get_medicine(code: str, db: SessionDep) -> MedicineDetail:
    medicine, current_rule = get_medicine_with_current_rule(db, code)
    return MedicineDetail(
        **MedicineSummary.model_validate(medicine).model_dump(),
        current_rule=RuleRead.model_validate(current_rule) if current_rule is not None else None,
    )
