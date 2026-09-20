"""Rule engine tests. No database: the engine is pure, so the awkward cases are cheap.

Times are written in Johannesburg local time and converted, because that is how the
rules are specified.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.business_time import BUSINESS_TZ
from app.domain.rule_engine import DispenseFacts, MedicineFacts, RulePeriod, evaluate

ACTIVE = MedicineFacts(code="MED1", is_active=True)
NOW = datetime(2026, 12, 31, tzinfo=timezone.utc)


def sast(text: str) -> datetime:
    """'2026-03-05 10:00' in Johannesburg, as a UTC instant."""
    return datetime.fromisoformat(text).replace(tzinfo=BUSINESS_TZ).astimezone(timezone.utc)


def rule(
    start: str = "2026-01-01",
    end: str | None = None,
    per_dispense: int = 100,
    per_30_days: int = 100,
    auth: bool = False,
    rule_id: int = 1,
) -> RulePeriod:
    return RulePeriod(
        id=rule_id,
        effective_from=date.fromisoformat(start),
        effective_to=date.fromisoformat(end) if end else None,
        max_quantity_per_dispense=per_dispense,
        max_quantity_per_30_days=per_30_days,
        requires_authorisation=auth,
    )


def codes(violations) -> set[str]:
    return {v.code for v in violations}


def request(quantity: int = 10, when: str = "2026-03-10 10:00", auth: str | None = None) -> DispenseFacts:
    return DispenseFacts(patient_ref="P1", quantity=quantity, dispensed_at=sast(when), authorisation_ref=auth)


def test_accepts_a_dispense_within_every_limit():
    assert evaluate(request(), ACTIVE, [rule()], [], NOW) == []


def test_reports_every_violation_at_once():
    """A rejection must list all broken rules, not stop at the first."""
    violations = evaluate(
        request(quantity=500),
        MedicineFacts(code="MED1", is_active=False),
        [rule(per_dispense=10, per_30_days=20, auth=True)],
        [],
        NOW,
    )
    assert codes(violations) == {
        "MEDICINE_INACTIVE",
        "MAX_PER_DISPENSE_EXCEEDED",
        "AUTHORISATION_REQUIRED",
        "MAX_30_DAYS_EXCEEDED",
    }


def test_blank_authorisation_reference_does_not_count():
    violations = evaluate(request(auth="   "), ACTIVE, [rule(auth=True)], [], NOW)
    assert codes(violations) == {"AUTHORISATION_REQUIRED"}


def test_no_rule_in_force_short_circuits():
    violations = evaluate(request(when="2025-12-31 10:00"), ACTIVE, [rule()], [], NOW)
    assert codes(violations) == {"NO_RULE_IN_FORCE"}


def test_future_dispense_is_rejected():
    violations = evaluate(request(when="2026-03-10 10:00"), ACTIVE, [rule()], [], sast("2026-03-09 10:00"))
    assert "DISPENSED_IN_FUTURE" in codes(violations)


def test_backdating_is_allowed_when_it_fits():
    neighbours = [DispenseFacts("P1", 10, sast("2026-03-20 10:00"))]
    assert evaluate(request(quantity=10, when="2026-03-05 10:00"), ACTIVE, [rule()], neighbours, NOW) == []


def test_rule_is_chosen_by_dispensed_at_not_by_now():
    """March's dispense is judged by March's rule, even though a stricter rule is in
    force when the request arrives."""
    rules = [rule(start="2026-01-01", end="2026-06-01", per_dispense=100), rule(start="2026-06-01", per_dispense=5, rule_id=2)]
    assert evaluate(request(quantity=50, when="2026-03-10 10:00"), ACTIVE, rules, [], NOW) == []


def test_rule_change_takes_effect_at_johannesburg_midnight():
    """22:30 UTC on 14 March is already 15 March in Johannesburg."""
    rules = [
        rule(start="2026-03-01", end="2026-03-15", per_dispense=50),
        rule(start="2026-03-15", per_dispense=10, rule_id=2),
    ]
    before = DispenseFacts("P1", 20, datetime(2026, 3, 14, 21, 30, tzinfo=timezone.utc))
    after = DispenseFacts("P1", 20, datetime(2026, 3, 14, 22, 30, tzinfo=timezone.utc))

    assert evaluate(before, ACTIVE, rules, [], NOW) == []
    assert codes(evaluate(after, ACTIVE, rules, [], NOW)) == {"MAX_PER_DISPENSE_EXCEEDED"}


def test_window_covers_thirty_business_dates_inclusive():
    limit = rule(per_30_days=100)
    on_the_edge = [DispenseFacts("P1", 60, sast("2026-02-09 08:00"))]  # 30th day back from 10 March
    just_outside = [DispenseFacts("P1", 60, sast("2026-02-08 08:00"))]

    assert codes(evaluate(request(quantity=50), ACTIVE, [limit], on_the_edge, NOW)) == {"MAX_30_DAYS_EXCEEDED"}
    assert evaluate(request(quantity=50), ACTIVE, [limit], just_outside, NOW) == []


def test_backdated_dispense_may_not_breach_a_later_window():
    """60 on 10 March and 40 on 20 March use up a limit of 100. Backdating 30 to
    5 March fits its own window but would push the 20 March window to 130."""
    neighbours = [
        DispenseFacts("P1", 60, sast("2026-03-10 10:00")),
        DispenseFacts("P1", 40, sast("2026-03-20 10:00")),
    ]
    violations = evaluate(request(quantity=30, when="2026-03-05 10:00"), ACTIVE, [rule(per_30_days=100)], neighbours, NOW)
    assert codes(violations) == {"LATER_WINDOW_EXCEEDED"}
    assert violations[0].field == "dispensed_at"


def test_later_window_is_judged_by_the_rule_in_force_on_that_later_date():
    """The window ending 20 March is governed by March's rule, not by the one in force
    on the backdated dispense's own date."""
    rules = [
        rule(start="2026-01-01", end="2026-03-15", per_30_days=1000),
        rule(start="2026-03-15", per_30_days=100, rule_id=2),
    ]
    neighbours = [DispenseFacts("P1", 90, sast("2026-03-20 10:00"))]
    violations = evaluate(request(quantity=20, when="2026-03-10 10:00"), ACTIVE, rules, neighbours, NOW)
    assert codes(violations) == {"LATER_WINDOW_EXCEEDED"}


@pytest.mark.parametrize("days_after", [1, 29])
def test_later_windows_are_checked_across_the_whole_window(days_after: int):
    later = sast("2026-03-05 10:00") + timedelta(days=days_after)
    neighbours = [DispenseFacts("P1", 100, later)]
    violations = evaluate(request(quantity=10, when="2026-03-05 10:00"), ACTIVE, [rule(per_30_days=100)], neighbours, NOW)
    assert codes(violations) == {"LATER_WINDOW_EXCEEDED"}


def test_dispenses_outside_the_window_are_ignored():
    far_future = [DispenseFacts("P1", 100, sast("2026-05-05 10:00"))]
    assert evaluate(request(quantity=10, when="2026-03-05 10:00"), ACTIVE, [rule(per_30_days=100)], far_future, NOW) == []
