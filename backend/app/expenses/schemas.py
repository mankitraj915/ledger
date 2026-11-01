from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

# 1e11 cents = 1 billion in major units: far beyond any shared expense, and keeps every
# balance well inside both BIGINT and the 2^53 integers a JavaScript client can hold.
MAX_AMOUNT_CENTS = 100_000_000_000
MAX_PARTICIPANTS = 100

Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


def _require_unique(user_ids: list[int]) -> None:
    if len(set(user_ids)) != len(user_ids):
        raise ValueError("each user may appear only once in a split")


class EqualSplitIn(BaseModel):
    method: Literal["equal"]
    participants: list[int] = Field(min_length=1, max_length=MAX_PARTICIPANTS)

    @model_validator(mode="after")
    def unique_participants(self) -> "EqualSplitIn":
        _require_unique(self.participants)
        return self


class ExactShareIn(BaseModel):
    user_id: int
    amount_cents: int = Field(ge=0, le=MAX_AMOUNT_CENTS)


class ExactSplitIn(BaseModel):
    method: Literal["exact"]
    shares: list[ExactShareIn] = Field(min_length=1, max_length=MAX_PARTICIPANTS)

    @model_validator(mode="after")
    def unique_participants(self) -> "ExactSplitIn":
        _require_unique([share.user_id for share in self.shares])
        return self


class WeightIn(BaseModel):
    user_id: int
    weight: int = Field(gt=0, le=10_000)


class SharesSplitIn(BaseModel):
    method: Literal["shares"]
    shares: list[WeightIn] = Field(min_length=1, max_length=MAX_PARTICIPANTS)

    @model_validator(mode="after")
    def unique_participants(self) -> "SharesSplitIn":
        _require_unique([share.user_id for share in self.shares])
        return self


SplitIn = Annotated[EqualSplitIn | ExactSplitIn | SharesSplitIn, Field(discriminator="method")]


class ExpenseIn(BaseModel):
    description: Description
    amount_cents: int = Field(gt=0, le=MAX_AMOUNT_CENTS)
    paid_by: int
    split: SplitIn


class ExpenseUpdate(ExpenseIn):
    # The version the client last saw. A mismatch means someone else edited it first.
    version: int = Field(ge=1)


class SplitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    share_cents: int
    weight: int | None


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: int
    description: str
    amount_cents: int
    paid_by: int
    split_method: str
    version: int
    created_by: int
    created_at: datetime
    updated_at: datetime
    splits: list[SplitOut]
