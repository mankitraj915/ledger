"""Tools for forcing specific interleavings of real Postgres transactions."""

import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.auth.models import User
from app.expenses.schemas import EqualSplitIn, ExpenseIn
from app.expenses.service import create_expense
from app.groups.models import Membership
from app.groups.schemas import GroupCreate
from app.groups.service import add_member, create_group
from app.ledger.balances import UserId
from app.settlements.schemas import SettlementIn
from app.settlements.service import SettlementOutcome, record_settlement

TIMEOUT = 15.0


class Gate:
    """Wraps a function so every caller parks inside it until the test opens the gate.

    Placed on the overdraw check, it holds each transaction at the precise moment
    between "read the balance" and "write the balance", which is where a lost update
    or overdraw happens. The test can then observe how many transactions managed to
    get there at once.
    """

    def __init__(self, real: Callable[..., Any]) -> None:
        self._real = real
        self._arrivals = threading.Semaphore(0)
        self._open = threading.Event()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self._arrivals.release()
        if not self._open.wait(TIMEOUT):
            raise TimeoutError("gate was never opened")
        return self._real(*args, **kwargs)

    def wait_for_arrivals(self, count: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        for _ in range(count):
            if not self._arrivals.acquire(timeout=max(0.0, deadline - time.monotonic())):
                return False
        return True

    def open(self) -> None:
        self._open.set()


def submit_all(calls: Iterable[Callable[[], Any]]) -> list[Future[Any]]:
    """Start every call on its own thread, released together by a barrier."""
    calls = list(calls)
    barrier = threading.Barrier(len(calls))
    pool = ThreadPoolExecutor(max_workers=len(calls))

    def synchronised(call: Callable[[], Any]) -> Any:
        barrier.wait(TIMEOUT)
        return call()

    futures = [pool.submit(synchronised, call) for call in calls]
    pool.shutdown(wait=False)
    return futures


def outcomes(futures: list[Future[Any]]) -> list[Any]:
    """Each future's result, or the exception it raised."""
    results: list[Any] = []
    for future in futures:
        try:
            results.append(future.result(TIMEOUT))
        except Exception as exc:
            results.append(exc)
    return results


def blocked_lock_waiters(engine: Engine, timeout: float = 5.0) -> list[str]:
    """Queries of backends currently waiting on a lock, polled until one appears."""
    deadline = time.monotonic() + timeout
    with engine.connect() as connection:
        while time.monotonic() < deadline:
            queries = (
                connection.execute(
                    text(
                        "SELECT query FROM pg_stat_activity "
                        "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                    )
                )
                .scalars()
                .all()
            )
            if queries:
                return list(queries)
            connection.rollback()  # new snapshot of pg_stat_activity next time round
            time.sleep(0.02)
    return []


class World:
    """A group of named members, driven through the real service layer."""

    def __init__(self, session_factory: sessionmaker[Session], *names: str) -> None:
        self.session_factory = session_factory
        with session_factory() as session:
            users = [User(email=f"{n}@example.com", name=n, password_hash="x") for n in names]
            session.add_all(users)
            session.commit()
            self.ids: dict[str, UserId] = {user.name: user.id for user in users}
        owner, *others = names
        with session_factory() as session:
            self.group_id = create_group(session, self.ids[owner], GroupCreate(name="g")).id
            for name in others:
                add_member(session, self.ids[owner], self.group_id, f"{name}@example.com")

    def expense(self, payer: str, amount_cents: int, *participants: str) -> None:
        payload = ExpenseIn(
            description="seed",
            amount_cents=amount_cents,
            paid_by=self.ids[payer],
            split=EqualSplitIn(method="equal", participants=[self.ids[p] for p in participants]),
        )
        with self.session_factory() as session:
            create_expense(session, self.ids[payer], self.group_id, payload)

    def settle(self, payer: str, payee: str, amount_cents: int, key: str) -> SettlementOutcome:
        payload = SettlementIn(
            payer_id=self.ids[payer], payee_id=self.ids[payee], amount_cents=amount_cents
        )
        with self.session_factory() as session:
            return record_settlement(session, self.ids[payer], self.group_id, payload, key)

    def balances(self) -> dict[str, int]:
        names = {user_id: name for name, user_id in self.ids.items()}
        with self.session_factory() as session:
            rows = session.execute(
                select(Membership.user_id, Membership.balance_cents).where(
                    Membership.group_id == self.group_id
                )
            )
            return {names[user_id]: balance for user_id, balance in rows}


def lock_balances_without_locking(
    session: Session, group_id: int, user_ids: Iterable[UserId]
) -> dict[UserId, Membership]:
    """The naive implementation: the same read, minus FOR UPDATE. For negative controls."""
    stmt = (
        select(Membership)
        .where(Membership.group_id == group_id, Membership.user_id.in_(set(user_ids)))
        .execution_options(populate_existing=True)
    )
    return {membership.user_id: membership for membership in session.scalars(stmt)}
