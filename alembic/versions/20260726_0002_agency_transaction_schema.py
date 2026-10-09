"""Add the disabled-by-default travel-agency transaction schema."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260726_0002"
down_revision: Union[str, None] = "20260511_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agency",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'suspended', 'closed')",
            name="ck_agency_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agency_code", name="uq_agency_code"),
    )
    op.create_index("ix_agency_status", "agency", ["status"], unique=False)

    op.create_table(
        "agency_membership",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN "
            "('travel_advisor', 'booking_operator', 'approver', 'finance', "
            "'auditor', 'admin', 'owner')",
            name="ck_agency_membership_role",
        ),
        sa.CheckConstraint(
            "status IN ('invited', 'active', 'suspended', 'revoked')",
            name="ck_agency_membership_status",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agency.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agency_id",
            "user_id",
            name="uq_agency_membership_agency_user",
        ),
    )
    op.create_index(
        "ix_agency_membership_user_status",
        "agency_membership",
        ["user_id", "status"],
        unique=False,
    )

    op.create_table(
        "agency_customer",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('prospect', 'active', 'inactive', 'blocked')",
            name="ck_agency_customer_status",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agency.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agency_id",
            "user_id",
            name="uq_agency_customer_agency_user",
        ),
    )
    op.create_index(
        "ix_agency_customer_user_status",
        "agency_customer",
        ["user_id", "status"],
        unique=False,
    )

    op.create_table(
        "supplier_product",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_code", sa.String(length=64), nullable=False),
        sa.Column("external_product_code", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("product_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("product_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'inactive', 'retired')",
            name="ck_supplier_product_status",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agency.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agency_id",
            "id",
            name="uq_supplier_product_agency_id",
        ),
        sa.UniqueConstraint(
            "agency_id",
            "supplier_code",
            "external_product_code",
            name="uq_supplier_product_supplier_external",
        ),
    )
    op.create_index(
        "ix_supplier_product_agency_type_status",
        "supplier_product",
        ["agency_id", "product_type", "status"],
        unique=False,
    )

    op.create_table(
        "agency_quote",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote_no", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("snapshot_version", sa.String(length=32), nullable=False),
        sa.Column("quote_snapshot", sa.JSON(), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'offered', 'accepted', 'expired', 'cancelled')",
            name="ck_agency_quote_status",
        ),
        sa.CheckConstraint(
            "total_amount >= 0",
            name="ck_agency_quote_amount",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_agency_quote_revision",
        ),
        sa.CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_agency_quote_payload_hash",
        ),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_agency_quote_currency",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agency.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "product_id"],
            ["supplier_product.agency_id", "supplier_product.id"],
            name="fk_agency_quote_product_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agency_id",
            "idempotency_key",
            name="uq_agency_quote_agency_idempotency",
        ),
        sa.UniqueConstraint(
            "agency_id",
            "user_id",
            "id",
            name="uq_agency_quote_agency_user_id",
        ),
        sa.UniqueConstraint("quote_no", name="uq_agency_quote_no"),
    )
    op.create_index(
        "ix_agency_quote_agency_user_status",
        "agency_quote",
        ["agency_id", "user_id", "status", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_agency_quote_agency_status_created",
        "agency_quote",
        ["agency_id", "status", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_agency_quote_valid_until",
        "agency_quote",
        ["valid_until"],
        unique=False,
    )

    op.create_table(
        "agency_order",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_no", sa.String(length=40), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payment_status", sa.String(length=24), nullable=False),
        sa.Column("fulfillment_status", sa.String(length=24), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("quote_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "external_action_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN "
            "('draft', 'pending_review', 'approved', 'review_rejected', "
            "'processing', 'manual_intervention', 'completed', 'failed', "
            "'cancellation_pending', 'cancelled')",
            name="ck_agency_order_status",
        ),
        sa.CheckConstraint(
            "payment_status IN "
            "('not_started', 'pending', 'paid', 'failed', "
            "'partially_refunded', 'refunded')",
            name="ck_agency_order_payment_status",
        ),
        sa.CheckConstraint(
            "fulfillment_status IN "
            "('not_started', 'pending', 'confirmed', 'in_progress', "
            "'completed', 'failed', 'cancelled')",
            name="ck_agency_order_fulfillment_status",
        ),
        sa.CheckConstraint(
            "total_amount >= 0",
            name="ck_agency_order_amount",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_agency_order_revision",
        ),
        sa.CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_agency_order_payload_hash",
        ),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_agency_order_currency",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agency.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "user_id", "quote_id"],
            [
                "agency_quote.agency_id",
                "agency_quote.user_id",
                "agency_quote.id",
            ],
            name="fk_agency_order_quote_tenant_user",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agency_id",
            "idempotency_key",
            name="uq_agency_order_agency_idempotency",
        ),
        sa.UniqueConstraint(
            "agency_id",
            "id",
            name="uq_agency_order_agency_id",
        ),
        sa.UniqueConstraint("order_no", name="uq_agency_order_no"),
        sa.UniqueConstraint("quote_id", name="uq_agency_order_quote"),
    )
    op.create_index(
        "ix_agency_order_agency_user_status",
        "agency_order",
        ["agency_id", "user_id", "status", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_agency_order_agency_status_created",
        "agency_order",
        ["agency_id", "status", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_agency_order_payment_fulfillment",
        "agency_order",
        ["payment_status", "fulfillment_status"],
        unique=False,
    )

    op.create_table(
        "agency_order_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_sequence", sa.Integer(), nullable=False),
        sa.Column("order_revision", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("from_status", sa.String(length=24), nullable=True),
        sa.Column("to_status", sa.String(length=24), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("event_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_sequence >= 1",
            name="ck_agency_order_event_sequence",
        ),
        sa.CheckConstraint(
            "order_revision >= 1",
            name="ck_agency_order_event_revision",
        ),
        sa.CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_agency_order_event_payload_hash",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["user.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agency.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "order_id"],
            ["agency_order.agency_id", "agency_order.id"],
            name="fk_agency_order_event_order_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "order_id",
            "event_sequence",
            name="uq_agency_order_event_sequence",
        ),
    )
    op.create_index(
        "ix_agency_order_event_agency_order_created",
        "agency_order_event",
        ["agency_id", "order_id", "created_at"],
        unique=False,
    )
    op.execute(
        """
        CREATE FUNCTION zhixing_reject_agency_order_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'agency_order_event is append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agency_order_event_append_only
        BEFORE UPDATE OR DELETE ON agency_order_event
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_reject_agency_order_event_mutation()
        """
    )

    op.create_table(
        "idempotency_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(length=80), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column("resource_id", sa.String(length=80), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('in_progress', 'completed', 'failed')",
            name="ck_idempotency_status",
        ),
        sa.CheckConstraint(
            "length(request_hash) = 64",
            name="ck_idempotency_request_hash",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agency.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agency_id",
            "scope",
            "key",
            name="uq_idempotency_agency_scope_key",
        ),
    )
    op.create_index(
        "ix_idempotency_agency_scope_status",
        "idempotency_record",
        ["agency_id", "scope", "status"],
        unique=False,
    )
    op.create_index(
        "ix_idempotency_expires_at",
        "idempotency_record",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "payment_attempt",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("provider_code", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "external_action_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("provider_reference", sa.String(length=160), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN "
            "('not_started', 'approval_required', 'processing', 'succeeded', "
            "'failed', 'cancelled')",
            name="ck_payment_attempt_status",
        ),
        sa.CheckConstraint(
            "amount >= 0",
            name="ck_payment_attempt_amount",
        ),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_payment_attempt_currency",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "order_id"],
            ["agency_order.agency_id", "agency_order.id"],
            name="fk_payment_attempt_order_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "order_id",
            "idempotency_key",
            name="uq_payment_attempt_order_idempotency",
        ),
        sa.UniqueConstraint(
            "order_id",
            "attempt_no",
            name="uq_payment_attempt_order_sequence",
        ),
    )
    op.create_index(
        "ix_payment_attempt_order_status",
        "payment_attempt",
        ["order_id", "status"],
        unique=False,
    )

    op.create_table(
        "fulfillment_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("line_item_key", sa.String(length=80), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("provider_code", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "external_action_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("provider_reference", sa.String(length=160), nullable=True),
        sa.Column("fulfillment_metadata", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN "
            "('not_started', 'approval_required', 'pending', 'confirmed', "
            "'in_progress', 'completed', 'failed', 'cancelled')",
            name="ck_fulfillment_status",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "order_id"],
            ["agency_order.agency_id", "agency_order.id"],
            name="fk_fulfillment_order_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "product_id"],
            ["supplier_product.agency_id", "supplier_product.id"],
            name="fk_fulfillment_product_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "order_id",
            "idempotency_key",
            name="uq_fulfillment_order_idempotency",
        ),
        sa.UniqueConstraint(
            "order_id",
            "line_item_key",
            name="uq_fulfillment_order_line_item",
        ),
    )
    op.create_index(
        "ix_fulfillment_order_status",
        "fulfillment_record",
        ["order_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fulfillment_order_status",
        table_name="fulfillment_record",
    )
    op.drop_table("fulfillment_record")

    op.drop_index(
        "ix_payment_attempt_order_status",
        table_name="payment_attempt",
    )
    op.drop_table("payment_attempt")

    op.drop_index(
        "ix_idempotency_expires_at",
        table_name="idempotency_record",
    )
    op.drop_index(
        "ix_idempotency_agency_scope_status",
        table_name="idempotency_record",
    )
    op.drop_table("idempotency_record")

    op.drop_index(
        "ix_agency_order_event_agency_order_created",
        table_name="agency_order_event",
    )
    op.execute(
        "DROP TRIGGER trg_agency_order_event_append_only "
        "ON agency_order_event"
    )
    op.execute(
        "DROP FUNCTION zhixing_reject_agency_order_event_mutation()"
    )
    op.drop_table("agency_order_event")

    op.drop_index(
        "ix_agency_order_payment_fulfillment",
        table_name="agency_order",
    )
    op.drop_index(
        "ix_agency_order_agency_user_status",
        table_name="agency_order",
    )
    op.drop_index(
        "ix_agency_order_agency_status_created",
        table_name="agency_order",
    )
    op.drop_table("agency_order")

    op.drop_index("ix_agency_quote_valid_until", table_name="agency_quote")
    op.drop_index(
        "ix_agency_quote_agency_user_status",
        table_name="agency_quote",
    )
    op.drop_index(
        "ix_agency_quote_agency_status_created",
        table_name="agency_quote",
    )
    op.drop_table("agency_quote")

    op.drop_index(
        "ix_supplier_product_agency_type_status",
        table_name="supplier_product",
    )
    op.drop_table("supplier_product")

    op.drop_index(
        "ix_agency_customer_user_status",
        table_name="agency_customer",
    )
    op.drop_table("agency_customer")

    op.drop_index(
        "ix_agency_membership_user_status",
        table_name="agency_membership",
    )
    op.drop_table("agency_membership")

    op.drop_index("ix_agency_status", table_name="agency")
    op.drop_table("agency")
