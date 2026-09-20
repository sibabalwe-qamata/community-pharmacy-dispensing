"""Row builders for the database-backed tests."""
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.core.business_time import BUSINESS_TZ
from app.db.models import FormularyRule, Medicine


def sast(text: str) -> datetime:
    """'2026-03-05 10:00' in Johannesburg, as a UTC instant."""
    return datetime.fromisoformat(text).replace(tzinfo=BUSINESS_TZ).astimezone(timezone.utc)


def make_medicine(
    session: Session,
    code: str = "MED00001",
    *,
    name: str = "Testazole 500",
    is_active: bool = True,
) -> Medicine:
    medicine = Medicine(
        code=code,
        name=name,
        form="tablet",
        strength_value=500,
        strength_unit="mg",
        is_active=is_active,
    )
    session.add(medicine)
    session.commit()
    return medicine


def make_rule(
    session: Session,
    medicine: Medicine,
    *,
    start: str = "2020-01-01",
    end: str | None = None,
    per_dispense: int = 100,
    per_30_days: int = 100,
    auth: bool = False,
) -> FormularyRule:
    rule = FormularyRule(
        medicine_id=medicine.id,
        effective_from=date.fromisoformat(start),
        effective_to=date.fromisoformat(end) if end else None,
        max_quantity_per_dispense=per_dispense,
        max_quantity_per_30_days=per_30_days,
        requires_authorisation=auth,
    )
    session.add(rule)
    session.commit()
    return rule


def dispense_body(
    code: str = "MED00001",
    patient_ref: str = "PT-1",
    quantity: int = 10,
    when: str = "2026-03-10 10:00",
    auth: str | None = None,
) -> dict:
    return {
        "medicine_code": code,
        "patient_ref": patient_ref,
        "quantity": quantity,
        "dispensed_at": sast(when).isoformat(),
        "authorisation_ref": auth,
    }
