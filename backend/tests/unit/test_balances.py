import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.ledger.allocation import allocate_equally
from app.ledger.balances import (
    SettlementExceedsBalance,
    Transfer,
    UnbalancedDeltas,
    combine,
    ensure_settleable,
    expense_deltas,
    negate,
    replay,
    settlement_deltas,
    suggest_settlements,
)


def zero_sum_balances() -> st.SearchStrategy[dict[int, int]]:
    """Arbitrary balances for up to 12 members that sum to zero."""

    def close(values: list[int]) -> dict[int, int]:
        balances = {user_id: value for user_id, value in enumerate(values, start=1)}
        balances[len(values) + 1] = -sum(values)
        return balances

    return st.lists(st.integers(-(10**9), 10**9), min_size=1, max_size=11).map(close)


class TestExpenseDeltas:
    def test_payer_is_credited_and_participants_debited(self) -> None:
        assert expense_deltas(1, 300, {1: 100, 2: 100, 3: 100}) == {1: 200, 2: -100, 3: -100}

    def test_payer_need_not_participate(self) -> None:
        assert expense_deltas(1, 300, {2: 150, 3: 150}) == {1: 300, 2: -150, 3: -150}

    def test_shares_not_summing_to_amount_is_a_programming_error(self) -> None:
        with pytest.raises(UnbalancedDeltas):
            expense_deltas(1, 300, {1: 100, 2: 100})

    @given(
        amount=st.integers(1, 10**12),
        participants=st.lists(st.integers(1, 100), min_size=1, max_size=20, unique=True),
        payer=st.integers(1, 100),
    )
    def test_always_sums_to_zero(self, amount: int, participants: list[int], payer: int) -> None:
        deltas = expense_deltas(payer, amount, allocate_equally(amount, participants))
        assert sum(deltas.values()) == 0


class TestSettlementDeltas:
    def test_moves_money_from_payee_claim_to_payer_debt(self) -> None:
        assert settlement_deltas(1, 2, 500) == {1: 500, 2: -500}

    def test_self_settlement_rejected(self) -> None:
        with pytest.raises(UnbalancedDeltas):
            settlement_deltas(1, 1, 500)


class TestCombine:
    def test_editing_an_expense_is_reverse_plus_reapply(self) -> None:
        old = expense_deltas(1, 300, {1: 150, 2: 150})
        new = expense_deltas(1, 300, {1: 100, 2: 100, 3: 100})
        assert combine(negate(old), new) == {1: 50, 2: 50, 3: -100}

    def test_rejects_unbalanced_input(self) -> None:
        with pytest.raises(UnbalancedDeltas):
            combine({1: 5}, {2: -4})


class TestEnsureSettleable:
    def test_paying_full_debt_is_allowed(self) -> None:
        ensure_settleable(payer_balance=-500, payee_balance=500, amount_cents=500)

    def test_partial_payment_is_allowed(self) -> None:
        ensure_settleable(payer_balance=-500, payee_balance=800, amount_cents=200)

    def test_cannot_exceed_payer_debt(self) -> None:
        with pytest.raises(SettlementExceedsBalance) as exc:
            ensure_settleable(payer_balance=-500, payee_balance=800, amount_cents=501)
        assert exc.value.details == {"max_amount_cents": 500}

    def test_cannot_exceed_payee_claim(self) -> None:
        with pytest.raises(SettlementExceedsBalance) as exc:
            ensure_settleable(payer_balance=-800, payee_balance=500, amount_cents=501)
        assert exc.value.details == {"max_amount_cents": 500}

    @pytest.mark.parametrize("payer_balance", [0, 100])
    def test_payer_must_owe_something(self, payer_balance: int) -> None:
        with pytest.raises(SettlementExceedsBalance):
            ensure_settleable(payer_balance=payer_balance, payee_balance=500, amount_cents=1)

    @pytest.mark.parametrize("payee_balance", [0, -100])
    def test_payee_must_be_owed_something(self, payee_balance: int) -> None:
        with pytest.raises(SettlementExceedsBalance):
            ensure_settleable(payer_balance=-500, payee_balance=payee_balance, amount_cents=1)


class TestSuggestSettlements:
    def test_settled_group_needs_no_transfers(self) -> None:
        assert suggest_settlements({1: 0, 2: 0}) == []

    def test_one_debtor_one_creditor(self) -> None:
        assert suggest_settlements({1: -500, 2: 500}) == [Transfer(1, 2, 500)]

    def test_largest_debtor_pays_largest_creditor_first(self) -> None:
        assert suggest_settlements({1: -700, 2: -300, 3: 600, 4: 400}) == [
            Transfer(1, 3, 600),
            Transfer(1, 4, 100),
            Transfer(2, 4, 300),
        ]

    def test_rejects_balances_that_do_not_sum_to_zero(self) -> None:
        with pytest.raises(UnbalancedDeltas):
            suggest_settlements({1: -5, 2: 4})

    @given(balances=zero_sum_balances())
    def test_transfers_settle_everyone_in_at_most_n_minus_one_steps(
        self, balances: dict[int, int]
    ) -> None:
        transfers = suggest_settlements(balances)
        movements = [
            settlement_deltas(t.from_user_id, t.to_user_id, t.amount_cents) for t in transfers
        ]
        after = combine(balances, *movements)
        assert all(value == 0 for value in after.values())
        assert all(t.amount_cents > 0 for t in transfers)
        non_zero = sum(1 for value in balances.values() if value != 0)
        assert len(transfers) <= max(non_zero - 1, 0)

    @given(balances=zero_sum_balances())
    def test_every_suggested_transfer_passes_the_overdraw_rule(
        self, balances: dict[int, int]
    ) -> None:
        current = dict(balances)
        for transfer in suggest_settlements(balances):
            ensure_settleable(
                current[transfer.from_user_id], current[transfer.to_user_id], transfer.amount_cents
            )
            current = combine(
                current,
                settlement_deltas(
                    transfer.from_user_id, transfer.to_user_id, transfer.amount_cents
                ),
            )


def test_replay_accumulates_history() -> None:
    history = [expense_deltas(1, 300, {1: 100, 2: 100, 3: 100}), settlement_deltas(2, 1, 100)]
    assert replay(history) == {1: 100, 2: 0, 3: -100}
