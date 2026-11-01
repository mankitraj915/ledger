from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.expenses.schemas import MAX_AMOUNT_CENTS


class SettlementIn(BaseModel):
    payer_id: int
    payee_id: int
    amount_cents: int = Field(gt=0, le=MAX_AMOUNT_CENTS)

    @model_validator(mode="after")
    def distinct_parties(self) -> "SettlementIn":
        if self.payer_id == self.payee_id:
            raise ValueError("payer and payee must be different members")
        return self


class SettlementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: int
    payer_id: int
    payee_id: int
    amount_cents: int
    created_by: int
    created_at: datetime
