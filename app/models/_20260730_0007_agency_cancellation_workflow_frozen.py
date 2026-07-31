"""`20260730_0007` 的 revision-frozen 取消域 schema 与 Alembic 编排。

该模块只属于 0007 revision。发布后不得随应用模型演进而修改；后续数据库
变化必须新增 revision。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.models._20260730_0007_agency_cancellation_workflow_guards_frozen import (
    create_0007_cancellation_guards,
    drop_0007_cancellation_guards,
    drop_order_mutation_guard,
    restore_0004_order_mutation_guard,
)


UUID = postgresql.UUID(as_uuid=True)
TIMESTAMP = sa.DateTime(timezone=True)


def _case_binding_columns() -> list[str]:
    return [
        "agency_id",
        "branch_id",
        "order_id",
        "customer_id",
        "cancellation_case_id",
    ]


def _case_binding_targets() -> list[str]:
    return [
        "agency_order_cancellation_case.agency_id",
        "agency_order_cancellation_case.branch_id",
        "agency_order_cancellation_case.order_id",
        "agency_order_cancellation_case.customer_id",
        "agency_order_cancellation_case.id",
    ]


def _create_case_table() -> None:
    op.create_table(
        "agency_order_cancellation_case",
        sa.Column("id", UUID, nullable=False),
        sa.Column("agency_id", UUID, nullable=False),
        sa.Column("branch_id", UUID, nullable=False),
        sa.Column("order_id", UUID, nullable=False),
        sa.Column("customer_id", UUID, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("order_revision_at_request", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("reason_detail", sa.String(500), nullable=True),
        sa.Column(
            "supplier_cancel_required",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "refund_required",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "approved_refund_amount",
            sa.Numeric(18, 2),
            nullable=True,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("requested_by_user_id", UUID, nullable=False),
        sa.Column("requested_at", TIMESTAMP, nullable=False),
        sa.Column("review_decision", sa.String(20), nullable=True),
        sa.Column("reviewed_by_user_id", UUID, nullable=True),
        sa.Column("reviewed_at", TIMESTAMP, nullable=True),
        sa.Column("review_note", sa.String(500), nullable=True),
        sa.Column(
            "external_action_triggered",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("completed_at", TIMESTAMP, nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_agency_order_cancellation_case",
        ),
        sa.UniqueConstraint(
            "agency_id",
            "branch_id",
            "order_id",
            "customer_id",
            "id",
            name="uq_agency_order_cancellation_case_binding",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "branch_id", "customer_id", "order_id"],
            [
                "agency_order.agency_id",
                "agency_order.branch_id",
                "agency_order.customer_id",
                "agency_order.id",
            ],
            name="fk_agency_order_cancellation_case_order",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["user.id"],
            name="fk_agency_order_cancellation_case_requester",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["user.id"],
            name="fk_agency_order_cancellation_case_reviewer",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN "
            "('approval_pending', 'rejected', 'action_pending', "
            "'reconciliation_pending', 'manual_intervention', 'completed')",
            name="ck_agency_order_cancellation_case_status",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_agency_order_cancellation_case_revision",
        ),
        sa.CheckConstraint(
            "order_revision_at_request >= 1",
            name="ck_agency_order_cancellation_case_order_revision",
        ),
        sa.CheckConstraint(
            "reason_code IN "
            "('customer_request', 'customer_consent_withdrawn', "
            "'agency_unable_to_fulfill', 'supplier_unavailable', "
            "'duplicate_order', 'pricing_or_booking_error', "
            "'force_majeure', 'compliance_or_risk')",
            name="ck_agency_order_cancellation_case_reason_code",
        ),
        sa.CheckConstraint(
            "reason_detail IS NULL "
            "OR (length(trim(reason_detail)) BETWEEN 1 AND 500)",
            name="ck_agency_order_cancellation_case_reason_detail",
        ),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_agency_order_cancellation_case_currency",
        ),
        sa.CheckConstraint(
            "approved_refund_amount IS NULL "
            "OR approved_refund_amount >= 0",
            name="ck_agency_order_cancellation_case_refund_amount",
        ),
        sa.CheckConstraint(
            "NOT external_action_triggered",
            name="ck_agency_order_cancellation_case_external_action",
        ),
        sa.CheckConstraint(
            "reviewed_by_user_id IS NULL "
            "OR reviewed_by_user_id <> requested_by_user_id",
            name="ck_agency_order_cancellation_case_four_eyes",
        ),
        sa.CheckConstraint(
            "review_note IS NULL "
            "OR (length(trim(review_note)) BETWEEN 1 AND 500)",
            name="ck_agency_order_cancellation_case_review_note",
        ),
        sa.CheckConstraint(
            "(status = 'approval_pending' "
            "AND review_decision IS NULL "
            "AND reviewed_by_user_id IS NULL "
            "AND reviewed_at IS NULL "
            "AND approved_refund_amount IS NULL "
            "AND completed_at IS NULL) "
            "OR (status = 'rejected' "
            "AND review_decision IS NOT NULL "
            "AND review_decision = 'rejected' "
            "AND reviewed_by_user_id IS NOT NULL "
            "AND reviewed_at IS NOT NULL "
            "AND approved_refund_amount IS NULL "
            "AND completed_at IS NULL) "
            "OR (status IN "
            "('action_pending', 'reconciliation_pending', "
            "'manual_intervention') "
            "AND review_decision IS NOT NULL "
            "AND review_decision = 'approved' "
            "AND reviewed_by_user_id IS NOT NULL "
            "AND reviewed_at IS NOT NULL "
            "AND completed_at IS NULL) "
            "OR (status = 'completed' "
            "AND review_decision IS NOT NULL "
            "AND review_decision = 'approved' "
            "AND reviewed_by_user_id IS NOT NULL "
            "AND reviewed_at IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name="ck_agency_order_cancellation_case_review_shape",
        ),
        sa.CheckConstraint(
            "(refund_required "
            "AND (review_decision <> 'approved' "
            "OR approved_refund_amount IS NOT NULL)) "
            "OR (NOT refund_required AND approved_refund_amount IS NULL)",
            name="ck_agency_order_cancellation_case_refund_shape",
        ),
        sa.CheckConstraint(
            "status NOT IN "
            "('action_pending', 'reconciliation_pending', "
            "'manual_intervention') "
            "OR supplier_cancel_required OR refund_required",
            name="ck_agency_order_cancellation_case_action_required",
        ),
    )
    op.create_index(
        "uq_agency_order_cancellation_case_open",
        "agency_order_cancellation_case",
        ["agency_id", "order_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('approval_pending', 'action_pending', "
            "'reconciliation_pending', 'manual_intervention')"
        ),
    )
    op.create_index(
        "ix_agency_order_cancellation_case_branch_status",
        "agency_order_cancellation_case",
        ["agency_id", "branch_id", "status", "created_at", "id"],
    )
    op.create_index(
        "ix_agency_order_cancellation_case_customer",
        "agency_order_cancellation_case",
        ["agency_id", "branch_id", "customer_id", "created_at", "id"],
    )


def _create_event_table() -> None:
    op.create_table(
        "agency_order_cancellation_event",
        sa.Column("id", UUID, nullable=False),
        sa.Column("agency_id", UUID, nullable=False),
        sa.Column("branch_id", UUID, nullable=False),
        sa.Column("order_id", UUID, nullable=False),
        sa.Column("customer_id", UUID, nullable=False),
        sa.Column("cancellation_case_id", UUID, nullable=False),
        sa.Column("event_sequence", sa.Integer(), nullable=False),
        sa.Column("case_revision", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_user_id", UUID, nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("event_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_agency_order_cancellation_event",
        ),
        sa.UniqueConstraint(
            "agency_id",
            "branch_id",
            "order_id",
            "customer_id",
            "cancellation_case_id",
            "event_sequence",
            name="uq_agency_order_cancellation_event_sequence",
        ),
        sa.ForeignKeyConstraint(
            _case_binding_columns(),
            _case_binding_targets(),
            name="fk_agency_order_cancellation_event_case",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["user.id"],
            name="fk_agency_order_cancellation_event_actor",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "event_sequence >= 1",
            name="ck_agency_order_cancellation_event_sequence",
        ),
        sa.CheckConstraint(
            "case_revision >= 1",
            name="ck_agency_order_cancellation_event_revision",
        ),
        sa.CheckConstraint(
            "length(trim(event_type)) BETWEEN 1 AND 64",
            name="ck_agency_order_cancellation_event_type",
        ),
        sa.CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_agency_order_cancellation_event_payload_hash",
        ),
    )
    op.create_index(
        "ix_agency_order_cancellation_event_case_created",
        "agency_order_cancellation_event",
        ["agency_id", "cancellation_case_id", "created_at", "id"],
    )


def _create_compensation_table() -> None:
    op.create_table(
        "agency_order_compensation_record",
        sa.Column("id", UUID, nullable=False),
        sa.Column("agency_id", UUID, nullable=False),
        sa.Column("branch_id", UUID, nullable=False),
        sa.Column("order_id", UUID, nullable=False),
        sa.Column("customer_id", UUID, nullable=False),
        sa.Column("cancellation_case_id", UUID, nullable=False),
        sa.Column("record_sequence", sa.Integer(), nullable=False),
        sa.Column("case_revision", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(24), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("external_reference_hash", sa.String(64), nullable=True),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("occurred_at", TIMESTAMP, nullable=False),
        sa.Column("recorded_by_user_id", UUID, nullable=False),
        sa.Column(
            "system_external_action_triggered",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_agency_order_compensation_record",
        ),
        sa.UniqueConstraint(
            "agency_id",
            "branch_id",
            "order_id",
            "customer_id",
            "cancellation_case_id",
            "id",
            name="uq_agency_order_compensation_record_binding",
        ),
        sa.UniqueConstraint(
            "agency_id",
            "branch_id",
            "order_id",
            "customer_id",
            "cancellation_case_id",
            "record_sequence",
            name="uq_agency_order_compensation_record_sequence",
        ),
        sa.ForeignKeyConstraint(
            _case_binding_columns(),
            _case_binding_targets(),
            name="fk_agency_order_compensation_record_case",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_user_id"],
            ["user.id"],
            name="fk_agency_order_compensation_record_recorder",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "record_sequence >= 1",
            name="ck_agency_order_compensation_record_sequence",
        ),
        sa.CheckConstraint(
            "case_revision >= 1",
            name="ck_agency_order_compensation_record_revision",
        ),
        sa.CheckConstraint(
            "action_type IN ('supplier_cancel', 'refund')",
            name="ck_agency_order_compensation_record_action",
        ),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'failed', 'unknown')",
            name="ck_agency_order_compensation_record_outcome",
        ),
        sa.CheckConstraint(
            "amount >= 0",
            name="ck_agency_order_compensation_record_amount",
        ),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_agency_order_compensation_record_currency",
        ),
        sa.CheckConstraint(
            "external_reference_hash IS NULL "
            "OR length(external_reference_hash) = 64",
            name="ck_agency_order_compensation_record_reference_hash",
        ),
        sa.CheckConstraint(
            "length(evidence_hash) = 64",
            name="ck_agency_order_compensation_record_evidence_hash",
        ),
        sa.CheckConstraint(
            "NOT system_external_action_triggered",
            name="ck_agency_order_compensation_record_external_action",
        ),
        sa.CheckConstraint(
            "action_type <> 'supplier_cancel' OR amount = 0",
            name="ck_agency_order_compensation_record_supplier_amount",
        ),
    )
    op.create_index(
        "ix_agency_order_compensation_record_case_action",
        "agency_order_compensation_record",
        ["agency_id", "cancellation_case_id", "action_type", "record_sequence"],
    )


def _create_reconciliation_table() -> None:
    op.create_table(
        "agency_order_reconciliation_record",
        sa.Column("id", UUID, nullable=False),
        sa.Column("agency_id", UUID, nullable=False),
        sa.Column("branch_id", UUID, nullable=False),
        sa.Column("order_id", UUID, nullable=False),
        sa.Column("customer_id", UUID, nullable=False),
        sa.Column("cancellation_case_id", UUID, nullable=False),
        sa.Column("compensation_record_id", UUID, nullable=False),
        sa.Column("case_revision", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("observed_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("reconciled_by_user_id", UUID, nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("reconciled_at", TIMESTAMP, nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_agency_order_reconciliation_record",
        ),
        sa.UniqueConstraint(
            "compensation_record_id",
            name="uq_agency_order_reconciliation_compensation",
        ),
        sa.ForeignKeyConstraint(
            _case_binding_columns(),
            _case_binding_targets(),
            name="fk_agency_order_reconciliation_record_case",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                *_case_binding_columns(),
                "compensation_record_id",
            ],
            [
                "agency_order_compensation_record.agency_id",
                "agency_order_compensation_record.branch_id",
                "agency_order_compensation_record.order_id",
                "agency_order_compensation_record.customer_id",
                "agency_order_compensation_record.cancellation_case_id",
                "agency_order_compensation_record.id",
            ],
            name="fk_agency_order_reconciliation_record_compensation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reconciled_by_user_id"],
            ["user.id"],
            name="fk_agency_order_reconciliation_record_reconciler",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "case_revision >= 1",
            name="ck_agency_order_reconciliation_record_revision",
        ),
        sa.CheckConstraint(
            "outcome IN ('matched', 'mismatched', 'unverifiable')",
            name="ck_agency_order_reconciliation_record_outcome",
        ),
        sa.CheckConstraint(
            "length(evidence_hash) = 64",
            name="ck_agency_order_reconciliation_record_evidence_hash",
        ),
        sa.CheckConstraint(
            "(observed_amount IS NULL AND currency IS NULL) "
            "OR (observed_amount IS NOT NULL "
            "AND currency IS NOT NULL "
            "AND observed_amount >= 0 "
            "AND length(currency) = 3 "
            "AND currency = upper(currency))",
            name="ck_agency_order_reconciliation_record_amount",
        ),
    )
    op.create_index(
        "ix_agency_order_reconciliation_record_case_created",
        "agency_order_reconciliation_record",
        ["agency_id", "cancellation_case_id", "created_at", "id"],
    )


def _raise_if_business_data_exists() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM agency_order_cancellation_case
                UNION ALL
                SELECT 1 FROM agency_order_cancellation_event
                UNION ALL
                SELECT 1 FROM agency_order_compensation_record
                UNION ALL
                SELECT 1 FROM agency_order_reconciliation_record
                UNION ALL
                SELECT 1
                FROM agency_order
                WHERE cancellation_requested_at IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade 0007 after cancellation workflow data exists';
            END IF;
        END;
        $$;
        """
    )


def upgrade_agency_cancellation_workflow() -> None:
    op.add_column(
        "agency_order",
        sa.Column("cancellation_requested_at", TIMESTAMP, nullable=True),
    )
    # The 0004 guard rejects same-status maintenance updates and requires a
    # business revision bump.  Remove it before translating the legacy
    # ``cancelled_at`` projection; PostgreSQL transactional DDL keeps this
    # unguarded interval private until the whole revision commits.
    drop_order_mutation_guard()
    op.execute(
        """
        UPDATE agency_order
        SET cancellation_requested_at = COALESCE(cancelled_at, updated_at),
            cancelled_at = NULL
        WHERE status IN ('cancellation_pending', 'manual_intervention')
        """
    )
    op.create_unique_constraint(
        "uq_agency_order_branch_customer_id",
        "agency_order",
        ["agency_id", "branch_id", "customer_id", "id"],
    )
    _create_case_table()
    _create_event_table()
    _create_compensation_table()
    _create_reconciliation_table()
    create_0007_cancellation_guards()


def downgrade_agency_cancellation_workflow() -> None:
    _raise_if_business_data_exists()
    drop_0007_cancellation_guards()
    for index_name, table_name in (
        (
            "ix_agency_order_reconciliation_record_case_created",
            "agency_order_reconciliation_record",
        ),
        (
            "ix_agency_order_compensation_record_case_action",
            "agency_order_compensation_record",
        ),
        (
            "ix_agency_order_cancellation_event_case_created",
            "agency_order_cancellation_event",
        ),
        (
            "ix_agency_order_cancellation_case_customer",
            "agency_order_cancellation_case",
        ),
        (
            "ix_agency_order_cancellation_case_branch_status",
            "agency_order_cancellation_case",
        ),
        (
            "uq_agency_order_cancellation_case_open",
            "agency_order_cancellation_case",
        ),
    ):
        op.drop_index(index_name, table_name=table_name)
    op.drop_table("agency_order_reconciliation_record")
    op.drop_table("agency_order_compensation_record")
    op.drop_table("agency_order_cancellation_event")
    op.drop_table("agency_order_cancellation_case")
    op.drop_constraint(
        "uq_agency_order_branch_customer_id",
        "agency_order",
        type_="unique",
    )
    op.drop_column("agency_order", "cancellation_requested_at")
    restore_0004_order_mutation_guard()
