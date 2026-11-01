from typing import Annotated

from fastapi import APIRouter, Header, Response, status

from app.auth.deps import CurrentUser
from app.db import SessionDep
from app.errors import BadRequest
from app.settlements import service
from app.settlements.schemas import SettlementIn, SettlementOut

router = APIRouter(prefix="/groups/{group_id}/settlements", tags=["settlements"])

REPLAY_HEADER = "Idempotent-Replayed"


class IdempotencyKeyRequired(BadRequest):
    code = "idempotency_key_required"


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "Replay of an earlier request with the same key"}},
)
def record_settlement(
    group_id: int,
    payload: SettlementIn,
    response: Response,
    session: SessionDep,
    user: CurrentUser,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=1, max_length=255)
    ] = None,
) -> SettlementOut:
    """Record that one member paid another. Requires an ``Idempotency-Key`` header:
    the client generates one key per settle-up attempt and reuses it on retry."""
    if idempotency_key is None:
        raise IdempotencyKeyRequired("The Idempotency-Key header is required")
    outcome = service.record_settlement(session, user.id, group_id, payload, idempotency_key)
    if outcome.replayed:
        response.status_code = status.HTTP_200_OK
        response.headers[REPLAY_HEADER] = "true"
    return SettlementOut.model_validate(outcome.settlement)


@router.get("")
def list_settlements(group_id: int, session: SessionDep, user: CurrentUser) -> list[SettlementOut]:
    settlements = service.list_settlements(session, user.id, group_id)
    return [SettlementOut.model_validate(settlement) for settlement in settlements]
