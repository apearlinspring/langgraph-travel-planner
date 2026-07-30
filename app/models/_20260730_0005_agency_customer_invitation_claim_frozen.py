"""`20260730_0005` 的 revision-frozen schema、backfill 与 Alembic 编排。

该模块只属于 0005 revision。发布后不得随应用模型演进而修改；后续数据库
变化必须新增 revision。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.models._20260730_0005_agency_customer_invitation_claim_guards_frozen import (
    create_deferred_consistency_guards,
    create_invitation_mutation_guard,
    create_secure_transaction_guards,
    create_consent_record_guards,
    drop_0005_triggers_and_functions,
    drop_existing_customer_lifecycle_trigger,
    replace_customer_lifecycle_guard,
    restore_0004_customer_lifecycle_guard,
)


UUID = postgresql.UUID(as_uuid=True)
TIMESTAMP = sa.DateTime(timezone=True)


def _raise_if_exists(query: str, message: str) -> None:
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


def _create_invitation_table() -> None:
    op.create_table(
        "agency_customer_invitation",
        sa.Column("id", UUID, nullable=False),
        sa.Column("agency_id", UUID, nullable=False),
        sa.Column("branch_id", UUID, nullable=False),
        sa.Column("customer_id", UUID, nullable=False),
        sa.Column("target_user_id", UUID, nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("issued_by_user_id", UUID, nullable=False),
        sa.Column("issued_at", TIMESTAMP, nullable=False),
        sa.Column("expires_at", TIMESTAMP, nullable=False),
        sa.Column("claimed_by_user_id", UUID, nullable=True),
        sa.Column("claimed_at", TIMESTAMP, nullable=True),
        sa.Column("revoked_by_user_id", UUID, nullable=True),
        sa.Column("revoked_at", TIMESTAMP, nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'claimed', 'revoked')",
            name="ck_agency_customer_invitation_status",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_agency_customer_invitation_revision",
        ),
        sa.CheckConstraint(
            "length(token_digest) = 64",
            name="ck_agency_customer_invitation_token_digest",
        ),
        sa.CheckConstraint(
            "expires_at > issued_at",
            name="ck_agency_customer_invitation_expiry",
        ),
        sa.CheckConstraint(
            "(status = 'pending' "
            "AND claimed_by_user_id IS NULL "
            "AND claimed_at IS NULL "
            "AND revoked_by_user_id IS NULL "
            "AND revoked_at IS NULL "
            "AND revocation_reason IS NULL) "
            "OR (status = 'claimed' "
            "AND claimed_by_user_id IS NOT NULL "
            "AND claimed_by_user_id = target_user_id "
            "AND claimed_at IS NOT NULL "
            "AND claimed_at >= issued_at "
            "AND claimed_at <= expires_at "
            "AND revoked_by_user_id IS NULL "
            "AND revoked_at IS NULL "
            "AND revocation_reason IS NULL) "
            "OR (status = 'revoked' "
            "AND claimed_by_user_id IS NULL "
            "AND claimed_at IS NULL "
            "AND revoked_by_user_id IS NOT NULL "
            "AND revoked_at IS NOT NULL "
            "AND revoked_at >= issued_at "
            "AND revocation_reason IS NOT NULL "
            "AND length(trim(revocation_reason)) > 0)",
            name="ck_agency_customer_invitation_terminal_state",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agency.id"],
            name="fk_agency_customer_invitation_agency",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "branch_id", "customer_id"],
            [
                "agency_customer.agency_id",
                "agency_customer.branch_id",
                "agency_customer.id",
            ],
            name="fk_agency_customer_invitation_customer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["user.id"],
            name="fk_agency_customer_invitation_target_user",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["issued_by_user_id"],
            ["user.id"],
            name="fk_agency_customer_invitation_issuer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["claimed_by_user_id"],
            ["user.id"],
            name="fk_agency_customer_invitation_claimant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"],
            ["user.id"],
            name="fk_agency_customer_invitation_revoker",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "token_digest",
            name="uq_agency_customer_invitation_token_digest",
        ),
        sa.UniqueConstraint(
            "agency_id",
            "branch_id",
            "customer_id",
            "id",
            name="uq_agency_customer_invitation_customer_id",
        ),
    )
    op.create_index(
        "uq_agency_customer_invitation_pending",
        "agency_customer_invitation",
        ["agency_id", "branch_id", "customer_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_agency_customer_invitation_target_pending",
        "agency_customer_invitation",
        ["agency_id", "target_user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_agency_customer_invitation_target_status",
        "agency_customer_invitation",
        ["target_user_id", "status", "expires_at"],
    )
    op.create_index(
        "ix_agency_customer_invitation_customer_status",
        "agency_customer_invitation",
        ["agency_id", "branch_id", "customer_id", "status", "issued_at"],
    )


def _create_consent_record_table() -> None:
    op.create_table(
        "agency_customer_consent_record",
        sa.Column("id", UUID, nullable=False),
        sa.Column("agency_id", UUID, nullable=False),
        sa.Column("branch_id", UUID, nullable=False),
        sa.Column("customer_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=True),
        sa.Column("invitation_id", UUID, nullable=True),
        sa.Column("consent_sequence", sa.Integer(), nullable=False),
        sa.Column("customer_revision", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("consent_version", sa.String(40), nullable=False),
        sa.Column("consent_document_hash", sa.String(64), nullable=True),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("evidence_schema_version", sa.String(40), nullable=False),
        sa.Column("evidence_origin", sa.String(24), nullable=False),
        sa.Column("recorded_at", TIMESTAMP, nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            "consent_sequence >= 1",
            name="ck_agency_customer_consent_record_sequence",
        ),
        sa.CheckConstraint(
            "customer_revision >= 1",
            name="ck_agency_customer_consent_record_customer_revision",
        ),
        sa.CheckConstraint(
            "decision IN ('granted', 'denied', 'revoked')",
            name="ck_agency_customer_consent_record_decision",
        ),
        sa.CheckConstraint(
            "length(trim(consent_version)) > 0",
            name="ck_agency_customer_consent_record_version",
        ),
        sa.CheckConstraint(
            "length(evidence_hash) = 64",
            name="ck_agency_customer_consent_record_evidence_hash",
        ),
        sa.CheckConstraint(
            "consent_document_hash IS NULL "
            "OR length(consent_document_hash) = 64",
            name="ck_agency_customer_consent_record_document_hash",
        ),
        sa.CheckConstraint(
            "length(trim(evidence_schema_version)) > 0",
            name="ck_agency_customer_consent_record_schema_version",
        ),
        sa.CheckConstraint(
            "evidence_origin IN "
            "('legacy_client_hash', 'server_canonical')",
            name="ck_agency_customer_consent_record_origin",
        ),
        sa.CheckConstraint(
            "(evidence_origin = 'legacy_client_hash' "
            "AND invitation_id IS NULL "
            "AND consent_document_hash IS NULL) "
            "OR (evidence_origin = 'server_canonical' "
            "AND user_id IS NOT NULL "
            "AND consent_document_hash IS NOT NULL "
            "AND (invitation_id IS NOT NULL "
            "OR decision IN ('denied', 'revoked')))",
            name="ck_agency_customer_consent_record_evidence_shape",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agency.id"],
            name="fk_agency_customer_consent_record_agency",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "branch_id", "customer_id"],
            [
                "agency_customer.agency_id",
                "agency_customer.branch_id",
                "agency_customer.id",
            ],
            name="fk_agency_customer_consent_record_customer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name="fk_agency_customer_consent_record_user",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id", "branch_id", "customer_id", "invitation_id"],
            [
                "agency_customer_invitation.agency_id",
                "agency_customer_invitation.branch_id",
                "agency_customer_invitation.customer_id",
                "agency_customer_invitation.id",
            ],
            name="fk_agency_customer_consent_record_invitation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agency_id",
            "branch_id",
            "customer_id",
            "id",
            name="uq_agency_customer_consent_record_customer_id",
        ),
        sa.UniqueConstraint(
            "agency_id",
            "branch_id",
            "customer_id",
            "consent_sequence",
            name="uq_agency_customer_consent_record_sequence",
        ),
        sa.UniqueConstraint(
            "agency_id",
            "branch_id",
            "customer_id",
            "customer_revision",
            name="uq_agency_customer_consent_record_revision",
        ),
    )
    op.create_index(
        "ix_agency_customer_consent_record_customer_recorded",
        "agency_customer_consent_record",
        ["agency_id", "branch_id", "customer_id", "recorded_at"],
    )


def _add_and_backfill_customer_columns() -> None:
    for column in (
        sa.Column("binding_provenance", sa.String(24), nullable=True),
        sa.Column("claimed_invitation_id", UUID, nullable=True),
        sa.Column("claimed_at", TIMESTAMP, nullable=True),
        sa.Column("current_consent_record_id", UUID, nullable=True),
        sa.Column("consent_evidence_origin", sa.String(24), nullable=True),
    ):
        op.add_column("agency_customer", column)

    op.execute(
        """
        UPDATE agency_customer
        SET binding_provenance = CASE
                WHEN user_id IS NULL THEN 'unbound'
                ELSE 'legacy_direct'
            END,
            consent_evidence_origin = CASE
                WHEN consent_status IN ('granted', 'denied', 'revoked')
                     AND consent_evidence_hash IS NOT NULL
                THEN 'legacy_client_hash'
                ELSE 'none'
            END
        """
    )
    op.execute(
        """
        INSERT INTO agency_customer_consent_record (
            id, agency_id, branch_id, customer_id, user_id, invitation_id,
            consent_sequence, customer_revision, decision, consent_version,
            consent_document_hash, evidence_hash, evidence_schema_version,
            evidence_origin, recorded_at, created_at
        )
        SELECT
            customer.id,
            customer.agency_id,
            customer.branch_id,
            customer.id,
            customer.user_id,
            NULL,
            1,
            customer.lifecycle_revision,
            customer.consent_status,
            customer.consent_version,
            NULL,
            customer.consent_evidence_hash,
            'legacy.client-hash.v1',
            'legacy_client_hash',
            customer.consent_updated_at,
            customer.consent_updated_at
        FROM agency_customer customer
        WHERE customer.consent_status IN ('granted', 'denied', 'revoked')
          AND customer.consent_version IS NOT NULL
          AND customer.consent_evidence_hash IS NOT NULL
          AND customer.consent_updated_at IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE agency_customer
        SET current_consent_record_id = id
        WHERE consent_evidence_origin = 'legacy_client_hash'
        """
    )
    op.alter_column(
        "agency_customer",
        "binding_provenance",
        existing_type=sa.String(24),
        nullable=False,
    )
    op.alter_column(
        "agency_customer",
        "consent_evidence_origin",
        existing_type=sa.String(24),
        nullable=False,
    )


def _create_customer_constraints_and_pointers() -> None:
    op.create_check_constraint(
        "ck_agency_customer_binding_provenance",
        "agency_customer",
        "binding_provenance IN "
        "('unbound', 'legacy_direct', 'secure_claim')",
    )
    op.create_check_constraint(
        "ck_agency_customer_binding_evidence",
        "agency_customer",
        "(binding_provenance = 'unbound' "
        "AND user_id IS NULL "
        "AND claimed_invitation_id IS NULL "
        "AND claimed_at IS NULL) "
        "OR (binding_provenance = 'legacy_direct' "
        "AND user_id IS NOT NULL "
        "AND claimed_invitation_id IS NULL "
        "AND claimed_at IS NULL) "
        "OR (binding_provenance = 'secure_claim' "
        "AND user_id IS NOT NULL "
        "AND claimed_invitation_id IS NOT NULL "
        "AND claimed_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_agency_customer_consent_evidence_origin",
        "agency_customer",
        "consent_evidence_origin IN "
        "('none', 'legacy_client_hash', 'server_canonical')",
    )
    op.create_check_constraint(
        "ck_agency_customer_consent_record_projection",
        "agency_customer",
        "(consent_evidence_origin = 'none' "
        "AND current_consent_record_id IS NULL "
        "AND consent_evidence_hash IS NULL) "
        "OR (consent_evidence_origin = 'legacy_client_hash' "
        "AND current_consent_record_id IS NOT NULL "
        "AND consent_evidence_hash IS NOT NULL) "
        "OR (consent_evidence_origin = 'server_canonical' "
        "AND current_consent_record_id IS NOT NULL "
        "AND consent_evidence_hash IS NOT NULL)",
    )
    # 存量 active + legacy_direct 必须可原样保留；NOT VALID 仍会约束后续
    # INSERT/UPDATE，避免迁移把历史直接绑定误写成安全认领。
    op.execute(
        """
        ALTER TABLE agency_customer
        ADD CONSTRAINT ck_agency_customer_active_secure_claim
        CHECK (
            status <> 'active'
            OR (
                binding_provenance = 'secure_claim'
                AND consent_status = 'granted'
                AND consent_evidence_origin = 'server_canonical'
            )
        ) NOT VALID
        """
    )
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
    op.create_index(
        "ix_agency_customer_claimed_invitation",
        "agency_customer",
        ["claimed_invitation_id"],
    )
    op.create_index(
        "ix_agency_customer_current_consent_record",
        "agency_customer",
        ["current_consent_record_id"],
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


def upgrade_invitation_claim_schema() -> None:
    drop_existing_customer_lifecycle_trigger()
    _create_invitation_table()
    _create_consent_record_table()
    _add_and_backfill_customer_columns()
    _create_customer_constraints_and_pointers()
    replace_customer_lifecycle_guard()
    create_invitation_mutation_guard()
    create_consent_record_guards()
    create_secure_transaction_guards()
    create_deferred_consistency_guards()


def downgrade_invitation_claim_schema() -> None:
    _raise_if_exists(
        """
        SELECT 1 FROM agency_customer_invitation
        UNION ALL
        SELECT 1 FROM agency_customer_consent_record
        WHERE evidence_origin = 'server_canonical'
        UNION ALL
        SELECT 1 FROM agency_customer
        WHERE binding_provenance = 'secure_claim'
           OR consent_evidence_origin = 'server_canonical'
        """,
        "downgrade blocked: secure customer claim or consent evidence exists",
    )
    drop_0005_triggers_and_functions()
    restore_0004_customer_lifecycle_guard()

    op.drop_constraint(
        "fk_agency_customer_current_consent_record",
        "agency_customer",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_agency_customer_claimed_invitation",
        "agency_customer",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_agency_customer_current_consent_record",
        table_name="agency_customer",
    )
    op.drop_index(
        "ix_agency_customer_claimed_invitation",
        table_name="agency_customer",
    )
    for constraint in (
        "ck_agency_customer_active_secure_claim",
        "ck_agency_customer_consent_record_projection",
        "ck_agency_customer_consent_evidence_origin",
        "ck_agency_customer_binding_evidence",
        "ck_agency_customer_binding_provenance",
    ):
        op.drop_constraint(constraint, "agency_customer", type_="check")

    op.drop_table("agency_customer_consent_record")
    op.drop_table("agency_customer_invitation")

    for column in (
        "consent_evidence_origin",
        "current_consent_record_id",
        "claimed_at",
        "claimed_invitation_id",
        "binding_provenance",
    ):
        op.drop_column("agency_customer", column)
