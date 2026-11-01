"""Proof that concurrent settlements cannot corrupt balances.

Each race is forced deterministically rather than hoped for: a Gate parks every
transaction between reading a balance and writing it. With correct locking only one
transaction can ever reach that point; the others are provably blocked on the
balance-row lock (we observe them in pg_stat_activity). Each test is paired with a
negative control that removes FOR UPDATE and shows the same choreography *does*
corrupt the data, so a pass cannot be an accident of timing.
"""

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import app.settlements.service as settlement_service
from app.ledger.audit import audit_group
from app.ledger.balances import SettlementExceedsBalance
from app.settlements.service import SettlementOutcome
from tests.concurrency.support import (
    Gate,
    World,
    blocked_lock_waiters,
    lock_balances_without_locking,
    outcomes,
    submit_all,
)

pytestmark = pytest.mark.concurrency


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch) -> Gate:
    gate = Gate(settlement_service.ensure_settleable)
    monkeypatch.setattr(settlement_service, "ensure_settleable", gate)
    return gate


@pytest.fixture
def without_row_locks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settlement_service, "lock_balances", lock_balances_without_locking)


@pytest.fixture
def bob_owes_ada_100(session_factory: sessionmaker[Session]) -> World:
    world = World(session_factory, "ada", "bob")
    world.expense("ada", 200, "ada", "bob")
    assert world.balances() == {"ada": 100, "bob": -100}
    return world


@pytest.fixture
def ada_and_bob_each_owe_cy_100(session_factory: sessionmaker[Session]) -> World:
    world = World(session_factory, "ada", "bob", "cy")
    world.expense("cy", 200, "ada", "bob")
    assert world.balances() == {"ada": -100, "bob": -100, "cy": 200}
    return world


class TestOverdraw:
    """Two settlements of the full debt, submitted at the same instant."""

    def test_second_settlement_waits_for_the_first_and_is_rejected(
        self, engine: Engine, gate: Gate, bob_owes_ada_100: World
    ) -> None:
        world = bob_owes_ada_100
        futures = submit_all(
            [
                lambda: world.settle("bob", "ada", 100, "k1"),
                lambda: world.settle("bob", "ada", 100, "k2"),
            ]
        )
        try:
            assert gate.wait_for_arrivals(1, timeout=5), "neither transaction reached the check"
            # The other transaction must be stuck on the balance-row lock, not merely slow.
            waiting = blocked_lock_waiters(engine)
            assert len(waiting) == 1
            assert "FOR UPDATE" in waiting[0] and "memberships" in waiting[0]
            assert not gate.wait_for_arrivals(1, timeout=0.5), "both transactions read the balance"
        finally:
            gate.open()

        results = outcomes(futures)
        assert sum(isinstance(r, SettlementOutcome) for r in results) == 1
        assert sum(isinstance(r, SettlementExceedsBalance) for r in results) == 1
        assert world.balances() == {"ada": 0, "bob": 0}
        assert audit_group(engine, world.group_id).consistent

    @pytest.mark.usefixtures("without_row_locks")
    def test_negative_control_without_locks_both_pay_and_the_ledger_is_corrupted(
        self, engine: Engine, gate: Gate, bob_owes_ada_100: World
    ) -> None:
        world = bob_owes_ada_100
        futures = submit_all(
            [
                lambda: world.settle("bob", "ada", 100, "k1"),
                lambda: world.settle("bob", "ada", 100, "k2"),
            ]
        )
        try:
            assert gate.wait_for_arrivals(2, timeout=5), "expected both to read the stale balance"
        finally:
            gate.open()

        results = outcomes(futures)
        # Overdraw: 200 paid against a 100 debt, both "successfully".
        assert all(isinstance(r, SettlementOutcome) for r in results)
        # Lost update: the second write overwrote the first, so the stored balances
        # still sum to zero (the trigger cannot see it) but disagree with history.
        assert world.balances() == {"ada": 0, "bob": 0}
        audit = audit_group(engine, world.group_id)
        assert not audit.consistent
        assert audit.journal == {world.ids["ada"]: -100, world.ids["bob"]: 100}


class TestLostUpdateOnSharedCreditor:
    """Ada and Bob each pay Cy at the same instant: both write Cy's balance row."""

    def test_both_succeed_and_neither_update_is_lost(
        self, engine: Engine, gate: Gate, ada_and_bob_each_owe_cy_100: World
    ) -> None:
        world = ada_and_bob_each_owe_cy_100
        futures = submit_all(
            [
                lambda: world.settle("ada", "cy", 100, "a"),
                lambda: world.settle("bob", "cy", 100, "b"),
            ]
        )
        try:
            assert gate.wait_for_arrivals(1, timeout=5)
            assert len(blocked_lock_waiters(engine)) == 1
        finally:
            gate.open()

        assert all(isinstance(r, SettlementOutcome) for r in outcomes(futures))
        assert world.balances() == {"ada": 0, "bob": 0, "cy": 0}
        assert audit_group(engine, world.group_id).consistent

    @pytest.mark.usefixtures("without_row_locks")
    def test_negative_control_without_locks_the_zero_sum_trigger_refuses_the_commit(
        self, engine: Engine, gate: Gate, ada_and_bob_each_owe_cy_100: World
    ) -> None:
        world = ada_and_bob_each_owe_cy_100
        futures = submit_all(
            [
                lambda: world.settle("ada", "cy", 100, "a"),
                lambda: world.settle("bob", "cy", 100, "b"),
            ]
        )
        try:
            assert gate.wait_for_arrivals(2, timeout=5)
        finally:
            gate.open()

        results = outcomes(futures)
        # Both computed cy = 200 - 100 from the same stale read. The second commit would
        # leave {0, 0, 100}, which does not sum to zero, so the database refuses it.
        assert sum(isinstance(r, SettlementOutcome) for r in results) == 1
        failures = [r for r in results if isinstance(r, IntegrityError)]
        assert len(failures) == 1
        assert "not 0" in str(failures[0])
        assert sorted(world.balances().values()) == [-100, 0, 100]
        assert audit_group(engine, world.group_id).consistent


class TestPayerOverdrawAcrossCreditors:
    def test_one_debt_cannot_be_paid_to_two_creditors_at_once(
        self, engine: Engine, gate: Gate, session_factory: sessionmaker[Session]
    ) -> None:
        """Bob owes 100 in total and tries to pay it to Ada and to Cy simultaneously.

        The two settlements share only the payer's row, so this is the overdraw race on
        the debtor side: Bob's row lock makes the second wait, re-read Bob at 0, and be
        rejected because he no longer owes anything.
        """
        world = World(session_factory, "ada", "bob", "cy", "dee")
        world.expense("ada", 100, "bob")
        world.expense("cy", 100, "dee")
        futures = submit_all(
            [
                lambda: world.settle("bob", "ada", 100, "a"),
                lambda: world.settle("bob", "cy", 100, "c"),
            ]
        )
        try:
            assert gate.wait_for_arrivals(1, timeout=5)
            assert len(blocked_lock_waiters(engine)) == 1
        finally:
            gate.open()

        results = outcomes(futures)
        assert sum(isinstance(r, SettlementOutcome) for r in results) == 1
        rejected = [r for r in results if isinstance(r, SettlementExceedsBalance)]
        assert len(rejected) == 1, results
        assert rejected[0].message == "The payer does not owe anything in this group"
        assert world.balances()["bob"] == 0
        assert audit_group(engine, world.group_id).consistent


class TestDoubleSubmit:
    def test_eight_simultaneous_submissions_of_one_key_apply_exactly_once(
        self, engine: Engine, bob_owes_ada_100: World
    ) -> None:
        world = bob_owes_ada_100
        results = outcomes(submit_all([lambda: world.settle("bob", "ada", 40, "same-key")] * 8))

        assert all(isinstance(r, SettlementOutcome) for r in results), results
        assert len({r.settlement.id for r in results}) == 1
        assert sorted(r.replayed for r in results) == [False] + [True] * 7
        assert world.balances() == {"ada": 60, "bob": -60}
        assert audit_group(engine, world.group_id).consistent

    def test_duplicate_waits_on_the_unique_index_then_replays(
        self, engine: Engine, gate: Gate, bob_owes_ada_100: World
    ) -> None:
        """The duplicate is held by Postgres at INSERT, before it can touch balances."""
        world = bob_owes_ada_100
        futures = submit_all([lambda: world.settle("bob", "ada", 40, "same-key")] * 2)
        try:
            assert gate.wait_for_arrivals(1, timeout=5)
            waiting = blocked_lock_waiters(engine)
            assert len(waiting) == 1
            assert "INSERT INTO settlements" in waiting[0]
        finally:
            gate.open()

        results = outcomes(futures)
        assert sorted(r.replayed for r in results) == [False, True]
        assert world.balances() == {"ada": 60, "bob": -60}
