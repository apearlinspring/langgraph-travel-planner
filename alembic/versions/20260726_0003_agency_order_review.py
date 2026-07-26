"""Add a strongly bound travel-agency order review."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260726_0003"
down_revision: Union[str, None] = "20260726_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agency_order_review",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("order_revision", sa.Integer(), nullable=False),
        sa.Column("decision_order_revision", sa.Integer(), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "total_amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "requested_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "decided_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_agency_order_review_status",
        ),
        sa.CheckConstraint(
            "order_revision >= 1",
            name="ck_agency_order_review_revision",
        ),
        sa.CheckConstraint(
            "decision_order_revision IS NULL "
            "OR decision_order_revision = order_revision + 1",
            name="ck_agency_order_review_decision_revision",
        ),
        sa.CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_agency_order_review_payload_hash",
        ),
        sa.CheckConstraint(
            "total_amount >= 0",
            name="ck_agency_order_review_amount",
        ),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_agency_order_review_currency",
        ),
        sa.CheckConstraint(
            "decided_by_user_id IS NULL "
            "OR decided_by_user_id <> requested_by_user_id",
            name="ck_agency_order_review_four_eyes",
        ),
        sa.CheckConstraint(
            "(status = 'pending' "
            "AND decided_by_user_id IS NULL "
            "AND decided_at IS NULL "
            "AND decision_reason IS NULL "
            "AND decision_order_revision IS NULL) "
            "OR (status IN ('approved', 'rejected') "
            "AND decided_by_user_id IS NOT NULL "
            "AND decided_at IS NOT NULL "
            "AND decision_order_revision IS NOT NULL)",
            name="ck_agency_order_review_decision_fields",
        ),
        sa.CheckConstraint(
            "status <> 'rejected' "
            "OR (decision_reason IS NOT NULL "
            "AND length(trim(decision_reason)) > 0)",
            name="ck_agency_order_review_rejection_reason",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agency.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "order_id"],
            ["agency_order.agency_id", "agency_order.id"],
            name="fk_agency_order_review_order_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["user.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["user.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agency_id",
            "order_id",
            "order_revision",
            name="uq_agency_order_review_order_revision",
        ),
    )
    op.create_index(
        "ix_agency_order_review_agency_status_created",
        "agency_order_review",
        ["agency_id", "status", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_agency_order_review_order_status",
        "agency_order_review",
        ["order_id", "status"],
        unique=False,
    )
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_agency_order_review_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'agency_order_review cannot be deleted';
            END IF;
            IF OLD.status <> 'pending' THEN
                RAISE EXCEPTION 'terminal agency_order_review is immutable';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.agency_id IS DISTINCT FROM OLD.agency_id
                OR NEW.order_id IS DISTINCT FROM OLD.order_id
                OR NEW.order_revision IS DISTINCT FROM OLD.order_revision
                OR NEW.payload_hash IS DISTINCT FROM OLD.payload_hash
                OR NEW.total_amount IS DISTINCT FROM OLD.total_amount
                OR NEW.currency IS DISTINCT FROM OLD.currency
                OR NEW.requested_by_user_id
                    IS DISTINCT FROM OLD.requested_by_user_id
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'agency_order_review binding is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agency_order_review_mutation_guard
        BEFORE UPDATE OR DELETE ON agency_order_review
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_guard_agency_order_review_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_agency_order_review_mutation_guard "
        "ON agency_order_review"
    )
    op.execute(
        "DROP FUNCTION zhixing_guard_agency_order_review_mutation()"
    )
    op.drop_index(
        "ix_agency_order_review_order_status",
        table_name="agency_order_review",
    )
    op.drop_index(
        "ix_agency_order_review_agency_status_created",
        table_name="agency_order_review",
    )
    op.drop_table("agency_order_review")
