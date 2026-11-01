"""Reconcile stored balances against the journal they are supposed to summarise.

Stored balances are a cache of history (expenses, splits, settlements). The cache is
only trustworthy if replaying history reproduces it. Sum-to-zero alone does not
prove that: a lost update can leave balances that still sum to zero but disagree
with the journal (see tests/concurrency). This check catches both.

Run against every group:  DATABASE_URL=... python -m app.ledger.audit
(exit status 0 = consistent, 1 = mismatch found, 2 = usage error)
"""

import os
import sys
from dataclasses import dataclass

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.config import normalize_database_url
from app.db import build_engine
from app.expenses.models import Expense, Split
from app.groups.models import Group, Membership
from app.settlements.models import Settlement


@dataclass(frozen=True)
class GroupAudit:
    group_id: int
    stored: dict[int, int]
    journal: dict[int, int]

    @property
    def consistent(self) -> bool:
        return self.stored == self.journal and sum(self.stored.values()) == 0


def _stored_balances(session: Session, group_id: int) -> dict[int, int]:
    rows = session.execute(
        select(Membership.user_id, Membership.balance_cents).where(Membership.group_id == group_id)
    )
    return {user_id: balance for user_id, balance in rows}


def _journal_balances(session: Session, group_id: int) -> dict[int, int]:
    members = select(Membership.user_id).where(Membership.group_id == group_id)
    balances = dict.fromkeys(session.scalars(members), 0)
    in_group = Expense.group_id == group_id
    settled_in_group = Settlement.group_id == group_id
    # Payers of expenses are credited, participants debited; settlement payers are
    # credited (their debt shrinks) and payees debited.
    movements = (
        (
            +1,
            select(Expense.paid_by, func.sum(Expense.amount_cents))
            .where(in_group)
            .group_by(Expense.paid_by),
        ),
        (
            -1,
            select(Split.user_id, func.sum(Split.share_cents))
            .join(Expense)
            .where(in_group)
            .group_by(Split.user_id),
        ),
        (
            +1,
            select(Settlement.payer_id, func.sum(Settlement.amount_cents))
            .where(settled_in_group)
            .group_by(Settlement.payer_id),
        ),
        (
            -1,
            select(Settlement.payee_id, func.sum(Settlement.amount_cents))
            .where(settled_in_group)
            .group_by(Settlement.payee_id),
        ),
    )
    for sign, stmt in movements:
        for user_id, total in session.execute(stmt):
            balances[user_id] = balances.get(user_id, 0) + sign * int(total)
    return balances


def audit_group(engine: Engine, group_id: int) -> GroupAudit:
    # REPEATABLE READ: every query below sees the same snapshot, so concurrent writes
    # cannot make the two sides of the comparison describe different moments.
    snapshot_engine = engine.execution_options(isolation_level="REPEATABLE READ")
    with Session(snapshot_engine) as session:
        return GroupAudit(
            group_id=group_id,
            stored=_stored_balances(session, group_id),
            journal=_journal_balances(session, group_id),
        )


def main() -> int:
    # Only DATABASE_URL: an operations job should not need the token-signing key.
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("Set DATABASE_URL to the database to audit", file=sys.stderr)
        return 2
    engine = build_engine(normalize_database_url(url))
    try:
        with Session(engine) as session:
            group_ids = list(session.scalars(select(Group.id).order_by(Group.id)))
        failures = [
            audit for audit in (audit_group(engine, g) for g in group_ids) if not audit.consistent
        ]
    finally:
        engine.dispose()
    for audit in failures:
        print(f"group {audit.group_id}: stored={audit.stored} journal={audit.journal}")
    print(f"audited {len(group_ids)} groups, {len(failures)} inconsistent")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
