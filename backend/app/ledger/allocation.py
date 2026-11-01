"""Splitting an amount into integer cent shares that sum *exactly* to the total.

Money is always an integer number of minor units (cents). Splitting 100 cents three
ways cannot be done evenly, so some participant must absorb the extra cent; the
rule for who does has to be deterministic, or the same expense would produce
different balances on different runs.
"""

from collections.abc import Mapping, Sequence

from app.errors import Unprocessable

UserId = int


class InvalidSplit(Unprocessable):
    code = "invalid_split"


def allocate_proportionally(total_cents: int, weights: Mapping[UserId, int]) -> dict[UserId, int]:
    """Largest-remainder (Hamilton) apportionment of ``total_cents`` by integer weights.

    Each participant first gets ``floor(total * w / W)``. The cents left over (always
    fewer than the number of participants) go one each to the largest fractional
    remainders, ties broken by ascending user id. The result sums exactly to the
    total and every share is within one cent of its exact proportional value.
    Integer arithmetic throughout: no float ever touches the amount.
    """
    if total_cents <= 0:
        raise InvalidSplit("Amount must be positive")
    if not weights:
        raise InvalidSplit("A split needs at least one participant")
    if any(weight <= 0 for weight in weights.values()):
        raise InvalidSplit("Share weights must be positive")

    weight_sum = sum(weights.values())
    shares: dict[UserId, int] = {}
    remainders: dict[UserId, int] = {}
    for user_id, weight in weights.items():
        shares[user_id], remainders[user_id] = divmod(total_cents * weight, weight_sum)

    leftover = total_cents - sum(shares.values())
    for user_id in sorted(weights, key=lambda u: (-remainders[u], u))[:leftover]:
        shares[user_id] += 1
    return shares


def allocate_equally(total_cents: int, participants: Sequence[UserId]) -> dict[UserId, int]:
    if len(set(participants)) != len(participants):
        raise InvalidSplit("Participants must be unique")
    return allocate_proportionally(total_cents, dict.fromkeys(participants, 1))


def validate_exact(total_cents: int, amounts: Mapping[UserId, int]) -> dict[UserId, int]:
    if total_cents <= 0:
        raise InvalidSplit("Amount must be positive")
    if not amounts:
        raise InvalidSplit("A split needs at least one participant")
    if any(amount < 0 for amount in amounts.values()):
        raise InvalidSplit("Exact shares cannot be negative")
    allocated = sum(amounts.values())
    if allocated != total_cents:
        raise InvalidSplit(
            f"Exact shares sum to {allocated} cents but the expense is {total_cents} cents",
            details={"allocated_cents": allocated, "amount_cents": total_cents},
        )
    return dict(amounts)
