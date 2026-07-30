"""`20260730_0005` 的 revision-frozen PostgreSQL guards。

该模块只属于 0005 revision。发布后不得随应用模型演进而修改；后续数据库
变化必须新增 revision。
"""

from alembic import op


def drop_existing_customer_lifecycle_trigger() -> None:
    op.execute(
        """DROP TRIGGER trg_agency_customer_lifecycle_guard ON agency_customer"""
    )


def replace_customer_lifecycle_guard() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION zhixing_guard_agency_customer_lifecycle()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'agency_customer cannot be deleted';
            END IF;

            IF TG_OP = 'INSERT' THEN
                IF NEW.binding_provenance <> 'unbound'
                    OR NEW.user_id IS NOT NULL
                    OR NEW.claimed_invitation_id IS NOT NULL
                    OR NEW.claimed_at IS NOT NULL
                THEN
                    RAISE EXCEPTION
                        'new agency_customer must start without a direct user binding';
                END IF;
                IF NEW.consent_evidence_origin <> 'none'
                    OR NEW.current_consent_record_id IS NOT NULL
                    OR NEW.consent_status <> 'unknown'
                THEN
                    RAISE EXCEPTION
                        'new agency_customer must start without consent evidence';
                END IF;
                IF NEW.lifecycle_revision <> 1 THEN
                    RAISE EXCEPTION
                        'new agency_customer revision must be one';
                END IF;
            ELSE
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

                IF OLD.binding_provenance = 'secure_claim'
                    AND (
                        NEW.binding_provenance <> 'secure_claim'
                        OR NEW.user_id IS DISTINCT FROM OLD.user_id
                        OR NEW.claimed_invitation_id
                            IS DISTINCT FROM OLD.claimed_invitation_id
                        OR NEW.claimed_at IS DISTINCT FROM OLD.claimed_at
                    )
                THEN
                    RAISE EXCEPTION
                        'secure agency_customer claim binding is immutable';
                END IF;

                IF NEW.binding_provenance = 'legacy_direct'
                    AND OLD.binding_provenance <> 'legacy_direct'
                THEN
                    RAISE EXCEPTION
                        'new direct agency_customer binding is forbidden';
                END IF;

                IF OLD.binding_provenance = 'unbound'
                    AND NEW.binding_provenance
                        NOT IN ('unbound', 'secure_claim')
                THEN
                    RAISE EXCEPTION
                        'unbound agency_customer requires secure claim';
                END IF;

                IF OLD.binding_provenance = 'legacy_direct'
                    AND NEW.binding_provenance
                        NOT IN ('legacy_direct', 'secure_claim')
                THEN
                    RAISE EXCEPTION
                        'legacy agency_customer binding cannot be cleared';
                END IF;

                IF NEW.user_id IS DISTINCT FROM OLD.user_id THEN
                    IF NEW.binding_provenance <> 'secure_claim'
                        OR NEW.claimed_invitation_id IS NULL
                        OR NEW.claimed_at IS NULL
                        OR NEW.status <> 'invited'
                        OR NEW.consent_status NOT IN ('unknown', 'pending')
                    THEN
                        RAISE EXCEPTION
                            'agency_customer user binding requires secure claim';
                    END IF;
                    IF OLD.user_id IS NOT NULL
                        AND NOT (
                            OLD.status = 'invited'
                            AND OLD.consent_status = 'unknown'
                            AND OLD.consent_version IS NULL
                            AND OLD.consent_evidence_hash IS NULL
                            AND OLD.consent_updated_at IS NULL
                        )
                    THEN
                        RAISE EXCEPTION
                            'confirmed agency_customer user binding is immutable';
                    END IF;
                END IF;

                IF NEW.claimed_invitation_id
                        IS DISTINCT FROM OLD.claimed_invitation_id
                    OR NEW.claimed_at IS DISTINCT FROM OLD.claimed_at
                THEN
                    IF OLD.binding_provenance = 'secure_claim'
                        OR NEW.binding_provenance <> 'secure_claim'
                    THEN
                        RAISE EXCEPTION
                            'agency_customer claim pointer is immutable';
                    END IF;
                END IF;

                IF (
                    NEW.consent_status IS DISTINCT FROM OLD.consent_status
                    OR NEW.consent_version
                        IS DISTINCT FROM OLD.consent_version
                    OR NEW.consent_evidence_hash
                        IS DISTINCT FROM OLD.consent_evidence_hash
                    OR NEW.consent_updated_at
                        IS DISTINCT FROM OLD.consent_updated_at
                    OR NEW.current_consent_record_id
                        IS DISTINCT FROM OLD.current_consent_record_id
                    OR NEW.consent_evidence_origin
                        IS DISTINCT FROM OLD.consent_evidence_origin
                ) THEN
                    IF NEW.consent_evidence_origin = 'legacy_client_hash'
                    THEN
                        RAISE EXCEPTION
                            'new legacy client consent evidence is forbidden';
                    END IF;
                    IF NEW.consent_evidence_origin = 'none'
                        AND (
                            NEW.consent_status
                                NOT IN ('unknown', 'pending')
                            OR NEW.current_consent_record_id IS NOT NULL
                            OR (
                                NEW.consent_status = 'pending'
                                AND NEW.binding_provenance <> 'secure_claim'
                            )
                        )
                    THEN
                        RAISE EXCEPTION
                            'pending consent requires a secure customer claim';
                    END IF;
                    IF NEW.consent_evidence_origin = 'server_canonical'
                        AND (
                            NEW.current_consent_record_id IS NULL
                            OR NEW.consent_status
                                NOT IN ('granted', 'denied', 'revoked')
                        )
                    THEN
                        RAISE EXCEPTION
                            'server consent requires a current consent record';
                    END IF;
                    IF NEW.consent_evidence_origin = 'server_canonical'
                        AND NEW.binding_provenance = 'legacy_direct'
                        AND NEW.consent_status NOT IN ('denied', 'revoked')
                    THEN
                        RAISE EXCEPTION
                            'legacy customer may only deny or revoke canonical consent';
                    END IF;
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
            END IF;

            PERFORM 1 FROM agency_branch branch
            WHERE branch.agency_id = NEW.agency_id
              AND branch.id = NEW.branch_id
            FOR SHARE;
            IF NEW.status = 'active' AND (
                NEW.binding_provenance <> 'secure_claim'
                OR NEW.user_id IS NULL
                OR NEW.consent_status <> 'granted'
                OR NEW.consent_version IS NULL
                OR NEW.consent_evidence_hash IS NULL
                OR NEW.current_consent_record_id IS NULL
                OR NEW.consent_evidence_origin <> 'server_canonical'
                OR NOT EXISTS (
                    SELECT 1 FROM agency_branch branch
                    WHERE branch.agency_id = NEW.agency_id
                      AND branch.id = NEW.branch_id
                      AND branch.status = 'active'
                )
            ) THEN
                RAISE EXCEPTION
                    'active customer requires linked user, current consent evidence and active branch';
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


def create_invitation_mutation_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_agency_customer_invitation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION
                    'agency_customer_invitation cannot be deleted';
            END IF;
            IF NEW.token_digest !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION
                    'agency_customer_invitation token digest must be sha256';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'pending' OR NEW.revision <> 1 THEN
                    RAISE EXCEPTION
                        'new agency_customer_invitation must be pending revision one';
                END IF;
            ELSE
                IF OLD.status <> 'pending' THEN
                    RAISE EXCEPTION
                        'terminal agency_customer_invitation is immutable';
                END IF;
                IF NEW.id IS DISTINCT FROM OLD.id
                    OR NEW.agency_id IS DISTINCT FROM OLD.agency_id
                    OR NEW.branch_id IS DISTINCT FROM OLD.branch_id
                    OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
                    OR NEW.target_user_id IS DISTINCT FROM OLD.target_user_id
                    OR NEW.token_digest IS DISTINCT FROM OLD.token_digest
                    OR NEW.issued_by_user_id
                        IS DISTINCT FROM OLD.issued_by_user_id
                    OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
                    OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
                    OR NEW.created_at IS DISTINCT FROM OLD.created_at
                THEN
                    RAISE EXCEPTION
                        'agency_customer_invitation binding is immutable';
                END IF;
                IF NEW.status NOT IN ('claimed', 'revoked') THEN
                    RAISE EXCEPTION
                        'agency_customer_invitation transition is invalid';
                END IF;
                IF NEW.revision <> OLD.revision + 1 THEN
                    RAISE EXCEPTION
                        'agency_customer_invitation revision must advance by one';
                END IF;
                IF NEW.status = 'claimed'
                    AND clock_timestamp() > NEW.expires_at
                THEN
                    RAISE EXCEPTION
                        'expired agency_customer_invitation cannot be claimed';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agency_customer_invitation_guard
        BEFORE INSERT OR UPDATE OR DELETE ON agency_customer_invitation
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_guard_agency_customer_invitation()
        """
    )


def create_consent_record_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_new_agency_customer_consent_record()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            expected_sequence integer;
            current_customer agency_customer%ROWTYPE;
        BEGIN
            SELECT customer.*
            INTO current_customer
            FROM agency_customer customer
            WHERE customer.agency_id = NEW.agency_id
              AND customer.branch_id = NEW.branch_id
              AND customer.id = NEW.customer_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'agency_customer_consent_record customer does not exist';
            END IF;
            IF NEW.evidence_origin <> 'server_canonical' THEN
                RAISE EXCEPTION
                    'new consent record must use server canonical evidence';
            END IF;
            IF NEW.evidence_hash !~ '^[0-9a-f]{64}$'
                OR NEW.consent_document_hash !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION
                    'server consent hashes must be lowercase sha256';
            END IF;
            IF current_customer.user_id IS DISTINCT FROM NEW.user_id THEN
                RAISE EXCEPTION
                    'server consent record user must match customer binding';
            END IF;
            IF current_customer.binding_provenance = 'secure_claim' THEN
                IF NEW.invitation_id IS NULL
                    OR current_customer.claimed_invitation_id
                        IS DISTINCT FROM NEW.invitation_id
                THEN
                    RAISE EXCEPTION
                        'secure consent record requires current claim invitation';
                END IF;
                PERFORM 1
                FROM agency_customer_invitation invitation
                WHERE invitation.agency_id = NEW.agency_id
                  AND invitation.branch_id = NEW.branch_id
                  AND invitation.customer_id = NEW.customer_id
                  AND invitation.id = NEW.invitation_id
                  AND invitation.status = 'claimed'
                  AND invitation.target_user_id = NEW.user_id
                  AND invitation.claimed_by_user_id = NEW.user_id
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'server consent record requires matching claimed invitation';
                END IF;
            ELSIF current_customer.binding_provenance = 'legacy_direct' THEN
                IF NEW.invitation_id IS NOT NULL
                    OR NEW.decision NOT IN ('denied', 'revoked')
                THEN
                    RAISE EXCEPTION
                        'legacy customer may only deny or revoke without invitation';
                END IF;
            ELSE
                RAISE EXCEPTION
                    'server consent record requires a bound customer';
            END IF;
            SELECT COALESCE(MAX(record.consent_sequence), 0) + 1
            INTO expected_sequence
            FROM agency_customer_consent_record record
            WHERE record.agency_id = NEW.agency_id
              AND record.branch_id = NEW.branch_id
              AND record.customer_id = NEW.customer_id;
            IF NEW.consent_sequence <> expected_sequence THEN
                RAISE EXCEPTION
                    'agency_customer_consent_record sequence must advance by one';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agency_customer_consent_record_insert_guard
        BEFORE INSERT ON agency_customer_consent_record
        FOR EACH ROW
        EXECUTE FUNCTION
            zhixing_guard_new_agency_customer_consent_record()
        """
    )
    op.execute(
        """
        CREATE FUNCTION zhixing_reject_agency_customer_consent_record_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION
                'agency_customer_consent_record is append-only';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agency_customer_consent_record_append_only
        BEFORE UPDATE OR DELETE ON agency_customer_consent_record
        FOR EACH ROW
        EXECUTE FUNCTION
            zhixing_reject_agency_customer_consent_record_mutation()
        """
    )


def create_secure_transaction_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_secure_customer_transaction_0005()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM 1
            FROM agency_customer customer
            WHERE customer.agency_id = NEW.agency_id
              AND customer.branch_id = NEW.branch_id
              AND customer.id = NEW.customer_id
              AND customer.user_id = NEW.user_id
              AND customer.status = 'active'
              AND customer.binding_provenance = 'secure_claim'
              AND customer.consent_status = 'granted'
              AND customer.consent_evidence_origin = 'server_canonical'
              AND customer.current_consent_record_id IS NOT NULL
            FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'new % requires secure claimed customer with canonical consent',
                    TG_TABLE_NAME;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agency_quote_0005_secure_customer_guard
        BEFORE INSERT ON agency_quote
        FOR EACH ROW
        EXECUTE FUNCTION
            zhixing_guard_secure_customer_transaction_0005()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agency_order_0005_secure_customer_guard
        BEFORE INSERT ON agency_order
        FOR EACH ROW
        EXECUTE FUNCTION
            zhixing_guard_secure_customer_transaction_0005()
        """
    )


def create_deferred_consistency_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_validate_agency_customer_claim_consent()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            affected_agency_id uuid;
            affected_branch_id uuid;
            affected_customer_id uuid;
            current_customer agency_customer%ROWTYPE;
        BEGIN
            affected_agency_id := NEW.agency_id;
            affected_branch_id := NEW.branch_id;
            IF TG_TABLE_NAME = 'agency_customer' THEN
                affected_customer_id := NEW.id;
            ELSE
                affected_customer_id := NEW.customer_id;
            END IF;

            SELECT customer.*
            INTO current_customer
            FROM agency_customer customer
            WHERE customer.agency_id = affected_agency_id
              AND customer.branch_id = affected_branch_id
              AND customer.id = affected_customer_id;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            IF current_customer.binding_provenance = 'secure_claim' THEN
                PERFORM 1
                FROM agency_customer_invitation invitation
                WHERE invitation.agency_id = current_customer.agency_id
                  AND invitation.branch_id = current_customer.branch_id
                  AND invitation.customer_id = current_customer.id
                  AND invitation.id
                        = current_customer.claimed_invitation_id
                  AND invitation.status = 'claimed'
                  AND invitation.target_user_id = current_customer.user_id
                  AND invitation.claimed_by_user_id
                        = current_customer.user_id
                  AND invitation.claimed_at
                        IS NOT DISTINCT FROM current_customer.claimed_at
                  AND invitation.claimed_at <= invitation.expires_at
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'secure_claim customer must match claimed invitation';
                END IF;
            END IF;

            IF TG_TABLE_NAME = 'agency_customer_invitation'
                AND NEW.status = 'pending'
                AND current_customer.user_id IS NOT NULL
                AND current_customer.user_id IS DISTINCT FROM NEW.target_user_id
                AND NOT (
                    current_customer.binding_provenance = 'legacy_direct'
                    AND current_customer.status = 'invited'
                    AND current_customer.consent_status = 'unknown'
                    AND current_customer.consent_version IS NULL
                    AND current_customer.consent_evidence_hash IS NULL
                    AND current_customer.consent_updated_at IS NULL
                )
            THEN
                RAISE EXCEPTION
                    'pending invitation target does not match customer binding';
            END IF;

            IF current_customer.consent_evidence_origin
                    = 'legacy_client_hash'
            THEN
                PERFORM 1
                FROM agency_customer_consent_record record
                WHERE record.agency_id = current_customer.agency_id
                  AND record.branch_id = current_customer.branch_id
                  AND record.customer_id = current_customer.id
                  AND record.id
                        = current_customer.current_consent_record_id
                  AND record.evidence_origin = 'legacy_client_hash'
                  AND record.user_id
                        IS NOT DISTINCT FROM current_customer.user_id
                  AND record.invitation_id IS NULL
                  AND record.decision = current_customer.consent_status
                  AND record.consent_version
                        = current_customer.consent_version
                  AND record.evidence_hash
                        = current_customer.consent_evidence_hash
                  AND record.recorded_at
                        IS NOT DISTINCT FROM
                            current_customer.consent_updated_at
                  AND NOT EXISTS (
                      SELECT 1
                      FROM agency_customer_consent_record newer
                      WHERE newer.agency_id = record.agency_id
                        AND newer.branch_id = record.branch_id
                        AND newer.customer_id = record.customer_id
                        AND newer.consent_sequence
                            > record.consent_sequence
                  );
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'legacy consent snapshot must match current record';
                END IF;
            ELSIF current_customer.consent_evidence_origin
                    = 'server_canonical'
            THEN
                PERFORM 1
                FROM agency_customer_consent_record record
                WHERE record.agency_id = current_customer.agency_id
                  AND record.branch_id = current_customer.branch_id
                  AND record.customer_id = current_customer.id
                  AND record.id
                        = current_customer.current_consent_record_id
                  AND record.evidence_origin = 'server_canonical'
                  AND record.user_id = current_customer.user_id
                  AND (
                      (
                          current_customer.binding_provenance = 'secure_claim'
                          AND record.invitation_id
                              = current_customer.claimed_invitation_id
                      )
                      OR (
                          current_customer.binding_provenance = 'legacy_direct'
                          AND record.invitation_id IS NULL
                          AND record.decision IN ('denied', 'revoked')
                      )
                  )
                  AND record.consent_document_hash IS NOT NULL
                  AND record.decision = current_customer.consent_status
                  AND record.consent_version
                        = current_customer.consent_version
                  AND record.evidence_hash
                        = current_customer.consent_evidence_hash
                  AND record.recorded_at
                        IS NOT DISTINCT FROM
                            current_customer.consent_updated_at
                  AND NOT EXISTS (
                      SELECT 1
                      FROM agency_customer_consent_record newer
                      WHERE newer.agency_id = record.agency_id
                        AND newer.branch_id = record.branch_id
                        AND newer.customer_id = record.customer_id
                        AND newer.consent_sequence
                            > record.consent_sequence
                  )
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'server consent snapshot must match current record';
                END IF;
            END IF;

            IF TG_TABLE_NAME = 'agency_customer_invitation'
                AND NEW.status = 'claimed'
                AND (
                    current_customer.binding_provenance <> 'secure_claim'
                    OR current_customer.claimed_invitation_id
                        IS DISTINCT FROM NEW.id
                )
            THEN
                RAISE EXCEPTION
                    'claimed invitation must be current customer claim';
            END IF;

            IF TG_TABLE_NAME = 'agency_customer_consent_record' THEN
                IF current_customer.current_consent_record_id
                        IS DISTINCT FROM NEW.id
                    OR current_customer.lifecycle_revision
                        <> NEW.customer_revision
                THEN
                    RAISE EXCEPTION
                        'new consent record must be current customer revision';
                END IF;
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
    for table, trigger, events in (
        (
            "agency_customer",
            "trg_agency_customer_claim_consent_consistency",
            "INSERT OR UPDATE",
        ),
        (
            "agency_customer_invitation",
            "trg_agency_customer_invitation_consistency",
            "INSERT OR UPDATE",
        ),
        (
            "agency_customer_consent_record",
            "trg_agency_customer_consent_record_consistency",
            "INSERT",
        ),
    ):
        op.execute(
            f"""
            CREATE CONSTRAINT TRIGGER {trigger}
            AFTER {events} ON {table}
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW
            EXECUTE FUNCTION
                zhixing_validate_agency_customer_claim_consent()
            """
        )


def restore_0004_customer_lifecycle_guard() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION zhixing_guard_agency_customer_lifecycle()
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


def drop_0005_triggers_and_functions() -> None:
    for table, trigger in (
        (
            "agency_customer_consent_record",
            "trg_agency_customer_consent_record_consistency",
        ),
        (
            "agency_customer_invitation",
            "trg_agency_customer_invitation_consistency",
        ),
        (
            "agency_customer",
            "trg_agency_customer_claim_consent_consistency",
        ),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
    op.execute(
        "DROP FUNCTION zhixing_validate_agency_customer_claim_consent()"
    )

    op.execute(
        "DROP TRIGGER trg_agency_order_0005_secure_customer_guard "
        "ON agency_order"
    )
    op.execute(
        "DROP TRIGGER trg_agency_quote_0005_secure_customer_guard "
        "ON agency_quote"
    )
    op.execute(
        "DROP FUNCTION zhixing_guard_secure_customer_transaction_0005()"
    )

    op.execute(
        "DROP TRIGGER trg_agency_customer_consent_record_append_only "
        "ON agency_customer_consent_record"
    )
    op.execute(
        "DROP FUNCTION "
        "zhixing_reject_agency_customer_consent_record_mutation()"
    )
    op.execute(
        "DROP TRIGGER trg_agency_customer_consent_record_insert_guard "
        "ON agency_customer_consent_record"
    )
    op.execute(
        "DROP FUNCTION zhixing_guard_new_agency_customer_consent_record()"
    )
    op.execute(
        "DROP TRIGGER trg_agency_customer_invitation_guard "
        "ON agency_customer_invitation"
    )
    op.execute("DROP FUNCTION zhixing_guard_agency_customer_invitation()")
