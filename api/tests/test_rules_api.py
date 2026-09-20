"""Rule history and the supersede operation."""
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.models import FormularyRule

from .factories import make_medicine, make_rule


def url(code: str = "MED00001") -> str:
    return f"/api/v1/medicines/{code}/rules"


def new_rule(start: str = "2026-03-01", per_dispense: int = 10, per_30_days: int = 20) -> dict:
    return {
        "effective_from": start,
        "max_quantity_per_dispense": per_dispense,
        "max_quantity_per_30_days": per_30_days,
        "requires_authorisation": False,
    }


def test_history_is_ordered_and_marks_what_is_in_force(client, session):
    medicine = make_medicine(session)
    make_rule(session, medicine, start="2020-01-01", end="2024-01-01")
    current = make_rule(session, medicine, start="2024-01-01")

    body = client.get(url()).json()

    assert [r["effective_from"] for r in body["items"]] == ["2020-01-01", "2024-01-01"]
    assert body["in_force_rule_id"] == current.id


def test_unknown_medicine_is_404(client, session):
    assert client.get(url("NOPE")).status_code == 404


def test_superseding_closes_the_rule_in_force(client, session):
    medicine = make_medicine(session)
    old = make_rule(session, medicine, start="2020-01-01")

    response = client.post(url(), json=new_rule(start="2026-03-01"))

    assert response.status_code == 201
    assert response.json()["effective_to"] is None
    session.refresh(old)
    assert old.effective_to == date(2026, 3, 1)  # exclusive: no overlap on the boundary day


def test_a_new_rule_stops_where_the_next_one_starts(client, session):
    medicine = make_medicine(session)
    make_rule(session, medicine, start="2020-01-01", end="2027-01-01")
    make_rule(session, medicine, start="2027-01-01")

    response = client.post(url(), json=new_rule(start="2026-03-01"))

    assert response.json()["effective_to"] == "2027-01-01"


def test_a_new_rule_inherits_the_end_of_the_rule_it_supersedes(client, session):
    """The superseded rule ended on 1 June and nothing followed it. Extending the new
    rule past that date would silently give a rule to dispenses that fell in the gap."""
    medicine = make_medicine(session)
    make_rule(session, medicine, start="2026-01-01", end="2026-06-01")

    response = client.post(url(), json=new_rule(start="2026-03-01"))

    assert response.json()["effective_to"] == "2026-06-01"


def test_a_second_rule_starting_on_the_same_day_is_a_conflict(client, session):
    medicine = make_medicine(session)
    make_rule(session, medicine, start="2026-03-01")

    response = client.post(url(), json=new_rule(start="2026-03-01"))

    assert response.status_code == 409
    assert response.json()["code"] == "RULE_START_CONFLICT"
    assert len(session.scalars(FormularyRule.__table__.select()).all()) == 1


def test_rules_may_start_in_the_past_and_history_is_untouched(client, session):
    medicine = make_medicine(session)
    old = make_rule(session, medicine, start="2020-01-01", per_dispense=100)

    assert client.post(url(), json=new_rule(start="2021-01-01", per_dispense=1)).status_code == 201

    session.refresh(old)
    assert old.max_quantity_per_dispense == 100  # never edited in place


def test_the_database_refuses_overlapping_periods(session):
    """The guarantee is the EXCLUDE constraint, not the service: writing an overlap
    directly must still fail."""
    medicine = make_medicine(session)
    make_rule(session, medicine, start="2026-01-01", end="2026-06-01")

    with pytest.raises(IntegrityError) as exc:
        session.execute(
            text(
                "INSERT INTO formulary_rule (medicine_id, effective_from, effective_to,"
                " max_quantity_per_dispense, max_quantity_per_30_days, requires_authorisation)"
                " VALUES (:m, '2026-03-01', '2026-09-01', 10, 20, false)"
            ),
            {"m": medicine.id},
        )
    assert "ex_rule_no_overlap" in str(exc.value)
    session.rollback()
