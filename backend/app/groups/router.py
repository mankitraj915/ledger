from fastapi import APIRouter, Response, status

from app.auth.deps import CurrentUser
from app.db import SessionDep
from app.groups import service
from app.groups.schemas import (
    GroupCreate,
    GroupDetail,
    GroupOut,
    GroupRename,
    GroupSummary,
    MemberAdd,
    MemberOut,
)

router = APIRouter(prefix="/groups", tags=["groups"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_group(payload: GroupCreate, session: SessionDep, user: CurrentUser) -> GroupOut:
    return GroupOut.model_validate(service.create_group(session, user.id, payload))


@router.get("")
def list_groups(session: SessionDep, user: CurrentUser) -> list[GroupSummary]:
    return service.list_groups(session, user.id)


@router.get("/{group_id}")
def get_group(group_id: int, session: SessionDep, user: CurrentUser) -> GroupDetail:
    return service.get_group_detail(session, user.id, group_id)


@router.patch("/{group_id}")
def rename_group(
    group_id: int, payload: GroupRename, session: SessionDep, user: CurrentUser
) -> GroupOut:
    return GroupOut.model_validate(service.rename_group(session, user.id, group_id, payload.name))


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(group_id: int, session: SessionDep, user: CurrentUser) -> Response:
    service.delete_group(session, user.id, group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{group_id}/members", status_code=status.HTTP_201_CREATED)
def add_member(
    group_id: int, payload: MemberAdd, session: SessionDep, user: CurrentUser
) -> MemberOut:
    return service.add_member(session, user.id, group_id, payload.email)
