"""Two simultaneous dispenses must not jointly breach the 30-day limit.

The brief says a test that passes only because the requests happened to serialise is
not a demonstration. So these tests force the interleaving:

* `evaluate` is wrapped in a barrier. A request that reaches it has already read the
  window and is holding (or not holding) the lock.
* With the lock in place the barrier CANNOT be satisfied — the second transaction is
  still blocked on the lock row — so it times out, and exactly one dispense is accepted.
* With the lock disabled the barrier IS satisfied: both requests sit inside the critical
  section having read the same window total, and the limit is breached. That is the
  race the lock exists to prevent, and it is what makes the first test meaningful.
"""
import threading

from sqlalchemy import func, select

from app.db.models import Dispense
from app.schemas.dispense import DispenseCreate
from app.services import dispensing

from .factories import dispense_body, make_medicine, make_rule

LIMIT = 100
QUANTITY = 60  # two of these breach a 30-day limit of 100


def _run_two(session_factory, barrier: threading.Barrier, monkeypatch) -> list:
    """Fire two dispenses for the same patient and medicine from two connections."""
    real_evaluate = dispensing.evaluate

    def barriered_evaluate(*args, **kwargs):
        try:
            barrier.wait(timeout=2)
        except threading.BrokenBarrierError:
            pass  # expected when the lock is doing its job
        return real_evaluate(*args, **kwargs)

    monkeypatch.setattr(dispensing, "evaluate", barriered_evaluate)

    results: list = [None, None]

    def attempt(index: int) -> None:
        with session_factory() as session:
            payload = DispenseCreate(**dispense_body(quantity=QUANTITY))
            results[index] = dispensing.create_dispense(session, payload, f"race-key-{index}")

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return results


def test_concurrent_dispenses_cannot_both_be_accepted(session, session_factory, monkeypatch):
    medicine = make_medicine(session)
    make_rule(session, medicine, per_dispense=LIMIT, per_30_days=LIMIT)
    barrier = threading.Barrier(2)

    results = _run_two(session_factory, barrier, monkeypatch)

    statuses = sorted(outcome.status for outcome in results)
    assert statuses == [201, 422]
    assert barrier.broken, "the barrier should time out: the lock must keep the second request out"

    rejected = next(o for o in results if o.status == 422)
    assert {e["code"] for e in rejected.body["errors"]} == {"MAX_30_DAYS_EXCEEDED"}
    assert session.scalar(select(func.sum(Dispense.quantity))) == QUANTITY
    assert session.scalar(select(func.count()).select_from(Dispense)) == 1


def test_without_the_lock_the_limit_is_breached(session, session_factory, monkeypatch):
    """The control: the same interleaving, with the lock removed."""
    medicine = make_medicine(session)
    make_rule(session, medicine, per_dispense=LIMIT, per_30_days=LIMIT)
    monkeypatch.setattr(dispensing, "lock_patient_medicine", lambda *args, **kwargs: None)
    barrier = threading.Barrier(2)

    results = _run_two(session_factory, barrier, monkeypatch)

    assert not barrier.broken, "both requests should reach the critical section together"
    assert [outcome.status for outcome in results] == [201, 201]
    assert session.scalar(select(func.sum(Dispense.quantity))) == QUANTITY * 2 > LIMIT
