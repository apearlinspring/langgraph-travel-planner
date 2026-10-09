"""Revision-frozen PostgreSQL fix for the 0005 customer consistency trigger.

The 0005 trigger function is shared by three tables. PostgreSQL cannot safely
resolve table-specific ``NEW`` fields from a boolean ``AND`` guard, so each
table-specific field access must live inside its own ``TG_TABLE_NAME`` branch.
Later database changes must add a new revision instead of editing this helper.
"""

from alembic import op

from app.models._20260730_0005_agency_customer_invitation_claim_guards_frozen import (
    create_deferred_consistency_guards as _restore_0005_deferred_consistency_guards,
)


_DEFERRED_TRIGGERS: tuple[tuple[str, str, str], ...] = (
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
)


def _drop_deferred_consistency_guards() -> None:
    for table, trigger, _events in reversed(_DEFERRED_TRIGGERS):
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
    op.execute("DROP FUNCTION zhixing_validate_agency_customer_claim_consent()")


def _create_corrected_deferred_consistency_guards() -> None:
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

            IF TG_TABLE_NAME = 'agency_customer_invitation' THEN
                IF NEW.status = 'pending'
                    AND current_customer.user_id IS NOT NULL
                    AND current_customer.user_id
                        IS DISTINCT FROM NEW.target_user_id
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

            IF TG_TABLE_NAME = 'agency_customer_invitation' THEN
                IF NEW.status = 'claimed'
                    AND (
                        current_customer.binding_provenance <> 'secure_claim'
                        OR current_customer.claimed_invitation_id
                            IS DISTINCT FROM NEW.id
                    )
                THEN
                    RAISE EXCEPTION
                        'claimed invitation must be current customer claim';
                END IF;
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
    for table, trigger, events in _DEFERRED_TRIGGERS:
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


def upgrade_customer_claim_trigger_fix() -> None:
    _drop_deferred_consistency_guards()
    _create_corrected_deferred_consistency_guards()


def downgrade_customer_claim_trigger_fix() -> None:
    _drop_deferred_consistency_guards()
    _restore_0005_deferred_consistency_guards()
