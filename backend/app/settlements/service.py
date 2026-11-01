"""Recording a settlement: exactly once, atomically, never beyond what is owed.

Three races are closed here, each by the database rather than by application checks:

* Double submit (same Idempotency-Key, possibly concurrent). The key is claimed with
  INSERT ... ON CONFLICT DO NOTHING against a unique index. If another transaction
  has inserted the same key but not yet committed, Postgres makes our INSERT *wait*
  for it; if it commits we get no row back and replay its result, if it rolls back
  our INSERT proceeds. A SELECT-then-INSERT check would let both through.

* Lost update / overdraw (different keys, same balances). Two settlements against
  one debt must not both read "owes 100" and both pay 100. The payer's and payee's
  balance rows are locked FOR UPDATE (in user_id order, so A->B and B->A cannot
  deadlock) and re-read after the lock is granted, and the overdraw rule is checked
  against those fresh values. The second transaction blocks until the first
  commits, then sees the updated balance and is rejected.

* Atomicity. The settlement row and both balance changes commit together or not at
  all; a deferred trigger additionally refuses any commit that breaks zero-sum.
"""

import hashlib
import json
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db import transaction
from app.errors import Forbidden, Unprocessable
from app.groups.service import require_membership
from app.ledger.balances import SettlementExceedsBalance, ensure_settleable, settlement_deltas
from app.ledger.store import apply_deltas, lock_balances, lock_group_for_money_write
from app.settlements.models import Settlement
from app.settlements.schemas import SettlementIn

logger = logging.getLogger(__name__)


class IdempotencyKeyReused(Unprocessable):
    code = "idempotency_key_reused"


@dataclass(frozen=True)
class SettlementOutcome:
    settlement: Settlement
    replayed: bool


def fingerprint(group_id: int, payload: SettlementIn) -> str:
    canonical = json.dumps({"group_id": group_id, **payload.model_dump()}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def record_settlement(
    session: Session, actor_id: int, group_id: int, payload: SettlementIn, idempotency_key: str
) -> SettlementOutcome:
    require_membership(session, group_id, actor_id)
    if actor_id not in (payload.payer_id, payload.payee_id):
        raise Forbidden("You can only record a settlement you are paying or receiving")
    request_fingerprint = fingerprint(group_id, payload)

    with transaction(session):
        lock_group_for_money_write(session, group_id)
        settlement = _claim_idempotency_key(
            session, actor_id, group_id, payload, idempotency_key, request_fingerprint
        )
        if settlement is not None:
            locked = lock_balances(session, group_id, {payload.payer_id, payload.payee_id})
            try:
                ensure_settleable(
                    payer_balance=locked[payload.payer_id].balance_cents,
                    payee_balance=locked[payload.payee_id].balance_cents,
                    amount_cents=payload.amount_cents,
                )
            except SettlementExceedsBalance:
                logger.info(
                    "settlement.rejected",
                    extra={"group_id": group_id, "amount_cents": payload.amount_cents},
                )
                raise
            apply_deltas(
                locked,
                settlement_deltas(payload.payer_id, payload.payee_id, payload.amount_cents),
            )

    if settlement is None:
        replayed = _replay(session, actor_id, idempotency_key, request_fingerprint)
        logger.info("settlement.replayed", extra={"settlement_id": replayed.id})
        return SettlementOutcome(replayed, replayed=True)

    logger.info(
        "settlement.created",
        extra={
            "settlement_id": settlement.id,
            "group_id": group_id,
            "amount_cents": settlement.amount_cents,
        },
    )
    return SettlementOutcome(settlement, replayed=False)


def list_settlements(session: Session, actor_id: int, group_id: int) -> list[Settlement]:
    require_membership(session, group_id, actor_id)
    stmt = (
        select(Settlement)
        .where(Settlement.group_id == group_id)
        .order_by(Settlement.created_at.desc(), Settlement.id.desc())
    )
    return list(session.scalars(stmt))


def _claim_idempotency_key(
    session: Session,
    actor_id: int,
    group_id: int,
    payload: SettlementIn,
    idempotency_key: str,
    request_fingerprint: str,
) -> Settlement | None:
    """Insert the settlement row, or return None if this key was already used."""
    stmt = (
        insert(Settlement)
        .values(
            group_id=group_id,
            payer_id=payload.payer_id,
            payee_id=payload.payee_id,
            amount_cents=payload.amount_cents,
            created_by=actor_id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        .on_conflict_do_nothing(index_elements=["created_by", "idempotency_key"])
        .returning(Settlement)
    )
    return session.scalars(stmt).one_or_none()


def _replay(
    session: Session, actor_id: int, idempotency_key: str, request_fingerprint: str
) -> Settlement:
    # A fresh statement in a fresh transaction: under READ COMMITTED it sees the row
    # that the conflicting (and by now committed) transaction inserted.
    original = session.scalars(
        select(Settlement).where(
            Settlement.created_by == actor_id, Settlement.idempotency_key == idempotency_key
        )
    ).one_or_none()
    if original is None or original.request_fingerprint != request_fingerprint:
        raise IdempotencyKeyReused("This Idempotency-Key was already used for a different request")
    return original
