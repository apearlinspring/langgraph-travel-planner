"""`20260731_0008` 的 revision-frozen schema 与 Alembic 编排。

该模块只属于 0008 revision。客户转店只改变 ``agency_customer`` 的当前
门店；邀请、同意、事件、分配和交易记录保留各自发生时的历史门店。后续
数据库变化必须新增 revision，不得修改本文件。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.models._20260731_0008_agency_branch_transfer_closure_guards_frozen import (
    create_0008_branch_transfer_closure_guards,
    drop_0008_branch_transfer_closure_guards,
    drop_pre_0008_branch_customer_guards,
    restore_pre_0008_branch_customer_guards,
)


UUID = postgresql.UUID(as_uuid=True)
TIMESTAMP = sa.DateTime(timezone=True)


_CUSTOMER_SCOPE_FOREIGN_KEYS: tuple[tuple[str, str], ...] = (
    ("fk_agency_customer_claimed_invitation", "agency_customer"),
    ("fk_agency_customer_current_consent_record", "agency_customer"),
    (
        "fk_agency_customer_consent_record_invitation",
        "agency_customer_consent_record",
    ),
    (
        "fk_agency_customer_consent_record_customer",
        "agency_customer_consent_record",
    ),
    (
        "fk_agency_customer_invitation_customer",
        "agency_customer_invitation",
    ),
    ("fk_agency_customer_event_customer", "agency_customer_event"),
    (
        "fk_customer_advisor_assignment_customer",
        "agency_customer_advisor_assignment",
    ),
    ("fk_agency_quote_customer", "agency_quote"),
    ("fk_agency_order_customer", "agency_order"),
)

_RESHAPED_UNIQUES: tuple[tuple[str, str], ...] = (
    ("uq_agency_customer_branch_id", "agency_customer"),
    ("uq_agency_customer_quote_binding", "agency_customer"),
    (
        "uq_agency_customer_invitation_customer_id",
        "agency_customer_invitation",
    ),
    (
        "uq_agency_customer_consent_record_customer_id",
        "agency_customer_consent_record",
    ),
    (
        "uq_agency_customer_consent_record_sequence",
        "agency_customer_consent_record",
    ),
    (
        "uq_agency_customer_consent_record_revision",
        "agency_customer_consent_record",
    ),
    ("uq_agency_customer_event_sequence", "agency_customer_event"),
)


def _drop_customer_scope_foreign_keys() -> None:
    for constraint_name, table_name in _CUSTOMER_SCOPE_FOREIGN_KEYS:
        op.drop_constraint(
            constraint_name,
            table_name,
            type_="foreignkey",
        )


def _drop_reshaped_uniques_and_indexes() -> None:
    op.drop_index(
        "uq_customer_advisor_assignment_active",
        table_name="agency_customer_advisor_assignment",
    )
    op.drop_index(
        "uq_agency_customer_invitation_pending",
        table_name="agency_customer_invitation",
    )
    for constraint_name, table_name in _RESHAPED_UNIQUES:
        op.drop_constraint(
            constraint_name,
            table_name,
            type_="unique",
        )


def _drop_branchless_customer_uniques_and_indexes() -> None:
    op.drop_index(
        "uq_customer_advisor_assignment_active",
        table_name="agency_customer_advisor_assignment",
    )
    op.drop_index(
        "uq_agency_customer_invitation_pending",
        table_name="agency_customer_invitation",
    )
    for constraint_name, table_name in (
        ("uq_agency_customer_agency_id", "agency_customer"),
        ("uq_agency_customer_quote_binding", "agency_customer"),
        (
            "uq_agency_customer_invitation_customer_id",
            "agency_customer_invitation",
        ),
        (
            "uq_agency_customer_consent_record_customer_id",
            "agency_customer_consent_record",
        ),
        (
            "uq_agency_customer_consent_record_sequence",
            "agency_customer_consent_record",
        ),
        (
            "uq_agency_customer_consent_record_revision",
            "agency_customer_consent_record",
        ),
        ("uq_agency_customer_event_sequence", "agency_customer_event"),
    ):
        op.drop_constraint(
            constraint_name,
            table_name,
            type_="unique",
        )


def _create_branchless_customer_uniques_and_indexes() -> None:
    op.create_unique_constraint(
        "uq_agency_customer_agency_id",
        "agency_customer",
        ["agency_id", "id"],
    )
    op.create_unique_constraint(
        "uq_agency_customer_quote_binding",
        "agency_customer",
        ["agency_id", "id", "user_id"],
    )
    op.create_unique_constraint(
        "uq_agency_customer_invitation_customer_id",
        "agency_customer_invitation",
        ["agency_id", "customer_id", "id"],
    )
    op.create_unique_constraint(
        "uq_agency_customer_consent_record_customer_id",
        "agency_customer_consent_record",
        ["agency_id", "customer_id", "id"],
    )
    op.create_unique_constraint(
        "uq_agency_customer_consent_record_sequence",
        "agency_customer_consent_record",
        ["agency_id", "customer_id", "consent_sequence"],
    )
    op.create_unique_constraint(
        "uq_agency_customer_consent_record_revision",
        "agency_customer_consent_record",
        ["agency_id", "customer_id", "customer_revision"],
    )
    op.create_unique_constraint(
        "uq_agency_customer_event_sequence",
        "agency_customer_event",
        ["agency_id", "customer_id", "event_sequence"],
    )
    op.create_index(
        "uq_agency_customer_invitation_pending",
        "agency_customer_invitation",
        ["agency_id", "customer_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_customer_advisor_assignment_active",
        "agency_customer_advisor_assignment",
        ["agency_id", "customer_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def _create_branchless_customer_foreign_keys() -> None:
    op.create_foreign_key(
        "fk_agency_customer_claimed_invitation",
        "agency_customer",
        "agency_customer_invitation",
        ["agency_id", "id", "claimed_invitation_id"],
        ["agency_id", "customer_id", "id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_agency_customer_current_consent_record",
        "agency_customer",
        "agency_customer_consent_record",
        ["agency_id", "id", "current_consent_record_id"],
        ["agency_id", "customer_id", "id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_agency_customer_invitation_customer",
        "agency_customer_invitation",
        "agency_customer",
        ["agency_id", "customer_id"],
        ["agency_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_agency_customer_consent_record_customer",
        "agency_customer_consent_record",
        "agency_customer",
        ["agency_id", "customer_id"],
        ["agency_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_agency_customer_consent_record_invitation",
        "agency_customer_consent_record",
        "agency_customer_invitation",
        ["agency_id", "customer_id", "invitation_id"],
        ["agency_id", "customer_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_agency_customer_event_customer",
        "agency_customer_event",
        "agency_customer",
        ["agency_id", "customer_id"],
        ["agency_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_customer_advisor_assignment_customer",
        "agency_customer_advisor_assignment",
        "agency_customer",
        ["agency_id", "customer_id"],
        ["agency_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_agency_quote_customer",
        "agency_quote",
        "agency_customer",
        ["agency_id", "customer_id", "user_id"],
        ["agency_id", "id", "user_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_agency_order_customer",
        "agency_order",
        "agency_customer",
        ["agency_id", "customer_id"],
        ["agency_id", "id"],
        ondelete="RESTRICT",
    )


def _restore_branch_scoped_customer_uniques_and_indexes() -> None:
    op.create_unique_constraint(
        "uq_agency_customer_branch_id",
        "agency_customer",
        ["agency_id", "branch_id", "id"],
    )
    op.create_unique_constraint(
        "uq_agency_customer_quote_binding",
        "agency_customer",
        ["agency_id", "branch_id", "id", "user_id"],
    )
    op.create_unique_constraint(
        "uq_agency_customer_invitation_customer_id",
        "agency_customer_invitation",
        ["agency_id", "branch_id", "customer_id", "id"],
    )
    op.create_unique_constraint(
        "uq_agency_customer_consent_record_customer_id",
        "agency_customer_consent_record",
        ["agency_id", "branch_id", "customer_id", "id"],
    )
    op.create_unique_constraint(
        "uq_agency_customer_consent_record_sequence",
        "agency_customer_consent_record",
        ["agency_id", "branch_id", "customer_id", "consent_sequence"],
    )
    op.create_unique_constraint(
        "uq_agency_customer_consent_record_revision",
        "agency_customer_consent_record",
        ["agency_id", "branch_id", "customer_id", "customer_revision"],
    )
    op.create_unique_constraint(
        "uq_agency_customer_event_sequence",
        "agency_customer_event",
        ["agency_id", "branch_id", "customer_id", "event_sequence"],
    )
    op.create_index(
        "uq_agency_customer_invitation_pending",
        "agency_customer_invitation",
        ["agency_id", "branch_id", "customer_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_customer_advisor_assignment_active",
        "agency_customer_advisor_assignment",
        ["agency_id", "branch_id", "customer_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def _restore_branch_scoped_customer_foreign_keys() -> None:
    op.create_foreign_key(
        "fk_agency_customer_claimed_invitation",
        "agency_customer",
        "agency_customer_invitation",
        ["agency_id", "branch_id", "id", "claimed_invitation_id"],
        ["agency_id", "branch_id", "customer_id", "id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_agency_customer_current_consent_record",
        "agency_customer",
        "agency_customer_consent_record",
        ["agency_id", "branch_id", "id", "current_consent_record_id"],
        ["agency_id", "branch_id", "customer_id", "id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_agency_customer_invitation_customer",
        "agency_customer_invitation",
        "agency_customer",
        ["agency_id", "branch_id", "customer_id"],
        ["agency_id", "branch_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_agency_customer_consent_record_customer",
        "agency_customer_consent_record",
        "agency_customer",
        ["agency_id", "branch_id", "customer_id"],
        ["agency_id", "branch_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_agency_customer_consent_record_invitation",
        "agency_customer_consent_record",
        "agency_customer_invitation",
        ["agency_id", "branch_id", "customer_id", "invitation_id"],
        ["agency_id", "branch_id", "customer_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_agency_customer_event_customer",
        "agency_customer_event",
        "agency_customer",
        ["agency_id", "branch_id", "customer_id"],
        ["agency_id", "branch_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_customer_advisor_assignment_customer",
        "agency_customer_advisor_assignment",
        "agency_customer",
        ["agency_id", "branch_id", "customer_id"],
        ["agency_id", "branch_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_agency_quote_customer",
        "agency_quote",
        "agency_customer",
        ["agency_id", "branch_id", "customer_id", "user_id"],
        ["agency_id", "branch_id", "id", "user_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_agency_order_customer",
        "agency_order",
        "agency_customer",
        ["agency_id", "branch_id", "customer_id"],
        ["agency_id", "branch_id", "id"],
        ondelete="RESTRICT",
    )


def _upgrade_branch_lifecycle_columns() -> None:
    op.add_column(
        "agency_branch",
        sa.Column("closed_at", TIMESTAMP, nullable=True),
    )
    op.drop_constraint(
        "ck_agency_branch_deactivated",
        "agency_branch",
        type_="check",
    )
    op.execute(
        """
        UPDATE agency_branch
        SET deactivated_at = COALESCE(
                deactivated_at,
                updated_at,
                created_at,
                CURRENT_TIMESTAMP
            ),
            closed_at = CASE
                WHEN status = 'closed' THEN COALESCE(
                    deactivated_at,
                    updated_at,
                    created_at,
                    CURRENT_TIMESTAMP
                )
                ELSE NULL
            END
        WHERE status IN ('inactive', 'closed')
        """
    )
    op.create_check_constraint(
        "ck_agency_branch_lifecycle_timestamps",
        "agency_branch",
        "(status = 'active' "
        "AND deactivated_at IS NULL "
        "AND closed_at IS NULL) "
        "OR (status = 'inactive' "
        "AND deactivated_at IS NOT NULL "
        "AND closed_at IS NULL) "
        "OR (status = 'closed' "
        "AND deactivated_at IS NOT NULL "
        "AND closed_at IS NOT NULL "
        "AND closed_at >= deactivated_at)",
    )


def _downgrade_branch_lifecycle_columns() -> None:
    op.drop_constraint(
        "ck_agency_branch_lifecycle_timestamps",
        "agency_branch",
        type_="check",
    )
    op.drop_column("agency_branch", "closed_at")
    op.create_check_constraint(
        "ck_agency_branch_deactivated",
        "agency_branch",
        "deactivated_at IS NULL OR status <> 'active'",
    )


def _create_customer_branch_transfer_table() -> None:
    op.create_table(
        "agency_customer_branch_transfer",
        sa.Column("id", UUID, nullable=False),
        sa.Column("agency_id", UUID, nullable=False),
        sa.Column("customer_id", UUID, nullable=False),
        sa.Column("from_branch_id", UUID, nullable=False),
        sa.Column("to_branch_id", UUID, nullable=False),
        sa.Column("customer_revision", sa.Integer(), nullable=False),
        sa.Column("transferred_by_user_id", UUID, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("transferred_at", TIMESTAMP, nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_agency_customer_branch_transfer",
        ),
        sa.UniqueConstraint(
            "agency_id",
            "customer_id",
            "customer_revision",
            name="uq_customer_branch_transfer_revision",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agency.id"],
            name="fk_customer_branch_transfer_agency",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "customer_id"],
            ["agency_customer.agency_id", "agency_customer.id"],
            name="fk_customer_branch_transfer_customer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "from_branch_id"],
            ["agency_branch.agency_id", "agency_branch.id"],
            name="fk_customer_branch_transfer_from_branch",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "to_branch_id"],
            ["agency_branch.agency_id", "agency_branch.id"],
            name="fk_customer_branch_transfer_to_branch",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transferred_by_user_id"],
            ["user.id"],
            name="fk_customer_branch_transfer_actor",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "from_branch_id <> to_branch_id",
            name="ck_customer_branch_transfer_distinct_branches",
        ),
        sa.CheckConstraint(
            "customer_revision >= 2",
            name="ck_customer_branch_transfer_revision",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) BETWEEN 1 AND 500",
            name="ck_customer_branch_transfer_reason",
        ),
    )
    op.create_index(
        "ix_customer_branch_transfer_customer_time",
        "agency_customer_branch_transfer",
        ["agency_id", "customer_id", "transferred_at", "id"],
    )


def _create_branch_lifecycle_event_table() -> None:
    op.create_table(
        "agency_branch_lifecycle_event",
        sa.Column("id", UUID, nullable=False),
        sa.Column("agency_id", UUID, nullable=False),
        sa.Column("branch_id", UUID, nullable=False),
        sa.Column("event_sequence", sa.Integer(), nullable=False),
        sa.Column("branch_revision", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("actor_user_id", UUID, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_agency_branch_lifecycle_event",
        ),
        sa.UniqueConstraint(
            "agency_id",
            "branch_id",
            "event_sequence",
            name="uq_agency_branch_lifecycle_event_sequence",
        ),
        sa.UniqueConstraint(
            "agency_id",
            "branch_id",
            "branch_revision",
            name="uq_agency_branch_lifecycle_event_revision",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "branch_id"],
            ["agency_branch.agency_id", "agency_branch.id"],
            name="fk_agency_branch_lifecycle_event_branch",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["user.id"],
            name="fk_agency_branch_lifecycle_event_actor",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "event_sequence >= 1",
            name="ck_agency_branch_lifecycle_event_sequence",
        ),
        sa.CheckConstraint(
            "branch_revision >= 2",
            name="ck_agency_branch_lifecycle_event_revision",
        ),
        sa.CheckConstraint(
            "event_type IN ('deactivated', 'closed')",
            name="ck_agency_branch_lifecycle_event_type",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) BETWEEN 1 AND 500",
            name="ck_agency_branch_lifecycle_event_reason",
        ),
    )
    op.create_index(
        "ix_agency_branch_lifecycle_event_branch_created",
        "agency_branch_lifecycle_event",
        ["agency_id", "branch_id", "created_at", "id"],
    )


def _raise_if_0008_business_data_or_branch_mismatch_exists() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM agency_customer_branch_transfer
                UNION ALL
                SELECT 1 FROM agency_branch_lifecycle_event
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade 0008 after branch transfer or closure data exists';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM agency_customer_invitation child
                JOIN agency_customer customer
                  ON customer.agency_id = child.agency_id
                 AND customer.id = child.customer_id
                WHERE child.branch_id <> customer.branch_id
                UNION ALL
                SELECT 1
                FROM agency_customer_consent_record child
                JOIN agency_customer customer
                  ON customer.agency_id = child.agency_id
                 AND customer.id = child.customer_id
                WHERE child.branch_id <> customer.branch_id
                UNION ALL
                SELECT 1
                FROM agency_customer_event child
                JOIN agency_customer customer
                  ON customer.agency_id = child.agency_id
                 AND customer.id = child.customer_id
                WHERE child.branch_id <> customer.branch_id
                UNION ALL
                SELECT 1
                FROM agency_customer_advisor_assignment child
                JOIN agency_customer customer
                  ON customer.agency_id = child.agency_id
                 AND customer.id = child.customer_id
                WHERE child.branch_id <> customer.branch_id
                UNION ALL
                SELECT 1
                FROM agency_quote child
                JOIN agency_customer customer
                  ON customer.agency_id = child.agency_id
                 AND customer.id = child.customer_id
                WHERE child.branch_id <> customer.branch_id
                UNION ALL
                SELECT 1
                FROM agency_order child
                JOIN agency_customer customer
                  ON customer.agency_id = child.agency_id
                 AND customer.id = child.customer_id
                WHERE child.branch_id <> customer.branch_id
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade 0008 while historical branch bindings differ';
            END IF;
        END;
        $$;
        """
    )


def _raise_if_legacy_closed_branch_has_0008_blockers() -> None:
    """拒绝把带存量关系或开放业务的旧 closed 门店静默带入 0008。"""

    op.execute(
        """
        LOCK TABLE
            agency_customer,
            agency_branch,
            agency_customer_invitation,
            agency_customer_advisor_assignment,
            agency_branch_role_grant,
            agency_order_review,
            agency_quote,
            agency_order,
            agency_order_cancellation_case
        IN SHARE ROW EXCLUSIVE MODE;

        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM agency_branch branch
                WHERE branch.status = 'closed'
                  AND (
                    EXISTS (
                        SELECT 1
                        FROM agency_customer customer
                        WHERE customer.agency_id = branch.agency_id
                          AND customer.branch_id = branch.id
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM agency_customer_invitation invitation
                        WHERE invitation.agency_id = branch.agency_id
                          AND invitation.branch_id = branch.id
                          AND invitation.status = 'pending'
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM agency_customer_advisor_assignment assignment
                        WHERE assignment.agency_id = branch.agency_id
                          AND assignment.branch_id = branch.id
                          AND assignment.status = 'active'
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM agency_branch_role_grant grant_row
                        WHERE grant_row.agency_id = branch.agency_id
                          AND grant_row.branch_id = branch.id
                          AND grant_row.status = 'active'
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM agency_order_review review
                        WHERE review.agency_id = branch.agency_id
                          AND review.branch_id = branch.id
                          AND review.status = 'pending'
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM agency_order order_row
                        WHERE order_row.agency_id = branch.agency_id
                          AND order_row.branch_id = branch.id
                          AND order_row.status NOT IN (
                              'review_rejected', 'completed', 'cancelled'
                          )
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM agency_quote quote
                        WHERE quote.agency_id = branch.agency_id
                          AND quote.branch_id = branch.id
                          AND (
                              quote.status IN ('draft', 'offered')
                              OR (
                                  quote.status = 'accepted'
                                  AND NOT EXISTS (
                                      SELECT 1
                                      FROM agency_order order_row
                                      WHERE order_row.agency_id
                                            = quote.agency_id
                                        AND order_row.branch_id
                                            = quote.branch_id
                                        AND order_row.quote_id = quote.id
                                        AND order_row.status IN (
                                            'review_rejected',
                                            'completed',
                                            'cancelled'
                                        )
                                  )
                              )
                          )
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM agency_order_cancellation_case case_row
                        WHERE case_row.agency_id = branch.agency_id
                          AND case_row.branch_id = branch.id
                          AND case_row.status IN (
                              'approval_pending',
                              'action_pending',
                              'reconciliation_pending',
                              'manual_intervention'
                          )
                    )
                  )
            ) THEN
                RAISE EXCEPTION
                    'cannot upgrade 0008: legacy closed agency_branch has current customers or open work';
            END IF;
        END;
        $$;
        """
    )


def upgrade_agency_branch_transfer_closure() -> None:
    _raise_if_legacy_closed_branch_has_0008_blockers()
    drop_pre_0008_branch_customer_guards()
    _upgrade_branch_lifecycle_columns()
    _drop_customer_scope_foreign_keys()
    _drop_reshaped_uniques_and_indexes()
    _create_branchless_customer_uniques_and_indexes()
    _create_branchless_customer_foreign_keys()
    _create_customer_branch_transfer_table()
    _create_branch_lifecycle_event_table()
    create_0008_branch_transfer_closure_guards()


def downgrade_agency_branch_transfer_closure() -> None:
    _raise_if_0008_business_data_or_branch_mismatch_exists()
    drop_0008_branch_transfer_closure_guards()
    op.drop_index(
        "ix_agency_branch_lifecycle_event_branch_created",
        table_name="agency_branch_lifecycle_event",
    )
    op.drop_index(
        "ix_customer_branch_transfer_customer_time",
        table_name="agency_customer_branch_transfer",
    )
    op.drop_table("agency_branch_lifecycle_event")
    op.drop_table("agency_customer_branch_transfer")
    _drop_customer_scope_foreign_keys()
    _drop_branchless_customer_uniques_and_indexes()
    _restore_branch_scoped_customer_uniques_and_indexes()
    _restore_branch_scoped_customer_foreign_keys()
    _downgrade_branch_lifecycle_columns()
    restore_pre_0008_branch_customer_guards()
