from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Group(Base):
    __tablename__ = "groups"
    __table_args__ = (CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso_4217"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    # One currency per group: balances in different currencies cannot be netted.
    currency: Mapped[str] = mapped_column(String(3))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Membership(Base):
    """A member of a group and their materialised balance within it.

    ``balance_cents`` is a running total of every expense and settlement in the
    journal. It is only ever changed through ``app.ledger.store`` while the row is
    locked, and a deferred trigger checks at commit that the group still sums to 0.
    """

    __tablename__ = "memberships"

    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True, index=True)
    balance_cents: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
