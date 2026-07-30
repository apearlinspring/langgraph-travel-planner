"""`20260726_0004` 的 revision-frozen Alembic 操作。

该模块是 0004 revision 的组成部分，不是通用 models helper。发布后不得随应用模型
演进而修改；后续数据库变化必须新增 revision。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

UUID = postgresql.UUID(as_uuid=True)
TIMESTAMP = sa.DateTime(timezone=True)


def raise_if_exists(query: str, message: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS ({query}) THEN
                RAISE EXCEPTION '{message}';
            END IF;
        END;
        $$
        """
    )


def foreign_key(
    name: str,
    source: str,
    target: str,
    local: list[str],
    remote: list[str],
) -> None:
    op.create_foreign_key(
        name,
        source,
        target,
        local,
        remote,
        ondelete="RESTRICT",
    )


def drop_constraints(
    table: str,
    constraint_type: str,
    *names: str,
) -> None:
    for name in names:
        op.drop_constraint(name, table, type_=constraint_type)


def drop_columns(table: str, *names: str) -> None:
    for name in names:
        op.drop_column(table, name)


def create_append_only_guard(table: str) -> None:
    function = f"zhixing_reject_{table}_mutation"
    trigger = f"trg_{table}_append_only"
    op.execute(
        f"""
        CREATE FUNCTION {function}()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '{table} is append-only';
        END;
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {trigger}
        BEFORE UPDATE OR DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION {function}()
        """
    )


def create_order_event_trigger() -> None:
    op.execute(
        """
        CREATE TRIGGER trg_agency_order_event_append_only
        BEFORE UPDATE OR DELETE ON agency_order_event
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_reject_agency_order_event_mutation()
        """
    )


def create_review_trigger(*, include_branch: bool) -> None:
    branch_guard = (
        "OR NEW.branch_id IS DISTINCT FROM OLD.branch_id"
        if include_branch
        else ""
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION zhixing_guard_agency_order_review_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'agency_order_review cannot be deleted';
            END IF;
            IF OLD.status <> 'pending' THEN
                RAISE EXCEPTION 'terminal agency_order_review is immutable';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.agency_id IS DISTINCT FROM OLD.agency_id
                {branch_guard}
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
        $$;
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

def _create_revision_guard(
    *,
    table: str,
    function: str,
    trigger: str,
    terminal_status: str,
    bindings: tuple[str, ...],
    required_condition: str,
    required_error: str,
    active_condition: str,
    active_error: str,
    lock_statements: str = "",
    transition_guard: str = "",
) -> None:
    binding_guard = "\n                    OR ".join(
        f"NEW.{column} IS DISTINCT FROM OLD.{column}"
        for column in bindings
    )
    op.execute(
        f"""
        CREATE FUNCTION {function}()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION '{table} cannot be deleted';
            END IF;
            {lock_statements}
            IF TG_OP = 'UPDATE' THEN
                IF OLD.status = '{terminal_status}' THEN
                    RAISE EXCEPTION 'terminal {table} is immutable';
                END IF;
                IF {binding_guard} THEN
                    RAISE EXCEPTION '{table} binding is immutable';
                END IF;
                IF NEW.revision <> OLD.revision + 1 THEN
                    RAISE EXCEPTION '{table} revision must advance by one';
                END IF;
                {transition_guard}
            ELSIF NEW.revision <> 1 THEN
                RAISE EXCEPTION 'new {table} revision must be one';
            END IF;
            IF NOT EXISTS ({required_condition}) THEN
                RAISE EXCEPTION '{required_error}';
            END IF;
            IF NEW.status = 'active' AND NOT EXISTS ({active_condition}) THEN
                RAISE EXCEPTION '{active_error}';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {trigger}
        BEFORE INSERT OR UPDATE OR DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION {function}()
        """
    )


def create_lifecycle_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_agency_branch_lifecycle()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'agency_branch cannot be deleted';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF NEW.id IS DISTINCT FROM OLD.id
                    OR NEW.agency_id IS DISTINCT FROM OLD.agency_id
                    OR NEW.branch_code IS DISTINCT FROM OLD.branch_code
                    OR NEW.created_at IS DISTINCT FROM OLD.created_at
                THEN
                    RAISE EXCEPTION 'agency_branch binding is immutable';
                END IF;
                IF OLD.status = 'closed' THEN
                    RAISE EXCEPTION 'closed agency_branch is immutable';
                END IF;
                IF NEW.revision <> OLD.revision + 1 THEN
                    RAISE EXCEPTION
                        'agency_branch revision must advance by one';
                END IF;
                IF NEW.status <> 'active' AND (
                    EXISTS (
                        SELECT 1 FROM agency_customer customer
                        WHERE customer.agency_id = NEW.agency_id
                          AND customer.branch_id = NEW.id
                          AND customer.status = 'active'
                    )
                    OR EXISTS (
                        SELECT 1 FROM agency_branch_role_grant grant_row
                        WHERE grant_row.agency_id = NEW.agency_id
                          AND grant_row.branch_id = NEW.id
                          AND grant_row.status = 'active'
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM agency_customer_advisor_assignment assignment
                        WHERE assignment.agency_id = NEW.agency_id
                          AND assignment.branch_id = NEW.id
                          AND assignment.status = 'active'
                    )
                    OR EXISTS (
                        SELECT 1 FROM agency_order_review review
                        WHERE review.agency_id = NEW.agency_id
                          AND review.branch_id = NEW.id
                          AND review.status = 'pending'
                    )
                    OR EXISTS (
                        SELECT 1 FROM agency_order order_row
                        WHERE order_row.agency_id = NEW.agency_id
                          AND order_row.branch_id = NEW.id
                          AND order_row.status NOT IN (
                              'review_rejected', 'completed', 'cancelled'
                          )
                    )
                    OR EXISTS (
                        SELECT 1 FROM agency_quote quote
                        WHERE quote.agency_id = NEW.agency_id
                          AND quote.branch_id = NEW.id
                          AND (
                              quote.status IN ('draft', 'offered')
                              OR (
                                  quote.status = 'accepted'
                                  AND NOT EXISTS (
                                      SELECT 1 FROM agency_order order_row
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
                ) THEN
                    RAISE EXCEPTION
                        'active or open branch relations must be closed first';
                END IF;
            ELSIF NEW.revision <> 1 THEN
                RAISE EXCEPTION 'new agency_branch revision must be one';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agency_branch_lifecycle_guard
        BEFORE INSERT OR UPDATE OR DELETE ON agency_branch
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_guard_agency_branch_lifecycle()
        """
    )
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_agency_customer_lifecycle()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'agency_customer cannot be deleted';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF NEW.id IS DISTINCT FROM OLD.id
                    OR NEW.agency_id IS DISTINCT FROM OLD.agency_id
                    OR NEW.branch_id IS DISTINCT FROM OLD.branch_id
                    OR NEW.customer_no IS DISTINCT FROM OLD.customer_no
                    OR NEW.source_type IS DISTINCT FROM OLD.source_type
                    OR NEW.source_reference
                        IS DISTINCT FROM OLD.source_reference
                    OR NEW.created_at IS DISTINCT FROM OLD.created_at
                    OR NEW.invited_at IS DISTINCT FROM OLD.invited_at
                THEN
                    RAISE EXCEPTION 'agency_customer binding is immutable';
                END IF;
                IF OLD.user_id IS NOT NULL
                    AND NEW.user_id IS DISTINCT FROM OLD.user_id
                    AND NOT (
                        OLD.status = 'invited'
                        AND OLD.consent_status = 'unknown'
                        AND OLD.consent_version IS NULL
                        AND OLD.consent_evidence_hash IS NULL
                        AND OLD.consent_updated_at IS NULL
                        AND NEW.user_id IS NOT NULL
                        AND NEW.status = 'invited'
                        AND NEW.consent_status = 'unknown'
                        AND NEW.consent_version IS NULL
                        AND NEW.consent_evidence_hash IS NULL
                        AND NEW.consent_updated_at IS NULL
                    )
                THEN
                    RAISE EXCEPTION
                        'agency_customer user binding is immutable';
                END IF;
                IF OLD.status = 'blocked' AND NEW.status <> 'blocked' THEN
                    RAISE EXCEPTION
                        'blocked agency_customer requires risk review';
                END IF;
                IF OLD.status <> 'active'
                    AND NEW.status = 'active'
                    AND EXISTS (
                        SELECT 1 FROM agency_order order_row
                        WHERE order_row.agency_id = NEW.agency_id
                          AND order_row.branch_id = NEW.branch_id
                          AND order_row.customer_id = NEW.id
                          AND order_row.status = 'pending_review'
                    )
                THEN
                    RAISE EXCEPTION
                        'pending customer order review must be rejected before reactivation';
                END IF;
                IF NEW.lifecycle_revision <> OLD.lifecycle_revision + 1 THEN
                    RAISE EXCEPTION
                        'agency_customer revision must advance by one';
                END IF;
            ELSIF NEW.lifecycle_revision <> 1 THEN
                RAISE EXCEPTION
                    'new agency_customer revision must be one';
            END IF;
            PERFORM 1 FROM agency_branch branch
            WHERE branch.agency_id = NEW.agency_id
              AND branch.id = NEW.branch_id
            FOR SHARE;
            IF NEW.status = 'active' AND (
                NEW.user_id IS NULL
                OR NEW.consent_status <> 'granted'
                OR NEW.consent_version IS NULL
                OR NEW.consent_evidence_hash IS NULL
                OR NOT EXISTS (
                    SELECT 1 FROM agency_branch branch
                    WHERE branch.agency_id = NEW.agency_id
                      AND branch.id = NEW.branch_id
                      AND branch.status = 'active'
                )
            ) THEN
                RAISE EXCEPTION
                    'active customer requires linked user, granted consent and active branch';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agency_customer_lifecycle_guard
        BEFORE INSERT OR UPDATE OR DELETE ON agency_customer
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_guard_agency_customer_lifecycle()
        """
    )
    _create_revision_guard(
        table="agency_customer_advisor_assignment",
        function="zhixing_guard_customer_advisor_assignment",
        trigger="trg_customer_advisor_assignment_guard",
        terminal_status="ended",
        bindings=(
            "id",
            "agency_id",
            "branch_id",
            "customer_id",
            "advisor_role_grant_id",
            "advisor_membership_id",
            "assigned_by_user_id",
            "assignment_reason",
            "assigned_at",
            "created_at",
        ),
        lock_statements="""
            IF NEW.status = 'active' THEN
                PERFORM 1 FROM agency_customer customer
                WHERE customer.agency_id = NEW.agency_id
                  AND customer.branch_id = NEW.branch_id
                  AND customer.id = NEW.customer_id
                FOR UPDATE;
                PERFORM 1 FROM agency_branch branch
                WHERE branch.agency_id = NEW.agency_id
                  AND branch.id = NEW.branch_id
                FOR SHARE;
                PERFORM 1 FROM agency_branch_role_grant grant_row
                WHERE grant_row.agency_id = NEW.agency_id
                  AND grant_row.branch_id = NEW.branch_id
                  AND grant_row.id = NEW.advisor_role_grant_id
                  AND grant_row.membership_id = NEW.advisor_membership_id
                FOR UPDATE;
            END IF;
        """,
        required_condition="""
            SELECT 1
            FROM agency_branch_role_grant grant_row
            WHERE grant_row.agency_id = NEW.agency_id
              AND grant_row.branch_id = NEW.branch_id
              AND grant_row.id = NEW.advisor_role_grant_id
              AND grant_row.membership_id = NEW.advisor_membership_id
              AND grant_row.role = 'travel_advisor'
        """,
        required_error="travel advisor grant binding is required",
        active_condition="""
            SELECT 1
            FROM agency_branch_role_grant grant_row
            JOIN agency_membership membership
              ON membership.agency_id = grant_row.agency_id
             AND membership.id = grant_row.membership_id
            JOIN agency_branch branch
              ON branch.agency_id = grant_row.agency_id
             AND branch.id = grant_row.branch_id
            WHERE grant_row.agency_id = NEW.agency_id
              AND grant_row.branch_id = NEW.branch_id
              AND grant_row.id = NEW.advisor_role_grant_id
              AND grant_row.membership_id = NEW.advisor_membership_id
              AND grant_row.role = 'travel_advisor'
              AND grant_row.status = 'active'
              AND membership.status = 'active'
              AND membership.role = 'travel_advisor'
              AND branch.status = 'active'
        """,
        active_error="active same-branch travel advisor grant is required",
    )
    _create_revision_guard(
        table="agency_branch_role_grant",
        function="zhixing_guard_agency_branch_role_grant",
        trigger="trg_agency_branch_role_grant_guard",
        terminal_status="revoked",
        bindings=(
            "id",
            "agency_id",
            "branch_id",
            "membership_id",
            "role",
            "granted_by_user_id",
            "granted_at",
            "created_at",
        ),
        lock_statements="""
            PERFORM 1 FROM agency_branch branch
            WHERE branch.agency_id = NEW.agency_id
              AND branch.id = NEW.branch_id
            FOR UPDATE;
            PERFORM 1 FROM agency_membership membership
            WHERE membership.agency_id = NEW.agency_id
              AND membership.id = NEW.membership_id
            FOR UPDATE;
        """,
        required_condition="""
            SELECT 1
            FROM agency_membership membership
            WHERE membership.agency_id = NEW.agency_id
              AND membership.id = NEW.membership_id
              AND membership.role = NEW.role
        """,
        required_error="branch grant role must match membership role",
        active_condition="""
            SELECT 1
            FROM agency_membership membership
            JOIN agency_branch branch
              ON branch.agency_id = NEW.agency_id
             AND branch.id = NEW.branch_id
            WHERE membership.agency_id = NEW.agency_id
              AND membership.id = NEW.membership_id
              AND membership.status = 'active'
              AND membership.role = NEW.role
              AND branch.status = 'active'
        """,
        active_error="active membership is required for branch role grant",
        transition_guard="""
            IF NEW.status = 'revoked' AND EXISTS (
                SELECT 1
                FROM agency_customer_advisor_assignment assignment
                WHERE assignment.advisor_role_grant_id = OLD.id
                  AND assignment.status = 'active'
            ) THEN
                RAISE EXCEPTION
                    'active advisor assignment must end before revocation';
            END IF;
            IF NEW.status = 'revoked'
                AND OLD.role = 'approver'
                AND EXISTS (
                    SELECT 1 FROM agency_order_review review
                    WHERE review.agency_id = OLD.agency_id
                      AND review.branch_id = OLD.branch_id
                      AND review.status = 'pending'
                )
                AND NOT EXISTS (
                    SELECT 1 FROM agency_branch_role_grant replacement
                    WHERE replacement.agency_id = OLD.agency_id
                      AND replacement.branch_id = OLD.branch_id
                      AND replacement.role = 'approver'
                      AND replacement.status = 'active'
                      AND replacement.id <> OLD.id
                )
            THEN
                RAISE EXCEPTION
                    'pending reviews require another active approver';
            END IF;
        """,
    )
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_membership_active_grants()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (
                TG_OP = 'DELETE'
                OR (
                    OLD.status = 'active'
                    AND (
                        NEW.status <> 'active'
                        OR NEW.role IS DISTINCT FROM OLD.role
                    )
                )
            ) AND EXISTS (
                SELECT 1 FROM agency_branch_role_grant grant_row
                WHERE grant_row.agency_id = OLD.agency_id
                  AND grant_row.membership_id = OLD.id
                  AND grant_row.status = 'active'
            ) THEN
                RAISE EXCEPTION 'active branch grants must be revoked first';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agency_membership_active_grant_guard
        BEFORE UPDATE OF status, role OR DELETE ON agency_membership
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_guard_membership_active_grants()
        """
    )


def create_branch_table() -> None:
    op.create_table(
        "agency_branch",
        sa.Column("id", UUID, nullable=False),
        sa.Column("agency_id", UUID, nullable=False),
        sa.Column("branch_code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("deactivated_at", TIMESTAMP, nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'closed')",
            name="ck_agency_branch_status",
        ),
        sa.CheckConstraint(
            "length(trim(branch_code)) > 0",
            name="ck_agency_branch_code",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_agency_branch_revision"),
        sa.CheckConstraint(
            "deactivated_at IS NULL OR status <> 'active'",
            name="ck_agency_branch_deactivated",
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
            name="uq_agency_branch_agency_id",
        ),
        sa.UniqueConstraint(
            "agency_id",
            "branch_code",
            name="uq_agency_branch_agency_code",
        ),
    )
    op.create_index(
        "ix_agency_branch_agency_status",
        "agency_branch",
        ["agency_id", "status", "created_at", "id"],
    )


def create_branch_role_grant_table() -> None:
    op.create_table(
        "agency_branch_role_grant",
        sa.Column("id", UUID, nullable=False),
        sa.Column("agency_id", UUID, nullable=False),
        sa.Column("branch_id", UUID, nullable=False),
        sa.Column("membership_id", UUID, nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("granted_by_user_id", UUID, nullable=True),
        sa.Column("granted_at", TIMESTAMP, nullable=False),
        sa.Column("revoked_at", TIMESTAMP, nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            "role IN "
            "('travel_advisor', 'booking_operator', 'approver', 'finance', "
            "'auditor', 'branch_manager')",
            name="ck_branch_role_grant_role",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_branch_role_grant_status",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_branch_role_grant_revision",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND revoked_at IS NULL "
            "AND revocation_reason IS NULL) "
            "OR (status = 'revoked' AND revoked_at IS NOT NULL "
            "AND revocation_reason IS NOT NULL "
            "AND length(trim(revocation_reason)) > 0)",
            name="ck_branch_role_grant_revocation",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "branch_id"],
            ["agency_branch.agency_id", "agency_branch.id"],
            name="fk_branch_role_grant_branch",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "membership_id"],
            ["agency_membership.agency_id", "agency_membership.id"],
            name="fk_branch_role_grant_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"],
            ["user.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agency_id",
            "branch_id",
            "id",
            "membership_id",
            name="uq_branch_role_grant_assignment_binding",
        ),
    )
    op.create_index(
        "uq_branch_role_grant_active",
        "agency_branch_role_grant",
        ["agency_id", "branch_id", "membership_id", "role"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_branch_role_grant_member_status",
        "agency_branch_role_grant",
        ["agency_id", "membership_id", "status"],
    )


def create_customer_event_table() -> None:
    customer_statuses = (
        "('invited', 'prospect', 'active', 'inactive', 'blocked')"
    )
    op.create_table(
        "agency_customer_event",
        sa.Column("id", UUID, nullable=False),
        sa.Column("agency_id", UUID, nullable=False),
        sa.Column("branch_id", UUID, nullable=False),
        sa.Column("customer_id", UUID, nullable=False),
        sa.Column("event_sequence", sa.Integer(), nullable=False),
        sa.Column("customer_revision", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=True),
        sa.Column("actor_user_id", UUID, nullable=True),
        sa.Column("event_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            "event_sequence >= 1",
            name="ck_agency_customer_event_sequence",
        ),
        sa.CheckConstraint(
            "customer_revision >= 1",
            name="ck_agency_customer_event_revision",
        ),
        sa.CheckConstraint(
            f"from_status IS NULL OR from_status IN {customer_statuses}",
            name="ck_agency_customer_event_from_status",
        ),
        sa.CheckConstraint(
            f"to_status IS NULL OR to_status IN {customer_statuses}",
            name="ck_agency_customer_event_to_status",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["user.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "branch_id"],
            ["agency_branch.agency_id", "agency_branch.id"],
            name="fk_agency_customer_event_branch",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "branch_id", "customer_id"],
            [
                "agency_customer.agency_id",
                "agency_customer.branch_id",
                "agency_customer.id",
            ],
            name="fk_agency_customer_event_customer",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agency_id",
            "branch_id",
            "customer_id",
            "event_sequence",
            name="uq_agency_customer_event_sequence",
        ),
    )
    op.create_index(
        "ix_agency_customer_event_customer_created",
        "agency_customer_event",
        ["agency_id", "branch_id", "customer_id", "created_at"],
    )


def create_advisor_assignment_table() -> None:
    op.create_table(
        "agency_customer_advisor_assignment",
        sa.Column("id", UUID, nullable=False),
        sa.Column("agency_id", UUID, nullable=False),
        sa.Column("branch_id", UUID, nullable=False),
        sa.Column("customer_id", UUID, nullable=False),
        sa.Column("advisor_role_grant_id", UUID, nullable=False),
        sa.Column("advisor_membership_id", UUID, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("assigned_by_user_id", UUID, nullable=True),
        sa.Column("assignment_reason", sa.Text(), nullable=True),
        sa.Column("assigned_at", TIMESTAMP, nullable=False),
        sa.Column("ended_at", TIMESTAMP, nullable=True),
        sa.Column("ended_reason", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'ended')",
            name="ck_customer_advisor_assignment_status",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_customer_advisor_assignment_revision",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND ended_at IS NULL "
            "AND ended_reason IS NULL) "
            "OR (status = 'ended' AND ended_at IS NOT NULL "
            "AND ended_reason IS NOT NULL "
            "AND length(trim(ended_reason)) > 0)",
            name="ck_customer_advisor_assignment_ending",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_user_id"],
            ["user.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "branch_id"],
            ["agency_branch.agency_id", "agency_branch.id"],
            name="fk_customer_advisor_assignment_branch",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "branch_id", "customer_id"],
            [
                "agency_customer.agency_id",
                "agency_customer.branch_id",
                "agency_customer.id",
            ],
            name="fk_customer_advisor_assignment_customer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "agency_id",
                "branch_id",
                "advisor_role_grant_id",
                "advisor_membership_id",
            ],
            [
                "agency_branch_role_grant.agency_id",
                "agency_branch_role_grant.branch_id",
                "agency_branch_role_grant.id",
                "agency_branch_role_grant.membership_id",
            ],
            name="fk_customer_advisor_assignment_grant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_customer_advisor_assignment_active",
        "agency_customer_advisor_assignment",
        ["agency_id", "branch_id", "customer_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_customer_advisor_assignment_advisor_status",
        "agency_customer_advisor_assignment",
        ["agency_id", "branch_id", "advisor_membership_id", "status"],
    )


def create_customer_constraints() -> None:
    checks = {
        "ck_agency_customer_status": (
            "status IN "
            "('invited', 'prospect', 'active', 'inactive', 'blocked')"
        ),
        "ck_agency_customer_no": "length(trim(customer_no)) > 0",
        "ck_agency_customer_source": "length(trim(source_type)) > 0",
        "ck_agency_customer_consent_status": (
            "consent_status IN "
            "('unknown', 'pending', 'granted', 'denied', 'revoked')"
        ),
        "ck_agency_customer_consent_evidence_hash": (
            "consent_evidence_hash IS NULL "
            "OR length(consent_evidence_hash) = 64"
        ),
        "ck_agency_customer_consent_evidence": (
            "(consent_status = 'unknown' "
            "AND consent_version IS NULL "
            "AND consent_evidence_hash IS NULL "
            "AND consent_updated_at IS NULL) "
            "OR (consent_status = 'pending' "
            "AND consent_version IS NOT NULL "
            "AND length(trim(consent_version)) > 0 "
            "AND consent_evidence_hash IS NULL "
            "AND consent_updated_at IS NOT NULL) "
            "OR (consent_status IN ('granted', 'denied', 'revoked') "
            "AND consent_version IS NOT NULL "
            "AND length(trim(consent_version)) > 0 "
            "AND consent_evidence_hash IS NOT NULL "
            "AND consent_updated_at IS NOT NULL)"
        ),
        "ck_agency_customer_lifecycle_revision": "lifecycle_revision >= 1",
        "ck_agency_customer_deactivated": (
            "deactivated_at IS NULL OR status IN ('inactive', 'blocked')"
        ),
    }
    for name, condition in checks.items():
        op.create_check_constraint(name, "agency_customer", condition)
    op.create_unique_constraint(
        "uq_agency_customer_branch_id",
        "agency_customer",
        ["agency_id", "branch_id", "id"],
    )
    op.create_unique_constraint(
        "uq_agency_customer_branch_no",
        "agency_customer",
        ["agency_id", "branch_id", "customer_no"],
    )
    op.create_unique_constraint(
        "uq_agency_customer_quote_binding",
        "agency_customer",
        ["agency_id", "branch_id", "id", "user_id"],
    )
    foreign_key(
        "fk_agency_customer_branch",
        "agency_customer",
        "agency_branch",
        ["agency_id", "branch_id"],
        ["agency_id", "id"],
    )
    op.create_index(
        "ix_agency_customer_branch_status",
        "agency_customer",
        ["agency_id", "branch_id", "status", "created_at", "id"],
    )
