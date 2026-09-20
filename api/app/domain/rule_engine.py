"""Pure formulary evaluation. No database, no HTTP, no clock of its own.

Everything the caller must know:

    evaluate(request, medicine, rules, neighbours, now) -> list[Violation]

`rules` is the medicine's rule history (any order). `neighbours` is every accepted
dispense for the same patient and medicine whose dispensed_at falls within
`window_days - 1` days either side of the request — enough for the request's own
window and for every later window the request would fall into.

An empty list means the dispense is acceptable. The list is never short-circuited:
every violated rule is reported (brief, rule 6).
"""
from dataclasses import dataclass
from datetime import date, datetime

from ..core.business_time import business_date, window_start
from ..core.config import get_settings
from ..core.problems import Violation

WINDOW_DAYS = get_settings().window_days


@dataclass(frozen=True)
class RulePeriod:
    id: int | None
    effective_from: date
    effective_to: date | None  # exclusive
    max_quantity_per_dispense: int
    max_quantity_per_30_days: int
    requires_authorisation: bool

    def covers(self, day: date) -> bool:
        return self.effective_from <= day and (self.effective_to is None or day < self.effective_to)


@dataclass(frozen=True)
class DispenseFacts:
    """A dispense, either proposed or already recorded."""

    patient_ref: str
    quantity: int
    dispensed_at: datetime
    authorisation_ref: str | None = None


@dataclass(frozen=True)
class MedicineFacts:
    code: str
    is_active: bool


def rule_in_force(rules: list[RulePeriod], day: date) -> RulePeriod | None:
    return next((r for r in rules if r.covers(day)), None)


def in_window(window_end: datetime, other: datetime) -> bool:
    """Is `other` inside the 30 business dates ending at `window_end` (inclusive)?"""
    return window_start(window_end, WINDOW_DAYS) <= other <= window_end


def window_total(window_end: datetime, dispenses: list[DispenseFacts]) -> int:
    return sum(d.quantity for d in dispenses if in_window(window_end, d.dispensed_at))


def evaluate(
    request: DispenseFacts,
    medicine: MedicineFacts,
    rules: list[RulePeriod],
    neighbours: list[DispenseFacts],
    now: datetime,
) -> list[Violation]:
    violations: list[Violation] = []

    if not medicine.is_active:
        violations.append(
            Violation("MEDICINE_INACTIVE", "medicine_code", f"Medicine {medicine.code} is not active")
        )
    if request.dispensed_at > now:
        violations.append(
            Violation("DISPENSED_IN_FUTURE", "dispensed_at", "dispensed_at may not be in the future")
        )

    day = business_date(request.dispensed_at)
    rule = rule_in_force(rules, day)
    if rule is None:
        violations.append(
            Violation("NO_RULE_IN_FORCE", "dispensed_at", f"No formulary rule is in force on {day}")
        )
        return violations  # nothing further can be judged without a rule

    if request.quantity > rule.max_quantity_per_dispense:
        violations.append(
            Violation(
                "MAX_PER_DISPENSE_EXCEEDED",
                "quantity",
                f"{request.quantity} exceeds the per-dispense maximum of {rule.max_quantity_per_dispense}",
                rule.id,
            )
        )

    if rule.requires_authorisation and not (request.authorisation_ref or "").strip():
        violations.append(
            Violation(
                "AUTHORISATION_REQUIRED",
                "authorisation_ref",
                "The rule in force requires an authorisation reference",
                rule.id,
            )
        )

    own_total = window_total(request.dispensed_at, neighbours) + request.quantity
    if own_total > rule.max_quantity_per_30_days:
        violations.append(
            Violation(
                "MAX_30_DAYS_EXCEEDED",
                "quantity",
                f"{own_total} units in the {WINDOW_DAYS} days ending {day} exceeds "
                f"the maximum of {rule.max_quantity_per_30_days}",
                rule.id,
            )
        )

    # A backdated dispense also has to fit inside the windows of dispenses that occurred
    # after it. Without this, recording March 5 after March 20 can leave the March 20
    # window over its limit with nobody told.
    for later in sorted(neighbours, key=lambda d: d.dispensed_at):
        if later.dispensed_at <= request.dispensed_at or not in_window(later.dispensed_at, request.dispensed_at):
            continue
        later_rule = rule_in_force(rules, business_date(later.dispensed_at))
        if later_rule is None:
            continue
        total = window_total(later.dispensed_at, neighbours) + request.quantity
        if total > later_rule.max_quantity_per_30_days:
            violations.append(
                Violation(
                    "LATER_WINDOW_EXCEEDED",
                    "dispensed_at",
                    f"This backdated dispense would push the window ending "
                    f"{business_date(later.dispensed_at)} to {total} units, over the maximum of "
                    f"{later_rule.max_quantity_per_30_days}",
                    later_rule.id,
                )
            )
            break  # the earliest breached later window is enough to reject

    return violations
