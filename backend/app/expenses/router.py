from typing import Annotated

from fastapi import APIRouter, Query, status

from app.auth.deps import CurrentUser
from app.db import SessionDep
from app.expenses import service
from app.expenses.schemas import ExpenseIn, ExpenseOut, ExpenseUpdate

router = APIRouter(prefix="/groups/{group_id}/expenses", tags=["expenses"])


@router.get("")
def list_expenses(
    group_id: int,
    session: SessionDep,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ExpenseOut]:
    expenses = service.list_expenses(session, user.id, group_id, limit, offset)
    return [ExpenseOut.model_validate(expense) for expense in expenses]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_expense(
    group_id: int, payload: ExpenseIn, session: SessionDep, user: CurrentUser
) -> ExpenseOut:
    return ExpenseOut.model_validate(service.create_expense(session, user.id, group_id, payload))


@router.put("/{expense_id}")
def update_expense(
    group_id: int, expense_id: int, payload: ExpenseUpdate, session: SessionDep, user: CurrentUser
) -> ExpenseOut:
    expense = service.update_expense(session, user.id, group_id, expense_id, payload)
    return ExpenseOut.model_validate(expense)
