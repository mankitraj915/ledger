import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import transaction
from app.errors import Conflict, NotFound
from app.expenses.models import Expense, Split
from app.expenses.schemas import EqualSplitIn, ExactSplitIn, ExpenseIn, ExpenseUpdate, SplitIn
from app.groups.service import require_membership
from app.ledger.allocation import allocate_equally, allocate_proportionally, validate_exact
from app.ledger.balances import combine, expense_deltas, negate
from app.ledger.store import apply_deltas, lock_balances, lock_group_for_money_write

logger = logging.getLogger(__name__)


class StaleExpenseVersion(Conflict):
    code = "stale_version"


@dataclass(frozen=True)
class Allocation:
    """How an expense's amount is divided: cents per user, plus the weights if any."""

    shares: dict[int, int]
    weights: dict[int, int] | None = None

    def splits(self) -> list[Split]:
        return [
            Split(
                user_id=user_id,
                share_cents=share,
                weight=self.weights[user_id] if self.weights else None,
            )
            for user_id, share in sorted(self.shares.items())
        ]


def allocate(amount_cents: int, split: SplitIn) -> Allocation:
    if isinstance(split, EqualSplitIn):
        return Allocation(allocate_equally(amount_cents, split.participants))
    if isinstance(split, ExactSplitIn):
        return Allocation(
            validate_exact(amount_cents, {s.user_id: s.amount_cents for s in split.shares})
        )
    weights = {s.user_id: s.weight for s in split.shares}
    return Allocation(allocate_proportionally(amount_cents, weights), weights)


def list_expenses(
    session: Session, actor_id: int, group_id: int, limit: int, offset: int
) -> list[Expense]:
    require_membership(session, group_id, actor_id)
    stmt = (
        select(Expense)
        .where(Expense.group_id == group_id)
        .options(selectinload(Expense.splits))
        .order_by(Expense.created_at.desc(), Expense.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(stmt))


def create_expense(session: Session, actor_id: int, group_id: int, payload: ExpenseIn) -> Expense:
    require_membership(session, group_id, actor_id)
    allocation = allocate(payload.amount_cents, payload.split)
    deltas = expense_deltas(payload.paid_by, payload.amount_cents, allocation.shares)

    with transaction(session):
        lock_group_for_money_write(session, group_id)
        # Lock everyone named, not just non-zero deltas: a participant whose share
        # rounds to 0 cents must still be validated as a member.
        locked = lock_balances(session, group_id, {payload.paid_by, *allocation.shares})
        apply_deltas(locked, deltas)
        expense = Expense(
            group_id=group_id,
            description=payload.description,
            amount_cents=payload.amount_cents,
            paid_by=payload.paid_by,
            split_method=payload.split.method,
            created_by=actor_id,
            splits=allocation.splits(),
        )
        session.add(expense)
    logger.info(
        "expense.created",
        extra={
            "expense_id": expense.id,
            "group_id": group_id,
            "amount_cents": expense.amount_cents,
        },
    )
    return expense


def update_expense(
    session: Session, actor_id: int, group_id: int, expense_id: int, payload: ExpenseUpdate
) -> Expense:
    """Edit = reverse the old movement and apply the new one, atomically."""
    require_membership(session, group_id, actor_id)
    allocation = allocate(payload.amount_cents, payload.split)
    new = expense_deltas(payload.paid_by, payload.amount_cents, allocation.shares)

    with transaction(session):
        lock_group_for_money_write(session, group_id)
        # Lock the expense before reading its splits. Two concurrent edits that both
        # read the old splits and then both reversed them would reverse it twice.
        expense = _lock_expense(session, group_id, expense_id)
        if expense.version != payload.version:
            raise StaleExpenseVersion(
                "This expense was changed by someone else; reload and try again",
                details={"current_version": expense.version},
            )
        old_shares = {split.user_id: split.share_cents for split in expense.splits}
        old = expense_deltas(expense.paid_by, expense.amount_cents, old_shares)
        locked = lock_balances(
            session,
            group_id,
            {expense.paid_by, *old_shares, payload.paid_by, *allocation.shares},
        )
        apply_deltas(locked, combine(negate(old), new))

        expense.description = payload.description
        expense.amount_cents = payload.amount_cents
        expense.paid_by = payload.paid_by
        expense.split_method = payload.split.method
        expense.version += 1
        expense.splits = allocation.splits()
    logger.info(
        "expense.updated",
        extra={"expense_id": expense.id, "group_id": group_id, "version": expense.version},
    )
    return expense


def _lock_expense(session: Session, group_id: int, expense_id: int) -> Expense:
    stmt = (
        select(Expense)
        .where(Expense.id == expense_id, Expense.group_id == group_id)
        .with_for_update(of=Expense)
        # The splits are loaded by a second SELECT issued after the lock is granted,
        # so they reflect any edit that committed while we were waiting.
        .options(selectinload(Expense.splits))
        .execution_options(populate_existing=True)
    )
    expense = session.scalars(stmt).one_or_none()
    if expense is None:
        raise NotFound("Expense not found")
    return expense
