"""The dispense algorithm: idempotent, locked, and rule-checked. Routers stay thin;
everything delicate about accepting or rejecting a dispense lives here.
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.business_time import business_date, start_of_business_day, utcnow, window_start
from ..core.config import get_settings
from ..core.pagination import decode_cursor, encode_cursor, take_page
from ..core.problems import DispenseRejected, UnprocessableRequest, Violation, problem_body
from ..db.models import Dispense, DispenseAttempt, FormularyRule, Medicine, PatientMedicineLock
from ..domain.rule_engine import DispenseFacts, MedicineFacts, RulePeriod, evaluate, rule_in_force
from ..schemas.dispense import DispenseCreate, DispenseRead

settings = get_settings()


@dataclass(frozen=True)
class DispenseOutcome:
    """What the router needs to build a response: it never touches the DB itself."""

    status: int
    body: dict


def _fingerprint(payload: DispenseCreate) -> str:
    """sha256 of a stable JSON encoding of the normalised body.

    Sorted keys and a fixed UTC ISO-8601 timestamp mean the same logical request always
    hashes the same way, regardless of how the client formatted its offset.
    """
    canonical = {
        "medicine_code": payload.medicine_code,
        "patient_ref": payload.patient_ref,
        "quantity": payload.quantity,
        "dispensed_at": payload.dispensed_at.astimezone(timezone.utc).isoformat(),
        "authorisation_ref": payload.authorisation_ref,
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _replay(attempt: DispenseAttempt) -> DispenseOutcome:
    return DispenseOutcome(status=attempt.response_status, body=attempt.response_body)


def _replay_after_conflict(db: Session, exc: IntegrityError, idempotency_key: str) -> DispenseOutcome:
    """Two requests raced on the same Idempotency-Key: both passed the "does an attempt
    already exist" check before either had committed. The loser's insert/flush trips
    `uq_attempt_idempotency_key`; once rolled back, the winner's row is already
    committed, so replay it instead of surfacing a spurious error to the loser.
    """
    db.rollback()
    if "uq_attempt_idempotency_key" not in str(exc.orig):
        raise exc
    attempt = db.execute(
        select(DispenseAttempt).where(DispenseAttempt.idempotency_key == idempotency_key)
    ).scalar_one()
    return _replay(attempt)


def lock_patient_medicine(db: Session, patient_ref: str, medicine_id: int) -> None:
    """Hold the (patient_ref, medicine_id) row until this transaction ends.

    ON CONFLICT DO UPDATE rather than DO NOTHING: DO NOTHING neither inserts nor locks
    the conflicting row, so a concurrent inserter that then rolled back could leave a
    follow-up SELECT with nothing to lock. A no-op UPDATE always leaves this transaction
    holding the row lock, whoever created the row.

    Named, not inlined, so the concurrency test can disable it and show that the limit is
    breached without it — otherwise a passing test proves nothing about the lock.
    """
    db.execute(
        pg_insert(PatientMedicineLock)
        .values(patient_ref=patient_ref, medicine_id=medicine_id)
        .on_conflict_do_update(index_elements=["patient_ref", "medicine_id"], set_={"patient_ref": patient_ref})
    )


def _persist_rejection(
    db: Session,
    payload: DispenseCreate,
    idempotency_key: str,
    fingerprint: str,
    violations: list[Violation],
) -> DispenseOutcome:
    """Write the attempt, commit it, and hand the rejection back as a value.

    The attempt must survive even though the dispense is refused: a rejection leaves an
    attempt row and NO dispense row, and both facts must hold at once. Raising a
    ProblemError here would unwind the transaction before it commits and lose the log,
    so nothing on this path raises.
    """
    body = problem_body(DispenseRejected(violations))
    attempt = DispenseAttempt(
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        medicine_code=payload.medicine_code,
        patient_ref=payload.patient_ref,
        quantity=payload.quantity,
        dispensed_at=payload.dispensed_at,
        authorisation_ref=payload.authorisation_ref,
        outcome="rejected",
        violations=[v.as_dict() for v in violations],
        response_body=body,
        response_status=422,
    )
    db.add(attempt)
    try:
        db.commit()
    except IntegrityError as exc:  # lost the idempotency-key race
        return _replay_after_conflict(db, exc, idempotency_key)
    return DispenseOutcome(status=422, body=body)


def create_dispense(db: Session, payload: DispenseCreate, idempotency_key: str) -> DispenseOutcome:
    fingerprint = _fingerprint(payload)

    # (b) Idempotency check happens before anything else is touched, and outside the
    # patient/medicine lock: a replay must be cheap and must not serialise against
    # unrelated in-flight dispenses.
    existing = db.execute(
        select(DispenseAttempt).where(DispenseAttempt.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            # The key is a client promise that a retried request carries the same
            # payload. A different payload under the same key is a client bug, not a
            # new logical request, so this is rejected rather than silently replayed
            # or silently accepted as a second dispense.
            raise UnprocessableRequest(
                "IDEMPOTENCY_KEY_REUSED",
                "This Idempotency-Key was already used with a different request body.",
            )
        return _replay(existing)

    # (c) An unknown code is a rejected attempt, not a 404: it is a dispense the
    # pharmacy tried to make and could not, so it belongs in the attempt log with its
    # reason, and the form can mark the medicine field like any other violation.
    medicine = db.execute(select(Medicine).where(Medicine.code == payload.medicine_code)).scalar_one_or_none()
    if medicine is None:
        return _persist_rejection(
            db,
            payload,
            idempotency_key,
            fingerprint,
            [
                Violation(
                    "MEDICINE_NOT_FOUND",
                    "medicine_code",
                    f"No medicine with code {payload.medicine_code!r}",
                )
            ],
        )

    # (d) Ensure the (patient_ref, medicine_id) lock row exists, then take it FOR
    # UPDATE. Every dispense for this pair is now serialised until this transaction
    # commits or rolls back, which is what stops two concurrent requests jointly
    # breaching the 30-day limit.
    lock_patient_medicine(db, payload.patient_ref, medicine.id)

    # (e) Rules for this medicine, and neighbouring dispenses within window_days - 1
    # days either side of the request date. Earlier ones matter for the request's own
    # window; later ones matter because a backdated dispense must not push a LATER
    # dispense's window over its limit. The range query rides ix_dispense_window
    # (patient_ref, medicine_id, dispensed_at).
    rule_rows = db.execute(select(FormularyRule).where(FormularyRule.medicine_id == medicine.id)).scalars().all()
    rules = [
        RulePeriod(
            id=r.id,
            effective_from=r.effective_from,
            effective_to=r.effective_to,
            max_quantity_per_dispense=r.max_quantity_per_dispense,
            max_quantity_per_30_days=r.max_quantity_per_30_days,
            requires_authorisation=r.requires_authorisation,
        )
        for r in rule_rows
    ]

    request_day = business_date(payload.dispensed_at)
    lower = window_start(payload.dispensed_at, settings.window_days)
    upper_day = request_day + timedelta(days=settings.window_days - 1)
    upper = start_of_business_day(upper_day + timedelta(days=1))  # exclusive: start of the day after upper_day

    neighbour_rows = (
        db.execute(
            select(Dispense).where(
                Dispense.patient_ref == payload.patient_ref,
                Dispense.medicine_id == medicine.id,
                Dispense.dispensed_at >= lower,
                Dispense.dispensed_at < upper,
            )
        )
        .scalars()
        .all()
    )
    neighbours = [
        DispenseFacts(
            patient_ref=n.patient_ref,
            quantity=n.quantity,
            dispensed_at=n.dispensed_at,
            authorisation_ref=n.authorisation_ref,
        )
        for n in neighbour_rows
    ]

    request_facts = DispenseFacts(
        patient_ref=payload.patient_ref,
        quantity=payload.quantity,
        dispensed_at=payload.dispensed_at,
        authorisation_ref=payload.authorisation_ref,
    )
    medicine_facts = MedicineFacts(code=medicine.code, is_active=medicine.is_active)

    # (f)
    violations = evaluate(request_facts, medicine_facts, rules, neighbours, utcnow())

    if violations:
        # (g) Rejected: the attempt is logged and committed, and no dispense row exists.
        return _persist_rejection(db, payload, idempotency_key, fingerprint, violations)

    # (h) Accepted: the attempt is inserted first (flushed, not yet committed) so its
    # id is available for the Dispense FK; the response body is filled in afterwards
    # once the dispense itself has an id and a server-assigned created_at.
    attempt = DispenseAttempt(
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        medicine_code=payload.medicine_code,
        patient_ref=payload.patient_ref,
        quantity=payload.quantity,
        dispensed_at=payload.dispensed_at,
        authorisation_ref=payload.authorisation_ref,
        outcome="accepted",
        violations=None,
        response_body={},
        response_status=201,
    )
    db.add(attempt)
    try:
        db.flush()  # assigns attempt.id; also where a racing duplicate key surfaces
    except IntegrityError as exc:  # (i) lost the idempotency-key race
        return _replay_after_conflict(db, exc, idempotency_key)

    rule = rule_in_force(rules, request_day)
    if rule is None:  # unreachable: evaluate() reports NO_RULE_IN_FORCE instead
        raise RuntimeError("accepted a dispense with no rule in force")

    dispense = Dispense(
        medicine_id=medicine.id,
        attempt_id=attempt.id,
        patient_ref=payload.patient_ref,
        quantity=payload.quantity,
        dispensed_at=payload.dispensed_at,
        authorisation_ref=payload.authorisation_ref,
        rule_id=rule.id,
    )
    db.add(dispense)
    db.flush()  # assigns dispense.id and created_at (server_default, fetched via RETURNING)

    body = DispenseRead(
        id=dispense.id,
        medicine_code=medicine.code,
        patient_ref=dispense.patient_ref,
        quantity=dispense.quantity,
        dispensed_at=dispense.dispensed_at,
        authorisation_ref=dispense.authorisation_ref,
        rule_id=dispense.rule_id,
        created_at=dispense.created_at,
    ).model_dump(mode="json")
    attempt.response_body = body

    try:
        db.commit()
    except IntegrityError as exc:  # (i) lost the idempotency-key race, very last moment
        return _replay_after_conflict(db, exc, idempotency_key)
    return DispenseOutcome(status=201, body=body)


def list_dispenses(
    db: Session,
    patient_ref: str | None,
    medicine_code: str | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[DispenseRead], str | None]:
    """Newest first, keyset-paginated on (dispensed_at, id).

    Filtering by patient_ref/medicine_code rides ix_dispense_patient_recent /
    ix_dispense_medicine_recent; both filters together still use one of the two.
    """
    stmt = select(Dispense, Medicine.code).join(Medicine, Medicine.id == Dispense.medicine_id)

    if patient_ref:
        stmt = stmt.where(Dispense.patient_ref == patient_ref)
    if medicine_code:
        stmt = stmt.where(Medicine.code == medicine_code)

    decoded = decode_cursor(cursor)
    if decoded is not None:
        try:
            cursor_dispensed_at = datetime.fromisoformat(str(decoded["dispensed_at"]))
            cursor_id = int(decoded["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise UnprocessableRequest("INVALID_CURSOR", "The cursor is not valid.") from exc
        # Descending order, so the next page is strictly "less than" the last row seen.
        stmt = stmt.where(tuple_(Dispense.dispensed_at, Dispense.id) < tuple_(cursor_dispensed_at, cursor_id))

    stmt = stmt.order_by(Dispense.dispensed_at.desc(), Dispense.id.desc()).limit(limit + 1)
    rows = db.execute(stmt).all()

    page_rows, has_more = take_page(rows, limit)
    items = [
        DispenseRead(
            id=d.id,
            medicine_code=code,
            patient_ref=d.patient_ref,
            quantity=d.quantity,
            dispensed_at=d.dispensed_at,
            authorisation_ref=d.authorisation_ref,
            rule_id=d.rule_id,
            created_at=d.created_at,
        )
        for d, code in page_rows
    ]
    next_cursor = (
        encode_cursor({"dispensed_at": page_rows[-1][0].dispensed_at.isoformat(), "id": page_rows[-1][0].id})
        if has_more and page_rows
        else None
    )
    return items, next_cursor
