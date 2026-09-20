"""Seed the database with the data volumes the brief requires.

    docker compose exec api python -m app.seed

500 medicines, 3-5 rule periods each, 2,000 dispenses across 2,000 patient
references over a two-year window, plus some rejected attempts so the attempt log
is not empty.

Seeding writes rows directly instead of going through POST /dispenses: it is a
fixture loader, not a client, and it must be fast and deterministic. It still only
produces dispenses that satisfy the rule in force at their dispensed_at, so the
dataset is consistent with the rules the API enforces. Rerunning it truncates first.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import insert, select, text

from .core.business_time import business_date
from .core.config import get_settings
from .db.models import Dispense, DispenseAttempt, FormularyRule, Medicine
from .db.session import SessionLocal

SEED = 20260917  # fixed, so runs are reproducible and p95 numbers are comparable

FORMS = ["tablet", "capsule", "suspension", "injection", "cream", "syrup"]
UNITS = ["mg", "mg/ml", "g", "mcg", "IU"]
STEMS = ["Amox", "Parac", "Ibupro", "Metfor", "Atorva", "Omepra", "Cipro", "Losar", "Simva", "Predni",
         "Azithro", "Furose", "Warfa", "Gliclaz", "Enala", "Ceftri", "Doxy", "Fluox", "Lamo", "Rispe"]
TAILS = ["cillin", "etamol", "fen", "min", "statin", "zole", "floxacin", "tan", "vastatin", "solone"]


def _medicine_rows(rng: random.Random, count: int) -> list[dict]:
    rows = []
    for i in range(count):
        stem, tail = rng.choice(STEMS), rng.choice(TAILS)
        rows.append(
            {
                "code": f"MED{i + 1:05d}",
                "name": f"{stem}{tail} {rng.choice([5, 10, 20, 50, 100, 250, 500])}",
                "form": rng.choice(FORMS),
                "strength_value": rng.choice([5, 10, 12.5, 20, 25, 50, 100, 250, 500, 1000]),
                "strength_unit": rng.choice(UNITS),
                # A tenth are inactive, so the inactive-medicine rejection has something to hit.
                "is_active": rng.random() > 0.1,
            }
        )
    return rows


def _rule_rows(rng: random.Random, medicine_ids: list[int], start: date, end: date) -> list[dict]:
    """3-5 contiguous, non-overlapping periods per medicine; the last is open-ended."""
    rows = []
    span = (end - start).days
    for medicine_id in medicine_ids:
        periods = rng.randint(3, 5)
        cuts = sorted(rng.sample(range(30, span - 30), periods - 1))
        boundaries = [start] + [start + timedelta(days=c) for c in cuts] + [None]
        for i in range(periods):
            per_dispense = rng.choice([14, 28, 30, 60, 90])
            rows.append(
                {
                    "medicine_id": medicine_id,
                    "effective_from": boundaries[i],
                    "effective_to": boundaries[i + 1],
                    "max_quantity_per_dispense": per_dispense,
                    "max_quantity_per_30_days": per_dispense * rng.choice([2, 3, 4]),
                    "requires_authorisation": rng.random() < 0.25,
                }
            )
    return rows


def _rule_for(rules: list[tuple], day: date) -> tuple | None:
    """rules: (id, effective_from, effective_to, max_per_dispense, max_30, requires_auth)."""
    return next((r for r in rules if r[1] <= day and (r[2] is None or day < r[2])), None)


def run() -> None:
    settings = get_settings()
    rng = random.Random(SEED)
    now = datetime.now(timezone.utc)
    start = business_date(now) - timedelta(days=730)
    end = business_date(now)

    with SessionLocal() as session:
        session.execute(
            text("TRUNCATE dispense, dispense_attempt, patient_medicine_lock, formulary_rule, medicine "
                 "RESTART IDENTITY CASCADE")
        )
        session.commit()

        medicine_ids = list(
            session.scalars(
                insert(Medicine).returning(Medicine.id), _medicine_rows(rng, settings.seed_medicines)
            )
        )
        session.commit()
        print(f"medicines: {len(medicine_ids)}")

        session.execute(insert(FormularyRule), _rule_rows(rng, medicine_ids, start, end))
        session.commit()

        rules_by_medicine: dict[int, list[tuple]] = {}
        for row in session.execute(
            select(
                FormularyRule.medicine_id,
                FormularyRule.id,
                FormularyRule.effective_from,
                FormularyRule.effective_to,
                FormularyRule.max_quantity_per_dispense,
                FormularyRule.max_quantity_per_30_days,
                FormularyRule.requires_authorisation,
            )
        ):
            rules_by_medicine.setdefault(row[0], []).append(tuple(row[1:]))
        print(f"rule periods: {sum(len(v) for v in rules_by_medicine.values())}")

        active_ids = list(session.scalars(select(Medicine.id).where(Medicine.is_active.is_(True))))

        attempts: list[dict] = []
        dispenses: list[dict] = []
        # One dispense per patient reference keeps every seeded dispense inside its own
        # 30-day window; the window logic is exercised by the tests, not by the seed.
        for i in range(settings.seed_dispenses):
            medicine_id = rng.choice(active_ids)
            when = datetime.combine(
                start + timedelta(days=rng.randint(0, 729)),
                datetime.min.time(),
                tzinfo=timezone.utc,
            ) + timedelta(hours=rng.randint(6, 18), minutes=rng.choice([0, 15, 30, 45]))
            rule = _rule_for(rules_by_medicine[medicine_id], business_date(when))
            if rule is None:
                continue
            rule_id, _, _, max_per, _, requires_auth = rule
            quantity = rng.randint(1, max_per)
            patient_ref = f"PT-{i % settings.seed_patients:05d}"
            auth = f"AUTH-{rng.randint(100000, 999999)}" if requires_auth else None
            attempts.append(
                {
                    "idempotency_key": f"seed-{i:06d}",
                    "request_fingerprint": f"seed{i:06d}",
                    "medicine_code": f"MED{medicine_id:05d}",
                    "patient_ref": patient_ref,
                    "quantity": quantity,
                    "dispensed_at": when,
                    "authorisation_ref": auth,
                    "outcome": "accepted",
                    "violations": None,
                    "response_body": {"seeded": True},
                    "response_status": 201,
                }
            )
            dispenses.append(
                {
                    "medicine_id": medicine_id,
                    "patient_ref": patient_ref,
                    "quantity": quantity,
                    "dispensed_at": when,
                    "authorisation_ref": auth,
                    "rule_id": rule_id,
                }
            )

        attempt_ids = list(session.scalars(insert(DispenseAttempt).returning(DispenseAttempt.id), attempts))
        for row, attempt_id in zip(dispenses, attempt_ids):
            row["attempt_id"] = attempt_id
        session.execute(insert(Dispense), dispenses)
        session.commit()
        print(f"dispenses: {len(dispenses)} across {len({d['patient_ref'] for d in dispenses})} patient refs")

        # A handful of rejections, so the attempt log shows both outcomes.
        rejected = [
            {
                "idempotency_key": f"seed-rej-{i:06d}",
                "request_fingerprint": f"seedrej{i:06d}",
                "medicine_code": f"MED{rng.choice(active_ids):05d}",
                "patient_ref": f"PT-{rng.randrange(settings.seed_patients):05d}",
                "quantity": 9999,
                "dispensed_at": now - timedelta(days=rng.randint(0, 60)),
                "authorisation_ref": None,
                "outcome": "rejected",
                "violations": [
                    {
                        "code": "MAX_PER_DISPENSE_EXCEEDED",
                        "field": "quantity",
                        "message": "9999 exceeds the per-dispense maximum",
                    }
                ],
                "response_body": {"seeded": True},
                "response_status": 422,
            }
            for i in range(100)
        ]
        session.execute(insert(DispenseAttempt), rejected)
        session.commit()
        print(f"rejected attempts: {len(rejected)}")
        session.execute(text("ANALYZE"))  # fresh statistics, so the first queries are honest
        session.commit()


if __name__ == "__main__":
    run()
