"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-02 02:41:52.257440
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Defence in depth for the zero-sum invariant. The application already refuses to
# apply deltas that do not sum to zero (app.ledger.balances.assert_zero_sum); this
# trigger makes the database refuse to COMMIT any transaction that leaves a group's
# balances not summing to zero, whatever code path or manual SQL produced it.
# DEFERRABLE INITIALLY DEFERRED: individual UPDATEs inside a transaction are allowed
# to be transiently unbalanced; the check runs once per touched row at COMMIT.
ASSERT_GROUP_BALANCED = """
CREATE FUNCTION assert_group_balanced() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target_group bigint := COALESCE(NEW.group_id, OLD.group_id);
    total bigint;
BEGIN
    SELECT COALESCE(SUM(balance_cents), 0) INTO total
    FROM memberships WHERE group_id = target_group;
    IF total <> 0 THEN
        RAISE EXCEPTION 'balances of group % sum to %, not 0', target_group, total
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END
$$;

CREATE CONSTRAINT TRIGGER memberships_group_balanced
    AFTER INSERT OR UPDATE OF balance_cents OR DELETE ON memberships
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION assert_group_balanced();
"""


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "groups",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_groups_currency_iso_4217")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_groups_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_groups")),
    )
    op.create_table(
        "expenses",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("group_id", sa.BigInteger(), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("paid_by", sa.BigInteger(), nullable=False),
        sa.Column("split_method", sa.String(length=10), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "split_method IN ('equal', 'exact', 'shares')",
            name=op.f("ck_expenses_split_method_known"),
        ),
        sa.CheckConstraint("amount_cents > 0", name=op.f("ck_expenses_amount_positive")),
        sa.CheckConstraint("version > 0", name=op.f("ck_expenses_version_positive")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_expenses_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name=op.f("fk_expenses_group_id_groups"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["paid_by"], ["users.id"], name=op.f("fk_expenses_paid_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expenses")),
    )
    op.create_index(op.f("ix_expenses_group_id"), "expenses", ["group_id"], unique=False)
    op.create_table(
        "memberships",
        sa.Column("group_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("balance_cents", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name=op.f("fk_memberships_group_id_groups"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_memberships_user_id_users")
        ),
        sa.PrimaryKeyConstraint("group_id", "user_id", name=op.f("pk_memberships")),
    )
    op.create_index(op.f("ix_memberships_user_id"), "memberships", ["user_id"], unique=False)
    op.create_table(
        "settlements",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("group_id", sa.BigInteger(), nullable=False),
        sa.Column("payer_id", sa.BigInteger(), nullable=False),
        sa.Column("payee_id", sa.BigInteger(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount_cents > 0", name=op.f("ck_settlements_amount_positive")),
        sa.CheckConstraint("payer_id <> payee_id", name=op.f("ck_settlements_distinct_parties")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_settlements_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name=op.f("fk_settlements_group_id_groups"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payee_id"], ["users.id"], name=op.f("fk_settlements_payee_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["payer_id"], ["users.id"], name=op.f("fk_settlements_payer_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_settlements")),
        sa.UniqueConstraint(
            "created_by", "idempotency_key", name=op.f("uq_settlements_created_by_idempotency_key")
        ),
    )
    op.create_index(op.f("ix_settlements_group_id"), "settlements", ["group_id"], unique=False)
    op.create_table(
        "splits",
        sa.Column("expense_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("share_cents", sa.BigInteger(), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=True),
        sa.CheckConstraint("share_cents >= 0", name=op.f("ck_splits_share_non_negative")),
        sa.CheckConstraint("weight IS NULL OR weight > 0", name=op.f("ck_splits_weight_positive")),
        sa.ForeignKeyConstraint(
            ["expense_id"],
            ["expenses.id"],
            name=op.f("fk_splits_expense_id_expenses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_splits_user_id_users")),
        sa.PrimaryKeyConstraint("expense_id", "user_id", name=op.f("pk_splits")),
    )
    op.execute(ASSERT_GROUP_BALANCED)


def downgrade() -> None:
    op.execute("DROP TRIGGER memberships_group_balanced ON memberships")
    op.execute("DROP FUNCTION assert_group_balanced()")
    op.drop_table("splits")
    op.drop_index(op.f("ix_settlements_group_id"), table_name="settlements")
    op.drop_table("settlements")
    op.drop_index(op.f("ix_memberships_user_id"), table_name="memberships")
    op.drop_table("memberships")
    op.drop_index(op.f("ix_expenses_group_id"), table_name="expenses")
    op.drop_table("expenses")
    op.drop_table("groups")
    op.drop_table("users")
