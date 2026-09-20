"""Querying for the medicine catalogue. Routers stay thin; this module owns the SQL."""
from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.orm import Session

from ..core.business_time import business_date, utcnow
from ..core.pagination import decode_cursor, encode_cursor, take_page
from ..core.problems import NotFound, UnprocessableRequest
from ..db.models import FormularyRule, Medicine
from ..domain.rule_engine import RulePeriod, rule_in_force


def _escape_like(value: str) -> str:
    """Escape LIKE metacharacters so user input in `q` is matched literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_medicines(db: Session, q: str | None, limit: int, cursor: str | None) -> tuple[list[Medicine], str | None]:
    """Search medicines by name/code and keyset-paginate on (name, id).

    Keyset (not offset) pagination is used because the catalogue is large and
    concurrently written; offset pagination would skip/duplicate rows as data changes
    and degrades on large offsets, while a keyset seeks straight off the (name, id) index.
    """
    stmt = select(Medicine)

    if q:
        # lower(col) LIKE lower(pattern) so Postgres can use the trigram indexes on
        # lower(name)/lower(code); a plain ILIKE would not match those expression indexes.
        pattern = f"%{_escape_like(q)}%"
        stmt = stmt.where(
            or_(
                func.lower(Medicine.name).like(func.lower(pattern), escape="\\"),
                func.lower(Medicine.code).like(func.lower(pattern), escape="\\"),
            )
        )

    decoded = decode_cursor(cursor)
    if decoded is not None:
        try:
            cursor_name = str(decoded["name"])
            cursor_id = int(decoded["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise UnprocessableRequest("INVALID_CURSOR", "The cursor is not valid.") from exc
        # Tuple comparison walks the composite (name, id) index directly, unlike an
        # OFFSET, and stays correct even as rows are inserted between pages.
        stmt = stmt.where(tuple_(Medicine.name, Medicine.id) > tuple_(cursor_name, cursor_id))

    stmt = stmt.order_by(Medicine.name.asc(), Medicine.id.asc()).limit(limit + 1)
    rows = db.execute(stmt).scalars().all()

    page_rows, has_more = take_page(rows, limit)
    next_cursor = encode_cursor({"name": page_rows[-1].name, "id": page_rows[-1].id}) if has_more and page_rows else None
    return page_rows, next_cursor


def get_medicine_with_current_rule(db: Session, code: str) -> tuple[Medicine, RulePeriod | None]:
    """Look up one medicine and the rule in force for it today, in the business timezone."""
    medicine = db.execute(select(Medicine).where(Medicine.code == code)).scalar_one_or_none()
    if medicine is None:
        raise NotFound("Medicine", code)

    rules = db.execute(select(FormularyRule).where(FormularyRule.medicine_id == medicine.id)).scalars().all()
    periods = [
        RulePeriod(
            id=r.id,
            effective_from=r.effective_from,
            effective_to=r.effective_to,
            max_quantity_per_dispense=r.max_quantity_per_dispense,
            max_quantity_per_30_days=r.max_quantity_per_30_days,
            requires_authorisation=r.requires_authorisation,
        )
        for r in rules
    ]
    current = rule_in_force(periods, business_date(utcnow()))
    return medicine, current
