"""Many clients doing everything at once.

The targeted tests prove specific interleavings; this one looks for interleavings
nobody thought of. Eight threads add expenses (participants in random order), edit
them and settle up in every direction for a few hundred operations. Afterwards the
stored balances must sum to zero and match a replay of the journal, and the only
errors allowed are the business-rule rejections, so no deadlocks, no trigger
violations and no serialisation failures.

Seeds are fixed, but thread scheduling is not, so this is evidence rather than a
proof; the proofs are in test_settlement_races.py.
"""

import random
import uuid

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.expenses.models import Expense
from app.expenses.schemas import EqualSplitIn, ExpenseIn, ExpenseUpdate
from app.expenses.service import StaleExpenseVersion, create_expense, update_expense
from app.ledger.audit import audit_group
from app.ledger.balances import SettlementExceedsBalance
from app.settlements.models import Settlement
from app.settlements.service import SettlementOutcome
from tests.concurrency.support import World, outcomes, submit_all

pytestmark = pytest.mark.concurrency

MEMBERS = ("ada", "bob", "cy", "dee", "eli")
THREADS = 8
OPERATIONS_PER_THREAD = 30
EXPECTED_REJECTIONS = (SettlementExceedsBalance, StaleExpenseVersion)


def worker(world: World, seed: int) -> list[object]:
    rng = random.Random(seed)
    results: list[object] = []
    for _ in range(OPERATIONS_PER_THREAD):
        roll = rng.random()
        try:
            if roll < 0.35:
                results.append(add_expense(world, rng))
            elif roll < 0.5:
                results.append(edit_expense(world, rng))
            else:
                payer, payee = rng.sample(MEMBERS, 2)
                key = str(uuid.UUID(int=rng.getrandbits(128)))
                results.append(world.settle(payer, payee, rng.randint(1, 3_000), key))
        except EXPECTED_REJECTIONS as rejection:
            results.append(rejection)
    return results


def random_split(world: World, rng: random.Random) -> EqualSplitIn:
    participants = rng.sample(MEMBERS, rng.randint(1, len(MEMBERS)))  # random order
    return EqualSplitIn(method="equal", participants=[world.ids[p] for p in participants])


def add_expense(world: World, rng: random.Random) -> Expense:
    payer = rng.choice(MEMBERS)
    payload = ExpenseIn(
        description="stress",
        amount_cents=rng.randint(1, 10_000),
        paid_by=world.ids[payer],
        split=random_split(world, rng),
    )
    with world.session_factory() as session:
        return create_expense(session, world.ids[payer], world.group_id, payload)


def edit_expense(world: World, rng: random.Random) -> Expense | None:
    with world.session_factory() as session:
        row = session.execute(
            select(Expense.id, Expense.version).order_by(func.random()).limit(1)
        ).one_or_none()
    if row is None:
        return None
    actor = rng.choice(MEMBERS)
    payload = ExpenseUpdate(
        description="stress edit",
        amount_cents=rng.randint(1, 10_000),
        paid_by=world.ids[rng.choice(MEMBERS)],
        split=random_split(world, rng),
        version=row.version,  # read outside the edit's transaction: may well be stale
    )
    with world.session_factory() as session:
        return update_expense(session, world.ids[actor], world.group_id, row.id, payload)


def test_mixed_concurrent_workload_preserves_every_invariant(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    world = World(session_factory, *MEMBERS)
    world.expense("ada", 50_000, *MEMBERS)

    per_thread = outcomes(
        submit_all([lambda seed=seed: worker(world, seed) for seed in range(THREADS)])
    )

    unexpected = [r for r in per_thread if isinstance(r, BaseException)]
    assert not unexpected, f"unexpected errors (deadlock? trigger?): {unexpected}"
    results = [r for thread_results in per_thread for r in thread_results]
    settled = [r for r in results if isinstance(r, SettlementOutcome)]
    assert settled, "workload never managed a settlement; it is not exercising anything"

    audit = audit_group(engine, world.group_id)
    assert audit.consistent, f"stored {audit.stored} != journal {audit.journal}"
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Settlement)) == len(settled)
