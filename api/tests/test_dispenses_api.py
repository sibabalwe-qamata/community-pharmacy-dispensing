"""POST/GET /dispenses: idempotency, the attempt log, and the error contract."""
from sqlalchemy import func, select

from app.db.models import Dispense, DispenseAttempt

from .factories import dispense_body, make_medicine, make_rule, sast

URL = "/api/v1/dispenses"


def post(client, body: dict, key: str = "key-00000001"):
    return client.post(URL, json=body, headers={"Idempotency-Key": key})


def test_accepts_a_valid_dispense(client, session):
    medicine = make_medicine(session)
    make_rule(session, medicine)

    response = post(client, dispense_body())

    assert response.status_code == 201
    payload = response.json()
    assert payload["quantity"] == 10
    assert payload["rule_id"] is not None
    assert session.scalar(select(func.count()).select_from(Dispense)) == 1


def test_rejection_is_logged_and_leaves_no_dispense(client, session):
    """Both halves of rule 7 at once: the attempt is persisted with its reasons, and
    no dispense row survives the rejection."""
    medicine = make_medicine(session)
    make_rule(session, medicine, per_dispense=5, per_30_days=5, auth=True)

    response = post(client, dispense_body(quantity=50))

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    codes = {e["code"] for e in body["errors"]}
    assert codes == {"MAX_PER_DISPENSE_EXCEEDED", "MAX_30_DAYS_EXCEEDED", "AUTHORISATION_REQUIRED"}
    assert {e["field"] for e in body["errors"]} == {"quantity", "authorisation_ref"}

    assert session.scalar(select(func.count()).select_from(Dispense)) == 0
    attempt = session.scalars(select(DispenseAttempt)).one()
    assert attempt.outcome == "rejected"
    assert {v["code"] for v in attempt.violations} == codes


def test_unknown_medicine_is_a_logged_rejection(client, session):
    response = post(client, dispense_body(code="NOPE"))

    assert response.status_code == 422
    assert {e["code"] for e in response.json()["errors"]} == {"MEDICINE_NOT_FOUND"}
    assert session.scalars(select(DispenseAttempt)).one().outcome == "rejected"


def test_inactive_medicine_is_rejected(client, session):
    medicine = make_medicine(session, is_active=False)
    make_rule(session, medicine)

    response = post(client, dispense_body())

    assert response.status_code == 422
    assert "MEDICINE_INACTIVE" in {e["code"] for e in response.json()["errors"]}


def test_naive_timestamp_is_a_field_error(client, session):
    medicine = make_medicine(session)
    make_rule(session, medicine)
    body = dispense_body() | {"dispensed_at": "2026-03-10T10:00:00"}

    response = post(client, body)

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "dispensed_at"


def test_repeating_a_key_replays_the_original_outcome(client, session):
    medicine = make_medicine(session)
    make_rule(session, medicine)
    body = dispense_body()

    first = post(client, body, key="repeat-key-1")
    second = post(client, body, key="repeat-key-1")

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert session.scalar(select(func.count()).select_from(Dispense)) == 1


def test_a_replayed_rejection_is_also_replayed(client, session):
    medicine = make_medicine(session)
    make_rule(session, medicine, per_dispense=1)
    body = dispense_body(quantity=50)

    first = post(client, body, key="repeat-key-2")
    second = post(client, body, key="repeat-key-2")

    assert first.status_code == second.status_code == 422
    assert first.json() == second.json()
    assert session.scalar(select(func.count()).select_from(DispenseAttempt)) == 1


def test_same_key_with_a_different_payload_is_rejected(client, session):
    medicine = make_medicine(session)
    make_rule(session, medicine)

    post(client, dispense_body(quantity=10), key="reuse-key-1")
    response = post(client, dispense_body(quantity=11), key="reuse-key-1")

    assert response.status_code == 422
    assert response.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert session.scalar(select(func.count()).select_from(Dispense)) == 1


def test_missing_idempotency_key_is_refused(client, session):
    assert client.post(URL, json=dispense_body()).status_code == 422


def test_backdated_dispense_breaching_a_later_window_is_rejected(client, session):
    medicine = make_medicine(session)
    make_rule(session, medicine, per_dispense=100, per_30_days=100)

    assert post(client, dispense_body(quantity=60, when="2026-03-10 10:00"), key="win-1").status_code == 201
    assert post(client, dispense_body(quantity=40, when="2026-03-20 10:00"), key="win-2").status_code == 201

    late = post(client, dispense_body(quantity=30, when="2026-03-05 10:00"), key="win-3")

    assert late.status_code == 422
    assert {e["code"] for e in late.json()["errors"]} == {"LATER_WINDOW_EXCEEDED"}


def test_ledger_is_newest_first_and_paginates(client, session):
    medicine = make_medicine(session)
    make_rule(session, medicine, per_dispense=100, per_30_days=1000)
    for day in range(1, 6):
        post(client, dispense_body(quantity=1, when=f"2026-03-0{day} 10:00"), key=f"page-key-{day}")

    first = client.get(URL, params={"patient_ref": "PT-1", "limit": 2}).json()
    assert [item["dispensed_at"] for item in first["items"]] == [
        sast("2026-03-05 10:00").isoformat(),
        sast("2026-03-04 10:00").isoformat(),
    ]

    second = client.get(URL, params={"patient_ref": "PT-1", "limit": 2, "cursor": first["next_cursor"]}).json()
    assert [item["dispensed_at"] for item in second["items"]] == [
        sast("2026-03-03 10:00").isoformat(),
        sast("2026-03-02 10:00").isoformat(),
    ]


def test_ledger_filters_by_patient(client, session):
    medicine = make_medicine(session)
    make_rule(session, medicine)
    post(client, dispense_body(patient_ref="PT-1"), key="filter-key-1")
    post(client, dispense_body(patient_ref="PT-2"), key="filter-key-2")

    body = client.get(URL, params={"patient_ref": "PT-2"}).json()

    assert [item["patient_ref"] for item in body["items"]] == ["PT-2"]
