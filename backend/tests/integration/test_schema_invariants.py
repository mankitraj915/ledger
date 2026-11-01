"""The database itself refuses to store broken money, whatever code path tries."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.groups.models import Membership
from app.ledger.balances import UnbalancedDeltas
from app.ledger.store import apply_deltas


@pytest.fixture
def pair(session_factory: sessionmaker[Session]) -> int:
    """A group with members 1 and 2, both at zero. Returns the group id."""
    with session_factory.begin() as session:
        session.execute(
            text(
                "INSERT INTO users (email, name, password_hash) VALUES "
                "('a@example.com', 'A', 'x'), ('b@example.com', 'B', 'x')"
            )
        )
        group_id = session.execute(
            text(
                "INSERT INTO groups (name, currency, created_by) "
                "VALUES ('G', 'USD', 1) RETURNING id"
            )
        ).scalar_one()
        session.execute(
            text("INSERT INTO memberships (group_id, user_id) VALUES (:g, 1), (:g, 2)"),
            {"g": group_id},
        )
    return int(group_id)


def test_commit_that_breaks_zero_sum_is_refused(
    session_factory: sessionmaker[Session], pair: int
) -> None:
    with (
        pytest.raises(IntegrityError, match="sum to 100, not 0"),
        session_factory.begin() as session,
    ):
        session.execute(
            text("UPDATE memberships SET balance_cents = 100 WHERE group_id = :g AND user_id = 1"),
            {"g": pair},
        )
    with session_factory() as session:
        balances = session.execute(text("SELECT balance_cents FROM memberships")).scalars().all()
    assert balances == [0, 0]


def test_transiently_unbalanced_statements_are_fine_if_the_commit_balances(
    session_factory: sessionmaker[Session], pair: int
) -> None:
    with session_factory.begin() as session:
        for user_id, delta in ((1, 100), (2, -100)):
            session.execute(
                text(
                    "UPDATE memberships SET balance_cents = balance_cents + :d "
                    "WHERE group_id = :g AND user_id = :u"
                ),
                {"d": delta, "g": pair, "u": user_id},
            )
    with session_factory() as session:
        total = session.execute(text("SELECT SUM(balance_cents) FROM memberships")).scalar_one()
    assert total == 0


@pytest.mark.parametrize(
    ("payer", "payee", "amount", "constraint"),
    [(1, 1, 100, "distinct_parties"), (1, 2, 0, "amount_positive")],
)
def test_settlement_row_constraints(
    session_factory: sessionmaker[Session],
    pair: int,
    payer: int,
    payee: int,
    amount: int,
    constraint: str,
) -> None:
    with pytest.raises(IntegrityError, match=constraint), session_factory.begin() as session:
        session.execute(
            text(
                "INSERT INTO settlements (group_id, payer_id, payee_id, amount_cents, created_by,"
                " idempotency_key, request_fingerprint) VALUES (:g, :p, :q, :a, 1, 'k', 'f')"
            ),
            {"g": pair, "p": payer, "q": payee, "a": amount},
        )


class TestApplyDeltas:
    def members(self) -> dict[int, Membership]:
        return {u: Membership(group_id=1, user_id=u, balance_cents=0) for u in (1, 2)}

    def test_applies_balanced_deltas(self) -> None:
        locked = self.members()
        apply_deltas(locked, {1: 50, 2: -50})
        assert (locked[1].balance_cents, locked[2].balance_cents) == (50, -50)

    def test_refuses_unbalanced_deltas(self) -> None:
        with pytest.raises(UnbalancedDeltas):
            apply_deltas(self.members(), {1: 50, 2: -49})

    def test_refuses_to_touch_a_row_that_is_not_locked(self) -> None:
        with pytest.raises(RuntimeError, match="not locked"):
            apply_deltas(self.members(), {1: 50, 3: -50})
