"""Two people fixing the same expense at the same moment.

An edit reverses the expense's old splits and applies new ones. If two edits could
both read the old splits before either wrote, the old splits would be reversed
twice. Locking the expense row before reading its splits serialises the edits; the
version check then turns the loser into a clean 409 instead of a silent overwrite.
"""

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

import app.expenses.service as expense_service
from app.expenses.models import Expense
from app.expenses.schemas import EqualSplitIn, ExpenseUpdate
from app.expenses.service import StaleExpenseVersion, update_expense
from app.ledger.audit import audit_group
from tests.concurrency.support import Gate, World, blocked_lock_waiters, outcomes, submit_all

pytestmark = pytest.mark.concurrency


def test_concurrent_edits_serialise_and_the_loser_gets_stale_version(
    session_factory: sessionmaker[Session], engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World(session_factory, "ada", "bob", "cy")
    world.expense("ada", 300, "ada", "bob", "cy")
    with session_factory() as session:
        expense_id = session.scalars(select(Expense.id)).one()

    gate = Gate(expense_service.combine)
    monkeypatch.setattr(expense_service, "combine", gate)

    def edit(actor: str, amount_cents: int) -> Expense:
        payload = ExpenseUpdate(
            description="edited",
            amount_cents=amount_cents,
            paid_by=world.ids["ada"],
            split=EqualSplitIn(method="equal", participants=[world.ids["bob"], world.ids["cy"]]),
            version=1,
        )
        with session_factory() as session:
            return update_expense(session, world.ids[actor], world.group_id, expense_id, payload)

    futures = submit_all([lambda: edit("bob", 600), lambda: edit("cy", 900)])
    try:
        assert gate.wait_for_arrivals(1, timeout=5)
        waiting = blocked_lock_waiters(engine)
        assert len(waiting) == 1 and "FROM expenses" in waiting[0]
        assert not gate.wait_for_arrivals(1, timeout=0.5)
    finally:
        gate.open()

    results = outcomes(futures)
    winners = [r for r in results if isinstance(r, Expense)]
    assert len(winners) == 1
    assert sum(isinstance(r, StaleExpenseVersion) for r in results) == 1
    half = winners[0].amount_cents // 2
    assert world.balances() == {"ada": winners[0].amount_cents, "bob": -half, "cy": -half}
    assert audit_group(engine, world.group_id).consistent
