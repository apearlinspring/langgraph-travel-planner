"""Add agency branches, customer lifecycle and advisor assignments."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models._20260726_0004_agency_customer_lifecycle_frozen import (
    TIMESTAMP,
    UUID,
    create_advisor_assignment_table as _create_advisor_assignment_table,
    create_append_only_guard as _create_append_only_guard,
    create_branch_role_grant_table as _create_branch_role_grant_table,
    create_branch_table as _create_branch_table,
    create_customer_constraints as _create_customer_constraints,
    create_customer_event_table as _create_customer_event_table,
    create_lifecycle_triggers as _create_lifecycle_triggers,
    create_order_event_trigger as _create_order_event_trigger,
    create_review_trigger as _create_review_trigger,
    drop_columns as _drop_columns,
    drop_constraints as _drop_constraints,
    foreign_key as _foreign_key,
    raise_if_exists as _raise_if_exists,
)
from app.models._20260726_0004_agency_transaction_guards_frozen import (
    create_transaction_mutation_guards as _create_transaction_mutation_guards,
    drop_transaction_mutation_guards as _drop_transaction_mutation_guards,
)

revision: str = "20260726_0004"
down_revision: Union[str, None] = "20260726_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_agency_order_event_append_only "
        "ON agency_order_event"
    )
    op.execute(
        "DROP TRIGGER trg_agency_order_review_mutation_guard "
        "ON agency_order_review"
    )
    _create_branch_table()
    op.execute(
        """
        INSERT INTO agency_branch (
            id, agency_id, branch_code, name, status, revision,
            deactivated_at, created_at, updated_at
        )
        SELECT id, id, 'MAIN', name, 'active', 1, NULL, created_at, updated_at
        FROM agency
        """
    )
    op.drop_constraint(
        "ck_agency_membership_role",
        "agency_membership",
        type_="check",
    )
    op.create_check_constraint(
        "ck_agency_membership_role",
        "agency_membership",
        "role IN "
        "('travel_advisor', 'booking_operator', 'approver', 'finance', "
        "'auditor', 'branch_manager', 'admin', 'owner')",
    )
    op.create_unique_constraint(
        "uq_agency_membership_agency_id",
        "agency_membership",
        ["agency_id", "id"],
    )
    _create_branch_role_grant_table()
    op.execute(
        """
        INSERT INTO agency_branch_role_grant (
            id, agency_id, branch_id, membership_id, role, status, revision,
            granted_by_user_id, granted_at, revoked_at, revocation_reason,
            created_at, updated_at
        )
        SELECT id, agency_id, agency_id, id, role, 'active', 1, NULL,
               COALESCE(joined_at, created_at), NULL, NULL,
               created_at, updated_at
        FROM agency_membership
        WHERE status = 'active'
          AND role IN (
              'travel_advisor', 'booking_operator', 'approver',
              'finance', 'auditor', 'branch_manager'
          )
        """
    )

    customer_columns = (
        sa.Column("branch_id", UUID, nullable=True),
        sa.Column("customer_no", sa.String(40), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=True),
        sa.Column("source_reference", sa.String(160), nullable=True),
        sa.Column("consent_status", sa.String(20), nullable=True),
        sa.Column("consent_version", sa.String(40), nullable=True),
        sa.Column("consent_evidence_hash", sa.String(64), nullable=True),
        sa.Column("consent_updated_at", TIMESTAMP, nullable=True),
        sa.Column("lifecycle_revision", sa.Integer(), nullable=True),
        sa.Column("invited_at", TIMESTAMP, nullable=True),
        sa.Column("deactivated_at", TIMESTAMP, nullable=True),
    )
    for column in customer_columns:
        op.add_column("agency_customer", column)
    op.alter_column(
        "agency_customer",
        "user_id",
        existing_type=UUID,
        nullable=True,
    )
    op.execute(
        """
        UPDATE agency_customer SET
            branch_id = agency_id,
            customer_no = 'LEGACY-' || replace(id::text, '-', ''),
            source_type = 'legacy',
            source_reference = 'migration:20260726_0004',
            consent_status = 'unknown',
            lifecycle_revision = 1,
            invited_at = created_at
        """
    )
    required_customer_columns = {
        "branch_id": UUID,
        "customer_no": sa.String(40),
        "source_type": sa.String(32),
        "consent_status": sa.String(20),
        "lifecycle_revision": sa.Integer(),
        "invited_at": TIMESTAMP,
    }
    for name, column_type in required_customer_columns.items():
        op.alter_column(
            "agency_customer",
            name,
            existing_type=column_type,
            nullable=False,
        )
    op.drop_constraint(
        "ck_agency_customer_status",
        "agency_customer",
        type_="check",
    )
    _create_customer_constraints()
    _create_customer_event_table()
    op.execute(
        """
        INSERT INTO agency_customer_event (
            id, agency_id, branch_id, customer_id, event_sequence,
            customer_revision, event_type, from_status, to_status,
            actor_user_id, event_metadata, created_at
        )
        SELECT id, agency_id, branch_id, id, 1, lifecycle_revision,
               'customer_migrated', NULL, status, NULL,
               '{"source": "migration:20260726_0004"}'::json, created_at
        FROM agency_customer
        """
    )
    _create_append_only_guard("agency_customer_event")
    _create_advisor_assignment_table()
    _create_lifecycle_triggers()

    for table, names in (
        ("agency_quote", ("branch_id", "customer_id")),
        ("agency_order", ("branch_id", "customer_id")),
    ):
        for name in names:
            op.add_column(table, sa.Column(name, UUID, nullable=True))
    _raise_if_exists(
        """
        SELECT 1 FROM agency_quote quote
        LEFT JOIN agency_customer customer
          ON customer.agency_id = quote.agency_id
         AND customer.user_id = quote.user_id
        WHERE customer.id IS NULL
        """,
        "cannot bind every legacy quote to one agency customer",
    )
    op.execute(
        """
        UPDATE agency_quote quote
        SET branch_id = customer.branch_id, customer_id = customer.id
        FROM agency_customer customer
        WHERE customer.agency_id = quote.agency_id
          AND customer.user_id = quote.user_id
        """
    )
    for name in ("branch_id", "customer_id"):
        op.alter_column(
            "agency_quote",
            name,
            existing_type=UUID,
            nullable=False,
        )
    op.drop_constraint(
        "fk_agency_order_quote_tenant_user",
        "agency_order",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_agency_quote_agency_user_id",
        "agency_quote",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_agency_quote_order_binding",
        "agency_quote",
        ["agency_id", "branch_id", "customer_id", "user_id", "id"],
    )
    _foreign_key(
        "fk_agency_quote_branch",
        "agency_quote",
        "agency_branch",
        ["agency_id", "branch_id"],
        ["agency_id", "id"],
    )
    _foreign_key(
        "fk_agency_quote_customer",
        "agency_quote",
        "agency_customer",
        ["agency_id", "branch_id", "customer_id", "user_id"],
        ["agency_id", "branch_id", "id", "user_id"],
    )
    op.create_index(
        "ix_agency_quote_branch_customer_status",
        "agency_quote",
        [
            "agency_id",
            "branch_id",
            "customer_id",
            "status",
            "created_at",
            "id",
        ],
    )
    _raise_if_exists(
        """
        SELECT 1 FROM agency_order order_row
        LEFT JOIN agency_quote quote
          ON quote.agency_id = order_row.agency_id
         AND quote.user_id = order_row.user_id
         AND quote.id = order_row.quote_id
        WHERE quote.id IS NULL
           OR quote.branch_id IS NULL
           OR quote.customer_id IS NULL
        """,
        "cannot bind every legacy order to its quote customer",
    )
    op.execute(
        """
        UPDATE agency_order order_row
        SET branch_id = quote.branch_id, customer_id = quote.customer_id
        FROM agency_quote quote
        WHERE quote.agency_id = order_row.agency_id
          AND quote.user_id = order_row.user_id
          AND quote.id = order_row.quote_id
        """
    )
    for name in ("branch_id", "customer_id"):
        op.alter_column(
            "agency_order",
            name,
            existing_type=UUID,
            nullable=False,
        )
    op.create_unique_constraint(
        "uq_agency_order_branch_id",
        "agency_order",
        ["agency_id", "branch_id", "id"],
    )
    _foreign_key(
        "fk_agency_order_quote_binding",
        "agency_order",
        "agency_quote",
        ["agency_id", "branch_id", "customer_id", "user_id", "quote_id"],
        ["agency_id", "branch_id", "customer_id", "user_id", "id"],
    )
    _foreign_key(
        "fk_agency_order_branch",
        "agency_order",
        "agency_branch",
        ["agency_id", "branch_id"],
        ["agency_id", "id"],
    )
    _foreign_key(
        "fk_agency_order_customer",
        "agency_order",
        "agency_customer",
        ["agency_id", "branch_id", "customer_id"],
        ["agency_id", "branch_id", "id"],
    )
    op.create_index(
        "ix_agency_order_branch_customer_status",
        "agency_order",
        [
            "agency_id",
            "branch_id",
            "customer_id",
            "status",
            "created_at",
            "id",
        ],
    )

    op.add_column(
        "agency_order_event",
        sa.Column("branch_id", UUID, nullable=True),
    )
    _raise_if_exists(
        """
        SELECT 1 FROM agency_order_event event_row
        LEFT JOIN agency_order order_row
          ON order_row.agency_id = event_row.agency_id
         AND order_row.id = event_row.order_id
        WHERE order_row.id IS NULL OR order_row.branch_id IS NULL
        """,
        "cannot bind every legacy order event to an order branch",
    )
    op.execute(
        """
        UPDATE agency_order_event event_row
        SET branch_id = order_row.branch_id
        FROM agency_order order_row
        WHERE order_row.agency_id = event_row.agency_id
          AND order_row.id = event_row.order_id
        """
    )
    op.alter_column(
        "agency_order_event",
        "branch_id",
        existing_type=UUID,
        nullable=False,
    )
    _drop_constraints(
        "agency_order_event",
        "foreignkey",
        "fk_agency_order_event_order_tenant",
    )
    _drop_constraints(
        "agency_order_event",
        "unique",
        "uq_agency_order_event_sequence",
    )
    _foreign_key(
        "fk_agency_order_event_order_branch",
        "agency_order_event",
        "agency_order",
        ["agency_id", "branch_id", "order_id"],
        ["agency_id", "branch_id", "id"],
    )
    op.create_unique_constraint(
        "uq_agency_order_event_sequence",
        "agency_order_event",
        ["agency_id", "branch_id", "order_id", "event_sequence"],
    )
    _create_order_event_trigger()

    op.add_column(
        "agency_order_review",
        sa.Column("branch_id", UUID, nullable=True),
    )
    _raise_if_exists(
        """
        SELECT 1 FROM agency_order_review review
        LEFT JOIN agency_order order_row
          ON order_row.agency_id = review.agency_id
         AND order_row.id = review.order_id
        WHERE order_row.id IS NULL OR order_row.branch_id IS NULL
        """,
        "cannot bind every legacy order review to an order branch",
    )
    op.execute(
        """
        UPDATE agency_order_review review
        SET branch_id = order_row.branch_id
        FROM agency_order order_row
        WHERE order_row.agency_id = review.agency_id
          AND order_row.id = review.order_id
        """
    )
    op.alter_column(
        "agency_order_review",
        "branch_id",
        existing_type=UUID,
        nullable=False,
    )
    _drop_constraints(
        "agency_order_review",
        "foreignkey",
        "fk_agency_order_review_order_tenant",
    )
    _drop_constraints(
        "agency_order_review",
        "unique",
        "uq_agency_order_review_order_revision",
    )
    _foreign_key(
        "fk_agency_order_review_order_branch",
        "agency_order_review",
        "agency_order",
        ["agency_id", "branch_id", "order_id"],
        ["agency_id", "branch_id", "id"],
    )
    op.create_unique_constraint(
        "uq_agency_order_review_order_revision",
        "agency_order_review",
        ["agency_id", "branch_id", "order_id", "order_revision"],
    )
    op.drop_index(
        "ix_agency_order_review_agency_status_created",
        table_name="agency_order_review",
    )
    op.create_index(
        "ix_agency_order_review_agency_status_created",
        "agency_order_review",
        ["agency_id", "branch_id", "status", "created_at", "id"],
    )
    _create_review_trigger(include_branch=True)
    _create_transaction_mutation_guards()


def downgrade() -> None:
    _raise_if_exists(
        """
        SELECT 1 FROM agency_branch branch
        JOIN agency ON agency.id = branch.agency_id
        WHERE branch.id <> branch.agency_id
           OR branch.branch_code <> 'MAIN'
           OR branch.name <> agency.name
           OR branch.status <> 'active'
           OR branch.revision <> 1
           OR branch.deactivated_at IS NOT NULL
        UNION ALL
        SELECT 1 FROM agency
        WHERE NOT EXISTS (
            SELECT 1 FROM agency_branch
            WHERE agency_branch.id = agency.id
              AND agency_branch.agency_id = agency.id
        )
        """,
        "downgrade blocked: non-baseline agency branch exists",
    )
    _raise_if_exists(
        """
        SELECT 1 FROM agency_customer WHERE user_id IS NULL
        """,
        "downgrade blocked: customer without user binding exists",
    )
    _raise_if_exists(
        """
        SELECT 1 FROM agency_membership WHERE role = 'branch_manager'
        UNION ALL
        SELECT 1 FROM agency_branch_role_grant
        WHERE role = 'branch_manager'
        """,
        "downgrade blocked: branch_manager role exists",
    )
    _raise_if_exists(
        """
        SELECT 1 FROM agency_customer
        WHERE branch_id <> agency_id
           OR customer_no <> 'LEGACY-' || replace(id::text, '-', '')
           OR source_type IS DISTINCT FROM 'legacy'
           OR source_reference
                IS DISTINCT FROM 'migration:20260726_0004'
           OR consent_status <> 'unknown'
           OR consent_version IS NOT NULL
           OR consent_evidence_hash IS NOT NULL
           OR consent_updated_at IS NOT NULL
           OR lifecycle_revision <> 1
           OR invited_at <> created_at
           OR deactivated_at IS NOT NULL
           OR status NOT IN ('prospect', 'active', 'inactive', 'blocked')
        """,
        "downgrade blocked: non-legacy or changed customer exists",
    )
    _raise_if_exists(
        "SELECT 1 FROM agency_customer_advisor_assignment",
        "downgrade blocked: advisor assignment exists",
    )
    _raise_if_exists(
        """
        SELECT 1 FROM agency_customer_event event_row
        JOIN agency_customer customer ON customer.id = event_row.customer_id
        WHERE event_row.id <> customer.id
           OR event_row.agency_id <> customer.agency_id
           OR event_row.branch_id <> customer.branch_id
           OR event_row.event_sequence <> 1
           OR event_row.customer_revision <> 1
           OR event_row.event_type <> 'customer_migrated'
           OR event_row.from_status IS NOT NULL
           OR event_row.to_status <> customer.status
           OR event_row.actor_user_id IS NOT NULL
           OR event_row.event_metadata::jsonb IS DISTINCT FROM
                '{"source":"migration:20260726_0004"}'::jsonb
           OR event_row.created_at <> customer.created_at
        """,
        "downgrade blocked: non-baseline customer event exists",
    )
    _raise_if_exists(
        """
        SELECT 1 FROM agency_branch_role_grant grant_row
        LEFT JOIN agency_membership membership
          ON membership.id = grant_row.membership_id
        WHERE membership.id IS NULL
           OR membership.status <> 'active'
           OR grant_row.id <> membership.id
           OR grant_row.agency_id <> membership.agency_id
           OR grant_row.branch_id <> membership.agency_id
           OR grant_row.role <> membership.role
           OR grant_row.status <> 'active'
           OR grant_row.revision <> 1
           OR grant_row.granted_by_user_id IS NOT NULL
           OR grant_row.granted_at
                <> COALESCE(membership.joined_at, membership.created_at)
           OR grant_row.revoked_at IS NOT NULL
           OR grant_row.revocation_reason IS NOT NULL
           OR grant_row.created_at <> membership.created_at
           OR grant_row.updated_at <> membership.updated_at
        UNION ALL
        SELECT 1 FROM agency_membership membership
        WHERE membership.status = 'active'
          AND membership.role IN (
              'travel_advisor', 'booking_operator', 'approver',
              'finance', 'auditor', 'branch_manager'
          )
          AND NOT EXISTS (
              SELECT 1 FROM agency_branch_role_grant grant_row
              WHERE grant_row.id = membership.id
          )
        """,
        "downgrade blocked: non-baseline branch role grant exists",
    )

    _drop_transaction_mutation_guards()
    op.execute(
        "DROP TRIGGER trg_agency_order_review_mutation_guard "
        "ON agency_order_review"
    )
    op.drop_index(
        "ix_agency_order_review_agency_status_created",
        table_name="agency_order_review",
    )
    _drop_constraints(
        "agency_order_review",
        "foreignkey",
        "fk_agency_order_review_order_branch",
    )
    _drop_constraints(
        "agency_order_review",
        "unique",
        "uq_agency_order_review_order_revision",
    )
    op.drop_column("agency_order_review", "branch_id")
    _foreign_key(
        "fk_agency_order_review_order_tenant",
        "agency_order_review",
        "agency_order",
        ["agency_id", "order_id"],
        ["agency_id", "id"],
    )
    op.create_unique_constraint(
        "uq_agency_order_review_order_revision",
        "agency_order_review",
        ["agency_id", "order_id", "order_revision"],
    )
    op.create_index(
        "ix_agency_order_review_agency_status_created",
        "agency_order_review",
        ["agency_id", "status", "created_at", "id"],
    )
    _create_review_trigger(include_branch=False)

    op.execute(
        "DROP TRIGGER trg_agency_order_event_append_only "
        "ON agency_order_event"
    )
    _drop_constraints(
        "agency_order_event",
        "foreignkey",
        "fk_agency_order_event_order_branch",
    )
    _drop_constraints(
        "agency_order_event",
        "unique",
        "uq_agency_order_event_sequence",
    )
    op.drop_column("agency_order_event", "branch_id")
    _foreign_key(
        "fk_agency_order_event_order_tenant",
        "agency_order_event",
        "agency_order",
        ["agency_id", "order_id"],
        ["agency_id", "id"],
    )
    op.create_unique_constraint(
        "uq_agency_order_event_sequence",
        "agency_order_event",
        ["order_id", "event_sequence"],
    )
    _create_order_event_trigger()

    op.drop_index(
        "ix_agency_order_branch_customer_status",
        table_name="agency_order",
    )
    _drop_constraints(
        "agency_order",
        "foreignkey",
        "fk_agency_order_customer",
        "fk_agency_order_branch",
        "fk_agency_order_quote_binding",
    )
    _drop_constraints(
        "agency_order",
        "unique",
        "uq_agency_order_branch_id",
    )
    _drop_columns("agency_order", "customer_id", "branch_id")

    op.drop_index(
        "ix_agency_quote_branch_customer_status",
        table_name="agency_quote",
    )
    _drop_constraints(
        "agency_quote",
        "foreignkey",
        "fk_agency_quote_customer",
        "fk_agency_quote_branch",
    )
    _drop_constraints(
        "agency_quote",
        "unique",
        "uq_agency_quote_order_binding",
    )
    _drop_columns("agency_quote", "customer_id", "branch_id")
    op.create_unique_constraint(
        "uq_agency_quote_agency_user_id",
        "agency_quote",
        ["agency_id", "user_id", "id"],
    )
    _foreign_key(
        "fk_agency_order_quote_tenant_user",
        "agency_order",
        "agency_quote",
        ["agency_id", "user_id", "quote_id"],
        ["agency_id", "user_id", "id"],
    )

    trigger_objects = (
        (
            "agency_branch",
            "trg_agency_branch_lifecycle_guard",
            "zhixing_guard_agency_branch_lifecycle",
        ),
        (
            "agency_customer",
            "trg_agency_customer_lifecycle_guard",
            "zhixing_guard_agency_customer_lifecycle",
        ),
        (
            "agency_membership",
            "trg_agency_membership_active_grant_guard",
            "zhixing_guard_membership_active_grants",
        ),
        (
            "agency_branch_role_grant",
            "trg_agency_branch_role_grant_guard",
            "zhixing_guard_agency_branch_role_grant",
        ),
        (
            "agency_customer_advisor_assignment",
            "trg_customer_advisor_assignment_guard",
            "zhixing_guard_customer_advisor_assignment",
        ),
    )
    for table, trigger, function in trigger_objects:
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
        op.execute(f"DROP FUNCTION {function}()")
    op.drop_index(
        "ix_customer_advisor_assignment_advisor_status",
        table_name="agency_customer_advisor_assignment",
    )
    op.drop_index(
        "uq_customer_advisor_assignment_active",
        table_name="agency_customer_advisor_assignment",
    )
    op.drop_table("agency_customer_advisor_assignment")
    op.execute(
        "DROP TRIGGER trg_agency_customer_event_append_only "
        "ON agency_customer_event"
    )
    op.execute(
        "DROP FUNCTION zhixing_reject_agency_customer_event_mutation()"
    )
    op.drop_index(
        "ix_agency_customer_event_customer_created",
        table_name="agency_customer_event",
    )
    op.drop_table("agency_customer_event")
    op.drop_index(
        "ix_branch_role_grant_member_status",
        table_name="agency_branch_role_grant",
    )
    op.drop_index(
        "uq_branch_role_grant_active",
        table_name="agency_branch_role_grant",
    )
    op.drop_table("agency_branch_role_grant")

    op.drop_index(
        "ix_agency_customer_branch_status",
        table_name="agency_customer",
    )
    _drop_constraints(
        "agency_customer",
        "foreignkey",
        "fk_agency_customer_branch",
    )
    _drop_constraints(
        "agency_customer",
        "unique",
        "uq_agency_customer_quote_binding",
        "uq_agency_customer_branch_no",
        "uq_agency_customer_branch_id",
    )
    _drop_constraints(
        "agency_customer",
        "check",
        "ck_agency_customer_deactivated",
        "ck_agency_customer_lifecycle_revision",
        "ck_agency_customer_consent_evidence",
        "ck_agency_customer_consent_evidence_hash",
        "ck_agency_customer_consent_status",
        "ck_agency_customer_source",
        "ck_agency_customer_no",
        "ck_agency_customer_status",
    )
    _drop_columns(
        "agency_customer",
        "deactivated_at",
        "invited_at",
        "lifecycle_revision",
        "consent_updated_at",
        "consent_evidence_hash",
        "consent_version",
        "consent_status",
        "source_reference",
        "source_type",
        "customer_no",
        "branch_id",
    )
    op.alter_column(
        "agency_customer",
        "user_id",
        existing_type=UUID,
        nullable=False,
    )
    op.create_check_constraint(
        "ck_agency_customer_status",
        "agency_customer",
        "status IN ('prospect', 'active', 'inactive', 'blocked')",
    )
    _drop_constraints(
        "agency_membership",
        "unique",
        "uq_agency_membership_agency_id",
    )
    _drop_constraints(
        "agency_membership",
        "check",
        "ck_agency_membership_role",
    )
    op.create_check_constraint(
        "ck_agency_membership_role",
        "agency_membership",
        "role IN "
        "('travel_advisor', 'booking_operator', 'approver', 'finance', "
        "'auditor', 'admin', 'owner')",
    )
    op.drop_index(
        "ix_agency_branch_agency_status",
        table_name="agency_branch",
    )
    op.drop_table("agency_branch")
