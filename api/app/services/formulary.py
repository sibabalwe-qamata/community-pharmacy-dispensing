"""Formulary rule-history operations.

Introducing a new rule always *supersedes* whatever is in force on its start date
rather than being inserted blindly: the previous rule's period is trimmed to end
where the new one begins. The Postgres EXCLUDE constraint `ex_rule_no_overlap`
(see alembic/versions/0001_core_schema.py) is the real, concurrency-safe guarantee
that no two rules for a medicine ever overlap -- everything here only produces
better error messages and correct trimming in the common, uncontended case.
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.business_time import business_date, utcnow
from ..core.problems import Conflict, NotFound
from ..db.models import FormularyRule, Medicine
from ..schemas.rule import RuleCreate

OVERLAP_CONSTRAINT = "ex_rule_no_overlap"


@dataclass(frozen=True)
class RuleHistory:
    """The full rule history for a medicine, plus whichever rule (if any) is in
    force today."""

    medicine: Medicine
    rules: list[FormularyRule]
    in_force_rule_id: int | None


def _get_medicine(session: Session, code: str, *, for_update: bool = False) -> Medicine:
    stmt = select(Medicine).where(Medicine.code == code)
    if for_update:
        # Row lock so two concurrent supersedes for the same medicine serialise
        # instead of both reading the same "current" rule set and racing to write.
        stmt = stmt.with_for_update()
    medicine = session.scalars(stmt).first()
    if medicine is None:
        raise NotFound("Medicine", code)
    return medicine


def _ordered_rules(session: Session, medicine_id: int) -> list[FormularyRule]:
    return list(
        session.scalars(
            select(FormularyRule)
            .where(FormularyRule.medicine_id == medicine_id)
            .order_by(FormularyRule.effective_from)
        )
    )


def get_rule_history(session: Session, code: str) -> RuleHistory:
    medicine = _get_medicine(session, code)
    rules = _ordered_rules(session, medicine.id)
    today = business_date(utcnow())
    in_force_rule_id = next(
        (
            rule.id
            for rule in rules
            if rule.effective_from <= today and (rule.effective_to is None or today < rule.effective_to)
        ),
        None,
    )
    return RuleHistory(medicine=medicine, rules=rules, in_force_rule_id=in_force_rule_id)


def supersede_rule(session: Session, code: str, data: RuleCreate) -> FormularyRule:
    """Introduce a new rule starting at `data.effective_from`, ending whatever rule
    currently covers that date. Everything below happens in one transaction, which
    this function commits on success (or rolls back on the known overlap conflict).
    """
    # (a) Lock the medicine row first so nothing about "what's currently in force"
    # can change underneath us before we commit.
    medicine = _get_medicine(session, code, for_update=True)

    new_start = data.effective_from
    existing = _ordered_rules(session, medicine.id)

    # (b) Rules already used to validate past dispenses are never edited in place,
    # only ever trimmed from the end -- so a second rule starting on the exact same
    # day is always a conflict, never something to silently replace.
    if any(rule.effective_from == new_start for rule in existing):
        raise Conflict(
            "RULE_START_CONFLICT",
            f"Medicine {code!r} already has a rule starting {new_start}.",
        )

    # (c) The rule (if any) whose period currently contains the new start date.
    superseded = next(
        (
            rule
            for rule in existing
            if rule.effective_from <= new_start and (rule.effective_to is None or new_start < rule.effective_to)
        ),
        None,
    )
    inherited_end = superseded.effective_to if superseded is not None else None
    if superseded is not None:
        superseded.effective_to = new_start
        # Flush the trim BEFORE inserting the new rule. SQLAlchemy's unit of work emits
        # inserts ahead of updates, and ex_rule_no_overlap is checked per statement, so
        # without this the new row would collide with the period we are about to shorten.
        session.flush()

    # (d) The new rule must not claim more territory than the one it replaces held:
    # if a later rule already starts after `new_start`, the new rule stops there;
    # otherwise it inherits the superseded rule's original end (dated or open-ended).
    # Extending further would silently grant a rule to dispenses that fell in what
    # used to be a gap after the superseded rule ended.
    later_starts = [rule.effective_from for rule in existing if rule.effective_from > new_start]
    new_end = min(later_starts) if later_starts else inherited_end

    new_rule = FormularyRule(
        medicine_id=medicine.id,
        effective_from=new_start,
        effective_to=new_end,
        max_quantity_per_dispense=data.max_quantity_per_dispense,
        max_quantity_per_30_days=data.max_quantity_per_30_days,
        requires_authorisation=data.requires_authorisation,
    )
    session.add(new_rule)

    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        # (e) The EXCLUDE constraint is the real guarantee against overlaps -- (b)
        # only catches the common same-day case with a clearer message.
        diag = getattr(exc.orig, "diag", None)
        constraint = getattr(diag, "constraint_name", None)
        if constraint == OVERLAP_CONSTRAINT or OVERLAP_CONSTRAINT in str(exc.orig):
            raise Conflict(
                "RULE_OVERLAP",
                f"The new rule for {code!r} starting {new_start} would overlap an existing rule.",
            ) from exc
        raise

    # (f)
    session.commit()
    return new_rule
