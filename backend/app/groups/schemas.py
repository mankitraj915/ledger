from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

from app.auth.schemas import NormalisedEmail

GroupName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
CurrencyCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z]{3}$"),
    AfterValidator(str.upper),
]


class GroupCreate(BaseModel):
    name: GroupName
    currency: CurrencyCode = "USD"


class GroupRename(BaseModel):
    name: GroupName


class MemberAdd(BaseModel):
    email: NormalisedEmail


class MemberOut(BaseModel):
    user_id: int
    name: str
    email: str
    balance_cents: int


class TransferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_user_id: int
    to_user_id: int
    amount_cents: int


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    currency: str
    created_by: int
    created_at: datetime


class GroupSummary(GroupOut):
    member_count: int
    my_balance_cents: int


class GroupDetail(GroupOut):
    members: list[MemberOut]
    suggested_settlements: list[TransferOut]
