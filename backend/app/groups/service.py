import logging

from psycopg.errors import UniqueViolation
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.db import transaction
from app.errors import Conflict, Forbidden, NotFound
from app.groups.models import Group, Membership
from app.groups.schemas import (
    GroupCreate,
    GroupDetail,
    GroupOut,
    GroupSummary,
    MemberOut,
    TransferOut,
)
from app.ledger.balances import suggest_settlements
from app.ledger.store import lock_group_exclusively

logger = logging.getLogger(__name__)


class AlreadyMember(Conflict):
    code = "already_member"


class GroupNotSettled(Conflict):
    code = "group_not_settled"


def require_membership(session: Session, group_id: int, user_id: int) -> Membership:
    """Authorise access to a group. Non-members get the same 404 as a missing group,
    so group ids cannot be probed for existence."""
    membership = session.get(Membership, (group_id, user_id))
    if membership is None:
        raise NotFound("Group not found")
    return membership


def _get_group(session: Session, group_id: int) -> Group:
    # The group may have been deleted since the membership check ran (READ COMMITTED).
    group = session.get(Group, group_id)
    if group is None:
        raise NotFound("Group not found")
    return group


def create_group(session: Session, actor_id: int, payload: GroupCreate) -> Group:
    group = Group(name=payload.name, currency=payload.currency, created_by=actor_id)
    with transaction(session):
        session.add(group)
        session.flush()
        session.add(Membership(group_id=group.id, user_id=actor_id, balance_cents=0))
    logger.info("group.created", extra={"group_id": group.id, "actor_id": actor_id})
    return group


def list_groups(session: Session, actor_id: int) -> list[GroupSummary]:
    member_count = (
        select(func.count())
        .where(Membership.group_id == Group.id)
        .correlate(Group)
        .scalar_subquery()
    )
    rows = session.execute(
        select(Group, Membership.balance_cents, member_count)
        .join(Membership, Membership.group_id == Group.id)
        .where(Membership.user_id == actor_id)
        .order_by(Group.created_at.desc(), Group.id.desc())
    )
    return [
        GroupSummary(
            **GroupOut.model_validate(group).model_dump(),
            member_count=count,
            my_balance_cents=balance,
        )
        for group, balance, count in rows
    ]


def get_group_detail(session: Session, actor_id: int, group_id: int) -> GroupDetail:
    require_membership(session, group_id, actor_id)
    group = _get_group(session, group_id)
    rows = session.execute(
        select(User.id, User.name, User.email, Membership.balance_cents)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.group_id == group_id)
        .order_by(User.name, User.id)
    )
    members = [
        MemberOut(user_id=user_id, name=name, email=email, balance_cents=balance)
        for user_id, name, email, balance in rows
    ]
    # One statement, one snapshot: these balances are mutually consistent and sum to 0.
    transfers = suggest_settlements({m.user_id: m.balance_cents for m in members})
    return GroupDetail(
        **GroupOut.model_validate(group).model_dump(),
        members=members,
        suggested_settlements=[TransferOut.model_validate(t) for t in transfers],
    )


def rename_group(session: Session, actor_id: int, group_id: int, name: str) -> Group:
    require_membership(session, group_id, actor_id)
    with transaction(session):
        group = _get_group(session, group_id)
        group.name = name
    return group


def add_member(session: Session, actor_id: int, group_id: int, email: str) -> MemberOut:
    require_membership(session, group_id, actor_id)
    user = session.scalars(select(User).where(User.email == email)).one_or_none()
    if user is None:
        raise NotFound("No user with that email")
    try:
        with transaction(session):
            session.add(Membership(group_id=group_id, user_id=user.id, balance_cents=0))
    except IntegrityError as exc:
        if isinstance(exc.orig, UniqueViolation):
            raise AlreadyMember("That user is already a member of this group") from exc
        raise
    logger.info("group.member_added", extra={"group_id": group_id, "user_id": user.id})
    return MemberOut(user_id=user.id, name=user.name, email=user.email, balance_cents=0)


def delete_group(session: Session, actor_id: int, group_id: int) -> None:
    """Delete a fully settled group and its history. Only its creator may do this."""
    require_membership(session, group_id, actor_id)
    with transaction(session):
        # Exclusive group lock: waits for in-flight expenses/settlements (which hold a
        # shared lock on this row) and blocks new ones, so the balances read below
        # cannot change before the DELETE commits.
        group = lock_group_exclusively(session, group_id)
        if group.created_by != actor_id:
            raise Forbidden("Only the group's creator can delete it")
        outstanding = {
            user_id: balance
            for user_id, balance in session.execute(
                select(Membership.user_id, Membership.balance_cents).where(
                    Membership.group_id == group_id, Membership.balance_cents != 0
                )
            )
        }
        if outstanding:
            raise GroupNotSettled(
                "Settle all balances before deleting the group",
                details={"outstanding": outstanding},
            )
        session.delete(group)
    logger.info("group.deleted", extra={"group_id": group_id, "actor_id": actor_id})
