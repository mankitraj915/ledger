"""The only code allowed to change a stored balance.

Every money movement (adding or editing an expense, recording a settlement) runs in
one READ COMMITTED transaction that:

  1. locks the rows it is about to change,
  2. re-reads them *after* the lock is granted,
  3. validates against those fresh values,
  4. writes, and commits (releasing the locks).

Lock hierarchy. Transactions that write money take locks in this fixed order, which
is what makes a deadlock between any two of them impossible:

  1. the group row      FOR KEY SHARE by money writers (shared: they do not block
                        each other); FOR UPDATE by group deletion (exclusive).
  2. the expense row    FOR UPDATE, for expense edits only.
  3. membership rows    FOR UPDATE, in ascending user_id order.
"""

from collections.abc import Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import NotFound, Unprocessable
from app.groups.models import Group, Membership
from app.ledger.balances import UserId, assert_zero_sum


class NotGroupMembers(Unprocessable):
    code = "not_group_member"


def lock_group_for_money_write(session: Session, group_id: int) -> Group:
    """Shared lock on the group row: concurrent money writers proceed, deletion waits.

    Also turns "the group was deleted while this request was in flight" into a clean
    404: a row deleted by a committed transaction is simply not returned.
    """
    stmt = select(Group).where(Group.id == group_id).with_for_update(read=True, key_share=True)
    group = session.scalars(stmt).one_or_none()
    if group is None:
        raise NotFound("Group not found")
    return group


def lock_group_exclusively(session: Session, group_id: int) -> Group:
    """Exclusive lock on the group row: waits for every in-flight money writer to finish."""
    stmt = (
        select(Group)
        .where(Group.id == group_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    group = session.scalars(stmt).one_or_none()
    if group is None:
        raise NotFound("Group not found")
    return group


def lock_balances(
    session: Session, group_id: int, user_ids: Iterable[UserId]
) -> dict[UserId, Membership]:
    """``SELECT ... FOR UPDATE`` the given members' balance rows, in user_id order.

    * Order: Postgres places the LockRows step above the Sort, so rows are locked in
      ORDER BY order. Two transactions touching {A, B} both lock A first, so neither
      can hold B while waiting for A.
    * populate_existing: the session may already hold one of these Membership objects
      (the authorisation check loads the caller's own row). Without this option the
      ORM would hand back that cached instance with its *pre-lock* balance, and the
      lock would protect nothing.
    * Raises NotGroupMembers if any user has no membership in the group.
    """
    wanted = sorted(set(user_ids))
    stmt = (
        select(Membership)
        .where(Membership.group_id == group_id, Membership.user_id.in_(wanted))
        .order_by(Membership.user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    locked = {membership.user_id: membership for membership in session.scalars(stmt)}
    missing = [user_id for user_id in wanted if user_id not in locked]
    if missing:
        raise NotGroupMembers(
            "Every payer, payee and participant must be a member of the group",
            details={"user_ids": missing},
        )
    return locked


def apply_deltas(locked: Mapping[UserId, Membership], deltas: Mapping[UserId, int]) -> None:
    """Apply a zero-sum movement to balance rows this transaction has locked."""
    assert_zero_sum(deltas)
    unlocked = deltas.keys() - locked.keys()
    if unlocked:
        raise RuntimeError(f"refusing to change balances that are not locked: {sorted(unlocked)}")
    for user_id, delta in deltas.items():
        locked[user_id].balance_cents += delta
