"""Pure balance arithmetic: the rules every money movement must obey.

Sign convention: a member's balance is what the group owes them.
    balance > 0  -> they are owed money (a creditor)
    balance < 0  -> they owe money (a debtor)
Every money movement is expressed as a set of *deltas* that sum to zero, which is
what keeps a group's balances summing to zero forever.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.errors import Conflict

UserId = int
Deltas = dict[UserId, int]


class UnbalancedDeltas(AssertionError):
    """A movement that would create or destroy money. Always a programming error."""


class SettlementExceedsBalance(Conflict):
    code = "settlement_exceeds_balance"


@dataclass(frozen=True)
class Transfer:
    from_user_id: UserId
    to_user_id: UserId
    amount_cents: int


def assert_zero_sum(deltas: Mapping[UserId, int]) -> None:
    total = sum(deltas.values())
    if total != 0:
        raise UnbalancedDeltas(f"deltas sum to {total}, not 0: {dict(deltas)}")


def expense_deltas(paid_by: UserId, amount_cents: int, shares: Mapping[UserId, int]) -> Deltas:
    """The payer fronted the whole amount; each participant consumed their share."""
    deltas = {user_id: -share for user_id, share in shares.items()}
    deltas[paid_by] = deltas.get(paid_by, 0) + amount_cents
    assert_zero_sum(deltas)  # holds exactly when the shares sum to the amount
    return deltas


def settlement_deltas(payer_id: UserId, payee_id: UserId, amount_cents: int) -> Deltas:
    """The payer handed cash to the payee: the payer's debt shrinks, so does the payee's claim."""
    if payer_id == payee_id:
        raise UnbalancedDeltas("a settlement needs two distinct members")
    return {payer_id: amount_cents, payee_id: -amount_cents}


def combine(*movements: Mapping[UserId, int]) -> Deltas:
    combined: Deltas = {}
    for movement in movements:
        for user_id, delta in movement.items():
            combined[user_id] = combined.get(user_id, 0) + delta
    assert_zero_sum(combined)
    return combined


def negate(deltas: Mapping[UserId, int]) -> Deltas:
    return {user_id: -delta for user_id, delta in deltas.items()}


def ensure_settleable(payer_balance: int, payee_balance: int, amount_cents: int) -> None:
    """The overdraw rule: a settlement may only pay down real, outstanding debt.

    The payer must currently owe money, the payee must currently be owed money, and
    the amount may not exceed either position. So a settlement can never flip a
    sign: nobody ends up owed money because they over-paid, and nobody ends up in
    debt because they were over-paid.
    """
    if payer_balance >= 0:
        raise SettlementExceedsBalance("The payer does not owe anything in this group")
    if payee_balance <= 0:
        raise SettlementExceedsBalance("The payee is not owed anything in this group")
    max_amount = min(-payer_balance, payee_balance)
    if amount_cents > max_amount:
        raise SettlementExceedsBalance(
            f"Settlement of {amount_cents} cents exceeds the {max_amount} cents outstanding",
            details={"max_amount_cents": max_amount},
        )


def suggest_settlements(balances: Mapping[UserId, int]) -> list[Transfer]:
    """A short list of transfers that brings every balance to zero.

    Greedy: repeatedly match the largest debtor with the largest creditor. Each step
    zeroes at least one member, so it needs at most n-1 transfers. Finding the true
    minimum is NP-hard (it contains subset-sum), and n-1 is what people expect.
    Ties are broken by user id so the suggestion is stable between page loads.
    """
    assert_zero_sum(balances)
    debtors = sorted(((-b, u) for u, b in balances.items() if b < 0), key=lambda d: (-d[0], d[1]))
    creditors = sorted(((b, u) for u, b in balances.items() if b > 0), key=lambda c: (-c[0], c[1]))
    transfers: list[Transfer] = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        owed, debtor = debtors[i]
        due, creditor = creditors[j]
        amount = min(owed, due)
        transfers.append(Transfer(debtor, creditor, amount))
        debtors[i] = (owed - amount, debtor)
        creditors[j] = (due - amount, creditor)
        if debtors[i][0] == 0:
            i += 1
        if creditors[j][0] == 0:
            j += 1
    return transfers


def replay(movements: Iterable[Mapping[UserId, int]]) -> Deltas:
    """Recompute balances from history. The audit compares this to the stored balances."""
    balances: Deltas = {}
    for movement in movements:
        for user_id, delta in movement.items():
            balances[user_id] = balances.get(user_id, 0) + delta
    return balances
