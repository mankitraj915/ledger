from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

SPLIT_METHODS = ("equal", "exact", "shares")


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="amount_positive"),
        CheckConstraint(f"split_method IN {SPLIT_METHODS}", name="split_method_known"),
        CheckConstraint("version > 0", name="version_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    description: Mapped[str] = mapped_column(String(200))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    paid_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    split_method: Mapped[str] = mapped_column(String(10))
    # Optimistic concurrency for edits: a client must name the version it edited.
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    splits: Mapped[list["Split"]] = relationship(
        cascade="all, delete-orphan", order_by="Split.user_id", lazy="raise"
    )


class Split(Base):
    __tablename__ = "splits"
    __table_args__ = (
        CheckConstraint("share_cents >= 0", name="share_non_negative"),
        CheckConstraint("weight IS NULL OR weight > 0", name="weight_positive"),
    )

    expense_id: Mapped[int] = mapped_column(
        ForeignKey("expenses.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    share_cents: Mapped[int] = mapped_column(BigInteger)
    # The weight the share was derived from, for the "shares" method only.
    weight: Mapped[int | None] = mapped_column(Integer)
