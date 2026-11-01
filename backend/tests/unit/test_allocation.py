import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.ledger.allocation import (
    InvalidSplit,
    allocate_equally,
    allocate_proportionally,
    validate_exact,
)

user_ids = st.integers(min_value=1, max_value=10_000)
totals = st.integers(min_value=1, max_value=10**12)


class TestEqualSplit:
    def test_even_amount_splits_evenly(self) -> None:
        assert allocate_equally(900, [1, 2, 3]) == {1: 300, 2: 300, 3: 300}

    def test_extra_cent_goes_to_lowest_user_id(self) -> None:
        assert allocate_equally(100, [3, 1, 2]) == {1: 34, 2: 33, 3: 33}

    def test_two_extra_cents(self) -> None:
        assert allocate_equally(101, [1, 2, 3]) == {1: 34, 2: 34, 3: 33}

    def test_fewer_cents_than_participants_leaves_zero_shares(self) -> None:
        assert allocate_equally(1, [1, 2, 3]) == {1: 1, 2: 0, 3: 0}

    def test_duplicate_participants_rejected(self) -> None:
        with pytest.raises(InvalidSplit):
            allocate_equally(100, [1, 1])

    def test_no_participants_rejected(self) -> None:
        with pytest.raises(InvalidSplit):
            allocate_equally(100, [])

    @given(total=totals, participants=st.lists(user_ids, min_size=1, max_size=50, unique=True))
    def test_shares_sum_to_total_and_differ_by_at_most_one_cent(
        self, total: int, participants: list[int]
    ) -> None:
        shares = allocate_equally(total, participants)
        assert sum(shares.values()) == total
        assert set(shares) == set(participants)
        assert max(shares.values()) - min(shares.values()) <= 1


class TestProportionalSplit:
    def test_weights(self) -> None:
        assert allocate_proportionally(1000, {1: 1, 2: 3}) == {1: 250, 2: 750}

    def test_largest_remainder_gets_the_leftover_cent(self) -> None:
        # exact: 1: 33.33, 2: 66.66 -> floor 33/66, leftover 1 goes to user 2 (remainder .66)
        assert allocate_proportionally(100, {1: 1, 2: 2}) == {1: 33, 2: 67}

    @pytest.mark.parametrize("weights", [{1: 0}, {1: -1, 2: 3}])
    def test_non_positive_weights_rejected(self, weights: dict[int, int]) -> None:
        with pytest.raises(InvalidSplit):
            allocate_proportionally(100, weights)

    @pytest.mark.parametrize("total", [0, -5])
    def test_non_positive_total_rejected(self, total: int) -> None:
        with pytest.raises(InvalidSplit):
            allocate_proportionally(total, {1: 1})

    @given(
        total=totals,
        weights=st.dictionaries(
            user_ids, st.integers(min_value=1, max_value=1000), min_size=1, max_size=30
        ),
    )
    def test_shares_sum_to_total_and_stay_within_a_cent_of_exact(
        self, total: int, weights: dict[int, int]
    ) -> None:
        shares = allocate_proportionally(total, weights)
        assert sum(shares.values()) == total
        weight_sum = sum(weights.values())
        for user_id, share in shares.items():
            exact_times_w = total * weights[user_id]  # compare share*W against total*w exactly
            assert abs(share * weight_sum - exact_times_w) < weight_sum

    @given(total=totals, weights=st.dictionaries(user_ids, st.integers(1, 50), min_size=1))
    def test_is_deterministic_regardless_of_input_order(
        self, total: int, weights: dict[int, int]
    ) -> None:
        reversed_weights = dict(reversed(list(weights.items())))
        assert allocate_proportionally(total, weights) == allocate_proportionally(
            total, reversed_weights
        )


class TestExactSplit:
    def test_accepts_amounts_that_sum_to_total(self) -> None:
        assert validate_exact(1000, {1: 600, 2: 400}) == {1: 600, 2: 400}

    def test_allows_a_zero_share(self) -> None:
        assert validate_exact(1000, {1: 1000, 2: 0}) == {1: 1000, 2: 0}

    @pytest.mark.parametrize("amounts", [{1: 600, 2: 399}, {1: 600, 2: 401}])
    def test_rejects_amounts_that_do_not_sum_to_total(self, amounts: dict[int, int]) -> None:
        with pytest.raises(InvalidSplit) as exc:
            validate_exact(1000, amounts)
        assert exc.value.details["amount_cents"] == 1000

    def test_rejects_negative_share(self) -> None:
        with pytest.raises(InvalidSplit):
            validate_exact(1000, {1: 1100, 2: -100})
