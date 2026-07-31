"""`20260731_0008` 的 revision-frozen PostgreSQL guards。

该模块只属于 0008 revision。后续数据库不变量变化必须新增 revision，
不得修改这里已经发布的 trigger/function SQL。
"""

from alembic import op

from app.models._20260730_0005_agency_customer_invitation_claim_guards_frozen import (
    create_consent_record_guards as _restore_0005_consent_record_guards,
    create_invitation_mutation_guard as _restore_0005_invitation_guard,
    replace_customer_lifecycle_guard as _restore_0005_customer_guard,
)
from app.models._20260730_0006_customer_claim_trigger_fix_frozen import (
    _create_corrected_deferred_consistency_guards as _restore_0006_consistency_guards,
)


_PRE_0008_TRIGGERS: tuple[tuple[str, str], ...] = (
    ("agency_branch", "trg_agency_branch_lifecycle_guard"),
    ("agency_customer", "trg_agency_customer_lifecycle_guard"),
    (
        "agency_customer_invitation",
        "trg_agency_customer_invitation_guard",
    ),
    (
        "agency_customer_consent_record",
        "trg_agency_customer_consent_record_insert_guard",
    ),
    (
        "agency_customer_consent_record",
        "trg_agency_customer_consent_record_append_only",
    ),
    (
        "agency_customer",
        "trg_agency_customer_claim_consent_consistency",
    ),
    (
        "agency_customer_invitation",
        "trg_agency_customer_invitation_consistency",
    ),
    (
        "agency_customer_consent_record",
        "trg_agency_customer_consent_record_consistency",
    ),
)

_PRE_0008_FUNCTIONS: tuple[str, ...] = (
    "zhixing_guard_agency_branch_lifecycle",
    "zhixing_guard_agency_customer_lifecycle",
    "zhixing_guard_agency_customer_invitation",
    "zhixing_guard_new_agency_customer_consent_record",
    "zhixing_reject_agency_customer_consent_record_mutation",
    "zhixing_validate_agency_customer_claim_consent",
)


def drop_pre_0008_branch_customer_guards() -> None:
    for table_name, trigger_name in reversed(_PRE_0008_TRIGGERS):
        op.execute(f"DROP TRIGGER {trigger_name} ON {table_name}")
    for function_name in reversed(_PRE_0008_FUNCTIONS):
        op.execute(f"DROP FUNCTION {function_name}()")


def _create_branch_lifecycle_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_agency_branch_lifecycle()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'agency_branch cannot be deleted';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'active'
                    OR NEW.revision <> 1
                    OR NEW.deactivated_at IS NOT NULL
                    OR NEW.closed_at IS NOT NULL
                THEN
                    RAISE EXCEPTION
                        'new agency_branch must start active at revision one';
                END IF;
                RETURN NEW;
            END IF;

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
                RAISE EXCEPTION 'agency_branch revision must advance by one';
            END IF;

            IF NEW.status = OLD.status THEN
                IF NEW.deactivated_at IS DISTINCT FROM OLD.deactivated_at
                    OR NEW.closed_at IS DISTINCT FROM OLD.closed_at
                THEN
                    RAISE EXCEPTION
                        'agency_branch lifecycle timestamps are immutable without transition';
                END IF;
                RETURN NEW;
            END IF;

            IF OLD.status = 'active' AND NEW.status = 'inactive' THEN
                IF OLD.deactivated_at IS NOT NULL
                    OR NEW.deactivated_at IS NULL
                    OR NEW.closed_at IS NOT NULL
                THEN
                    RAISE EXCEPTION
                        'inactive agency_branch requires deactivated_at only';
                END IF;
                RETURN NEW;
            END IF;

            IF OLD.status = 'inactive' AND NEW.status = 'closed' THEN
                IF NEW.deactivated_at IS DISTINCT FROM OLD.deactivated_at
                    OR NEW.closed_at IS NULL
                    OR NEW.closed_at < NEW.deactivated_at
                THEN
                    RAISE EXCEPTION
                        'closed agency_branch requires ordered lifecycle timestamps';
                END IF;
                IF EXISTS (
                    SELECT 1
                    FROM agency_customer customer
                    WHERE customer.agency_id = NEW.agency_id
                      AND customer.branch_id = NEW.id
                )
                OR EXISTS (
                    SELECT 1
                    FROM agency_customer_invitation invitation
                    WHERE invitation.agency_id = NEW.agency_id
                      AND invitation.branch_id = NEW.id
                      AND invitation.status = 'pending'
                )
                OR EXISTS (
                    SELECT 1
                    FROM agency_customer_advisor_assignment assignment
                    WHERE assignment.agency_id = NEW.agency_id
                      AND assignment.branch_id = NEW.id
                      AND assignment.status = 'active'
                )
                OR EXISTS (
                    SELECT 1
                    FROM agency_branch_role_grant grant_row
                    WHERE grant_row.agency_id = NEW.agency_id
                      AND grant_row.branch_id = NEW.id
                      AND grant_row.status = 'active'
                )
                OR EXISTS (
                    SELECT 1
                    FROM agency_order_review review
                    WHERE review.agency_id = NEW.agency_id
                      AND review.branch_id = NEW.id
                      AND review.status = 'pending'
                )
                OR EXISTS (
                    SELECT 1
                    FROM agency_order order_row
                    WHERE order_row.agency_id = NEW.agency_id
                      AND order_row.branch_id = NEW.id
                      AND order_row.status NOT IN (
                          'review_rejected', 'completed', 'cancelled'
                      )
                )
                OR EXISTS (
                    SELECT 1
                    FROM agency_quote quote
                    WHERE quote.agency_id = NEW.agency_id
                      AND quote.branch_id = NEW.id
                      AND (
                          quote.status IN ('draft', 'offered')
                          OR (
                              quote.status = 'accepted'
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM agency_order order_row
                                  WHERE order_row.agency_id = quote.agency_id
                                    AND order_row.branch_id = quote.branch_id
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
                    WHERE case_row.agency_id = NEW.agency_id
                      AND case_row.branch_id = NEW.id
                      AND case_row.status IN (
                          'approval_pending',
                          'action_pending',
                          'reconciliation_pending',
                          'manual_intervention'
                      )
                )
                THEN
                    RAISE EXCEPTION
                        'agency_branch closure requires zero current customers and open work';
                END IF;
                RETURN NEW;
            END IF;

            RAISE EXCEPTION 'invalid agency_branch status transition';
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


def _create_branch_lifecycle_event_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_agency_branch_lifecycle_event_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            current_branch agency_branch%ROWTYPE;
            expected_sequence integer;
        BEGIN
            SELECT branch.*
            INTO current_branch
            FROM agency_branch branch
            WHERE branch.agency_id = NEW.agency_id
              AND branch.id = NEW.branch_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'agency_branch_lifecycle_event branch does not exist';
            END IF;

            PERFORM 1
            FROM agency_membership membership
            JOIN agency agency_row
              ON agency_row.id = membership.agency_id
             AND agency_row.status = 'active'
            WHERE membership.agency_id = NEW.agency_id
              AND membership.user_id = NEW.actor_user_id
              AND membership.role IN ('owner', 'admin')
              AND membership.status = 'active'
            FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'branch lifecycle event requires active owner or admin';
            END IF;

            SELECT COALESCE(MAX(event.event_sequence), 0) + 1
            INTO expected_sequence
            FROM agency_branch_lifecycle_event event
            WHERE event.agency_id = NEW.agency_id
              AND event.branch_id = NEW.branch_id;
            IF NEW.event_sequence <> expected_sequence THEN
                RAISE EXCEPTION
                    'agency_branch_lifecycle_event sequence must advance by one';
            END IF;

            IF NEW.event_type = 'deactivated' AND NOT (
                (
                    current_branch.status = 'active'
                    AND NEW.branch_revision = current_branch.revision + 1
                )
                OR (
                    current_branch.status = 'inactive'
                    AND NEW.branch_revision = current_branch.revision
                )
            ) THEN
                RAISE EXCEPTION
                    'deactivated event must bind active to inactive revision';
            END IF;
            IF NEW.event_type = 'closed' AND NOT (
                (
                    current_branch.status = 'inactive'
                    AND NEW.branch_revision = current_branch.revision + 1
                )
                OR (
                    current_branch.status = 'closed'
                    AND NEW.branch_revision = current_branch.revision
                )
            ) THEN
                RAISE EXCEPTION
                    'closed event must bind inactive to closed revision';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agency_branch_lifecycle_event_insert_guard
        BEFORE INSERT ON agency_branch_lifecycle_event
        FOR EACH ROW
        EXECUTE FUNCTION
            zhixing_guard_agency_branch_lifecycle_event_insert()
        """
    )
    op.execute(
        """
        CREATE FUNCTION zhixing_validate_agency_branch_lifecycle_event()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            current_branch agency_branch%ROWTYPE;
            expected_event_type text;
        BEGIN
            IF TG_TABLE_NAME = 'agency_branch' THEN
                IF NEW.status IS NOT DISTINCT FROM OLD.status THEN
                    RETURN NULL;
                END IF;
                expected_event_type := CASE NEW.status
                    WHEN 'inactive' THEN 'deactivated'
                    WHEN 'closed' THEN 'closed'
                    ELSE NULL
                END;
                PERFORM 1
                FROM agency_branch_lifecycle_event event
                WHERE event.agency_id = NEW.agency_id
                  AND event.branch_id = NEW.id
                  AND event.branch_revision = NEW.revision
                  AND event.event_type = expected_event_type;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'agency_branch lifecycle transition requires audit event';
                END IF;
                RETURN NULL;
            END IF;

            SELECT branch.*
            INTO current_branch
            FROM agency_branch branch
            WHERE branch.agency_id = NEW.agency_id
              AND branch.id = NEW.branch_id;
            IF NOT FOUND
                OR current_branch.revision <> NEW.branch_revision
                OR current_branch.status <> CASE NEW.event_type
                    WHEN 'deactivated' THEN 'inactive'
                    WHEN 'closed' THEN 'closed'
                END
            THEN
                RAISE EXCEPTION
                    'agency_branch lifecycle event does not match branch';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER
            trg_agency_branch_lifecycle_state_consistency
        AFTER UPDATE OF status ON agency_branch
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_validate_agency_branch_lifecycle_event()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER
            trg_agency_branch_lifecycle_event_consistency
        AFTER INSERT ON agency_branch_lifecycle_event
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_validate_agency_branch_lifecycle_event()
        """
    )


def _create_customer_lifecycle_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_agency_customer_lifecycle()
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
                PERFORM 1
                FROM agency_branch branch
                WHERE branch.agency_id = NEW.agency_id
                  AND branch.id = NEW.branch_id
                  AND branch.status = 'active'
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'new agency_customer requires active branch';
                END IF;
            ELSE
                IF NEW.id IS DISTINCT FROM OLD.id
                    OR NEW.agency_id IS DISTINCT FROM OLD.agency_id
                    OR NEW.customer_no IS DISTINCT FROM OLD.customer_no
                    OR NEW.source_type IS DISTINCT FROM OLD.source_type
                    OR NEW.source_reference
                        IS DISTINCT FROM OLD.source_reference
                    OR NEW.created_at IS DISTINCT FROM OLD.created_at
                    OR NEW.invited_at IS DISTINCT FROM OLD.invited_at
                THEN
                    RAISE EXCEPTION 'agency_customer binding is immutable';
                END IF;

                IF NEW.branch_id IS DISTINCT FROM OLD.branch_id THEN
                    IF NEW.user_id IS DISTINCT FROM OLD.user_id
                        OR NEW.binding_provenance
                            IS DISTINCT FROM OLD.binding_provenance
                        OR NEW.claimed_invitation_id
                            IS DISTINCT FROM OLD.claimed_invitation_id
                        OR NEW.claimed_at IS DISTINCT FROM OLD.claimed_at
                        OR NEW.status IS DISTINCT FROM OLD.status
                        OR NEW.consent_status
                            IS DISTINCT FROM OLD.consent_status
                        OR NEW.consent_version
                            IS DISTINCT FROM OLD.consent_version
                        OR NEW.consent_evidence_hash
                            IS DISTINCT FROM OLD.consent_evidence_hash
                        OR NEW.current_consent_record_id
                            IS DISTINCT FROM OLD.current_consent_record_id
                        OR NEW.consent_evidence_origin
                            IS DISTINCT FROM OLD.consent_evidence_origin
                        OR NEW.consent_updated_at
                            IS DISTINCT FROM OLD.consent_updated_at
                        OR NEW.activated_at IS DISTINCT FROM OLD.activated_at
                        OR NEW.deactivated_at
                            IS DISTINCT FROM OLD.deactivated_at
                    THEN
                        RAISE EXCEPTION
                            'agency_customer branch transfer cannot change lifecycle projection';
                    END IF;
                    PERFORM 1
                    FROM agency_branch branch
                    WHERE branch.agency_id = NEW.agency_id
                      AND branch.id = NEW.branch_id
                      AND branch.status = 'active'
                    FOR SHARE;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION
                            'agency_customer transfer requires active target branch';
                    END IF;
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
                            NEW.consent_status NOT IN ('unknown', 'pending')
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
                        SELECT 1
                        FROM agency_order order_row
                        WHERE order_row.agency_id = NEW.agency_id
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

            PERFORM 1
            FROM agency_branch branch
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
                    SELECT 1
                    FROM agency_branch branch
                    WHERE branch.agency_id = NEW.agency_id
                      AND branch.id = NEW.branch_id
                      AND (
                          branch.status = 'active'
                          OR (
                              branch.status = 'inactive'
                              AND TG_OP = 'UPDATE'
                              AND OLD.status = 'active'
                              AND NEW.branch_id
                                  IS NOT DISTINCT FROM OLD.branch_id
                              AND NEW.user_id
                                  IS NOT DISTINCT FROM OLD.user_id
                              AND NEW.binding_provenance
                                  IS NOT DISTINCT
                                      FROM OLD.binding_provenance
                              AND NEW.claimed_invitation_id
                                  IS NOT DISTINCT
                                      FROM OLD.claimed_invitation_id
                              AND NEW.claimed_at
                                  IS NOT DISTINCT FROM OLD.claimed_at
                              AND NEW.status
                                  IS NOT DISTINCT FROM OLD.status
                              AND NEW.consent_status
                                  IS NOT DISTINCT FROM OLD.consent_status
                              AND NEW.consent_version
                                  IS NOT DISTINCT FROM OLD.consent_version
                              AND NEW.consent_evidence_hash
                                  IS NOT DISTINCT
                                      FROM OLD.consent_evidence_hash
                              AND NEW.current_consent_record_id
                                  IS NOT DISTINCT
                                      FROM OLD.current_consent_record_id
                              AND NEW.consent_evidence_origin
                                  IS NOT DISTINCT
                                      FROM OLD.consent_evidence_origin
                              AND NEW.consent_updated_at
                                  IS NOT DISTINCT
                                      FROM OLD.consent_updated_at
                              AND NEW.activated_at
                                  IS NOT DISTINCT FROM OLD.activated_at
                              AND NEW.deactivated_at
                                  IS NOT DISTINCT FROM OLD.deactivated_at
                          )
                      )
                )
            ) THEN
                RAISE EXCEPTION
                    'active customer requires current consent and active branch except unchanged drain revision';
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


def _create_customer_branch_transfer_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_customer_branch_transfer_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            current_customer agency_customer%ROWTYPE;
        BEGIN
            SELECT customer.*
            INTO current_customer
            FROM agency_customer customer
            WHERE customer.agency_id = NEW.agency_id
              AND customer.id = NEW.customer_id
            FOR UPDATE;
            IF NOT FOUND OR NOT (
                (
                    current_customer.branch_id = NEW.from_branch_id
                    AND current_customer.lifecycle_revision + 1
                        = NEW.customer_revision
                )
                OR (
                    current_customer.branch_id = NEW.to_branch_id
                    AND current_customer.lifecycle_revision
                        = NEW.customer_revision
                )
            ) THEN
                RAISE EXCEPTION
                    'customer branch transfer does not match current customer revision';
            END IF;

            PERFORM 1
            FROM agency_branch branch
            WHERE branch.agency_id = NEW.agency_id
              AND branch.id IN (NEW.from_branch_id, NEW.to_branch_id)
            ORDER BY branch.id
            FOR UPDATE;
            IF NOT EXISTS (
                SELECT 1
                FROM agency_branch branch
                WHERE branch.agency_id = NEW.agency_id
                  AND branch.id = NEW.from_branch_id
                  AND branch.status IN ('active', 'inactive')
            ) OR NOT EXISTS (
                SELECT 1
                FROM agency_branch branch
                WHERE branch.agency_id = NEW.agency_id
                  AND branch.id = NEW.to_branch_id
                  AND branch.status = 'active'
            ) THEN
                RAISE EXCEPTION
                    'customer branch transfer requires valid source and active target';
            END IF;

            PERFORM 1
            FROM agency_membership membership
            JOIN agency agency_row
              ON agency_row.id = membership.agency_id
             AND agency_row.status = 'active'
            WHERE membership.agency_id = NEW.agency_id
              AND membership.user_id = NEW.transferred_by_user_id
              AND membership.role IN ('owner', 'admin')
              AND membership.status = 'active'
            FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'customer branch transfer requires active owner or admin';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM agency_customer_invitation invitation
                WHERE invitation.agency_id = NEW.agency_id
                  AND invitation.customer_id = NEW.customer_id
                  AND invitation.status = 'pending'
            ) THEN
                RAISE EXCEPTION
                    'customer branch transfer requires pending invitation cleanup';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM agency_quote quote
                WHERE quote.agency_id = NEW.agency_id
                  AND quote.customer_id = NEW.customer_id
                  AND (
                      quote.status IN ('draft', 'offered')
                      OR (
                          quote.status = 'accepted'
                          AND NOT EXISTS (
                              SELECT 1
                              FROM agency_order order_row
                              WHERE order_row.agency_id = quote.agency_id
                                AND order_row.quote_id = quote.id
                          )
                      )
                  )
            ) OR EXISTS (
                SELECT 1
                FROM agency_order order_row
                WHERE order_row.agency_id = NEW.agency_id
                  AND order_row.customer_id = NEW.customer_id
                  AND order_row.status NOT IN (
                      'review_rejected', 'completed', 'cancelled'
                  )
            ) OR EXISTS (
                SELECT 1
                FROM agency_order_review review
                JOIN agency_order order_row
                  ON order_row.agency_id = review.agency_id
                 AND order_row.branch_id = review.branch_id
                 AND order_row.id = review.order_id
                WHERE order_row.agency_id = NEW.agency_id
                  AND order_row.customer_id = NEW.customer_id
                  AND review.status = 'pending'
            ) OR EXISTS (
                SELECT 1
                FROM agency_order_cancellation_case case_row
                WHERE case_row.agency_id = NEW.agency_id
                  AND case_row.customer_id = NEW.customer_id
                  AND case_row.status IN (
                      'approval_pending',
                      'action_pending',
                      'reconciliation_pending',
                      'manual_intervention'
                  )
            ) THEN
                RAISE EXCEPTION
                    'customer branch transfer requires open work cleanup';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_customer_branch_transfer_insert_guard
        BEFORE INSERT ON agency_customer_branch_transfer
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_guard_customer_branch_transfer_insert()
        """
    )
    op.execute(
        """
        CREATE FUNCTION zhixing_validate_customer_branch_transfer()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            current_transfer agency_customer_branch_transfer%ROWTYPE;
            current_customer agency_customer%ROWTYPE;
        BEGIN
            IF TG_TABLE_NAME = 'agency_customer' THEN
                IF NEW.branch_id IS NOT DISTINCT FROM OLD.branch_id THEN
                    RETURN NULL;
                END IF;
                SELECT transfer.*
                INTO current_transfer
                FROM agency_customer_branch_transfer transfer
                WHERE transfer.agency_id = NEW.agency_id
                  AND transfer.customer_id = NEW.id
                  AND transfer.from_branch_id = OLD.branch_id
                  AND transfer.to_branch_id = NEW.branch_id
                  AND transfer.customer_revision = NEW.lifecycle_revision;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'agency_customer branch change requires matching transfer';
                END IF;
            ELSE
                current_transfer := NEW;
            END IF;

            SELECT customer.*
            INTO current_customer
            FROM agency_customer customer
            WHERE customer.agency_id = current_transfer.agency_id
              AND customer.id = current_transfer.customer_id;
            IF NOT FOUND
                OR current_customer.branch_id
                    <> current_transfer.to_branch_id
                OR current_customer.lifecycle_revision
                    <> current_transfer.customer_revision
            THEN
                RAISE EXCEPTION
                    'customer branch transfer must match final customer state';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM agency_customer_advisor_assignment assignment
                WHERE assignment.agency_id = current_transfer.agency_id
                  AND assignment.customer_id = current_transfer.customer_id
                  AND assignment.status = 'active'
                  AND (
                      assignment.branch_id <> current_transfer.to_branch_id
                      OR current_customer.status <> 'active'
                  )
            ) THEN
                RAISE EXCEPTION
                    'active advisor assignment requires active customer in transferred branch';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER
            trg_customer_branch_transfer_consistency
        AFTER INSERT ON agency_customer_branch_transfer
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_validate_customer_branch_transfer()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER
            trg_agency_customer_branch_transfer_consistency
        AFTER UPDATE OF branch_id ON agency_customer
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_validate_customer_branch_transfer()
        """
    )


def _create_invitation_guard() -> None:
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
                PERFORM 1
                FROM agency_customer customer
                JOIN agency_branch branch
                  ON branch.agency_id = customer.agency_id
                 AND branch.id = customer.branch_id
                 AND branch.status = 'active'
                WHERE customer.agency_id = NEW.agency_id
                  AND customer.id = NEW.customer_id
                  AND customer.branch_id = NEW.branch_id
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'new invitation must match customer current active branch';
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
                IF NEW.status NOT IN ('claimed', 'revoked')
                    OR NEW.revision <> OLD.revision + 1
                THEN
                    RAISE EXCEPTION
                        'agency_customer_invitation transition is invalid';
                END IF;
                IF NEW.status = 'claimed' THEN
                    IF clock_timestamp() > NEW.expires_at THEN
                        RAISE EXCEPTION
                            'expired agency_customer_invitation cannot be claimed';
                    END IF;
                    PERFORM 1
                    FROM agency_customer customer
                    JOIN agency_branch branch
                      ON branch.agency_id = customer.agency_id
                     AND branch.id = customer.branch_id
                     AND branch.status = 'active'
                    WHERE customer.agency_id = NEW.agency_id
                      AND customer.id = NEW.customer_id
                      AND customer.branch_id = NEW.branch_id
                    FOR SHARE;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION
                            'claimed invitation must match customer current active branch';
                    END IF;
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


def _create_consent_record_guards() -> None:
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
              AND customer.id = NEW.customer_id
              AND customer.branch_id = NEW.branch_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'new consent record must match customer current branch';
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


def _create_customer_event_insert_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_agency_customer_event_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            current_customer agency_customer%ROWTYPE;
            expected_sequence integer;
        BEGIN
            SELECT customer.*
            INTO current_customer
            FROM agency_customer customer
            WHERE customer.agency_id = NEW.agency_id
              AND customer.id = NEW.customer_id
              AND customer.branch_id = NEW.branch_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'new agency_customer_event must match current branch';
            END IF;
            IF NEW.customer_revision <> current_customer.lifecycle_revision
            THEN
                RAISE EXCEPTION
                    'new agency_customer_event must match customer revision';
            END IF;
            SELECT COALESCE(MAX(event.event_sequence), 0) + 1
            INTO expected_sequence
            FROM agency_customer_event event
            WHERE event.agency_id = NEW.agency_id
              AND event.customer_id = NEW.customer_id;
            IF NEW.event_sequence <> expected_sequence THEN
                RAISE EXCEPTION
                    'agency_customer_event sequence must advance by one';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agency_customer_event_insert_guard
        BEFORE INSERT ON agency_customer_event
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_guard_agency_customer_event_insert()
        """
    )


def _create_assignment_current_branch_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION
            zhixing_validate_customer_advisor_assignment_current_branch()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (TG_OP = 'INSERT' OR NEW.status = 'active') AND NOT EXISTS (
                SELECT 1
                FROM agency_customer customer
                WHERE customer.agency_id = NEW.agency_id
                  AND customer.id = NEW.customer_id
                  AND customer.branch_id = NEW.branch_id
                  AND customer.status = 'active'
            ) THEN
                RAISE EXCEPTION
                    'active advisor assignment requires active customer in current branch';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER
            trg_customer_advisor_assignment_current_branch_consistency
        AFTER INSERT OR UPDATE OF status, branch_id, customer_id
        ON agency_customer_advisor_assignment
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION
            zhixing_validate_customer_advisor_assignment_current_branch()
        """
    )


def _create_claim_consent_consistency_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_validate_agency_customer_claim_consent()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            affected_agency_id uuid;
            affected_customer_id uuid;
            current_customer agency_customer%ROWTYPE;
        BEGIN
            affected_agency_id := NEW.agency_id;
            IF TG_TABLE_NAME = 'agency_customer' THEN
                affected_customer_id := NEW.id;
            ELSE
                affected_customer_id := NEW.customer_id;
            END IF;

            SELECT customer.*
            INTO current_customer
            FROM agency_customer customer
            WHERE customer.agency_id = affected_agency_id
              AND customer.id = affected_customer_id;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            IF current_customer.binding_provenance = 'secure_claim' THEN
                PERFORM 1
                FROM agency_customer_invitation invitation
                WHERE invitation.agency_id = current_customer.agency_id
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
            IF TG_TABLE_NAME = 'agency_customer_consent_record'
                AND (
                    current_customer.current_consent_record_id
                        IS DISTINCT FROM NEW.id
                    OR current_customer.lifecycle_revision
                        <> NEW.customer_revision
                )
            THEN
                RAISE EXCEPTION
                    'new consent record must be current customer revision';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
    for table_name, trigger_name, events in (
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
            CREATE CONSTRAINT TRIGGER {trigger_name}
            AFTER {events} ON {table_name}
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW
            EXECUTE FUNCTION
                zhixing_validate_agency_customer_claim_consent()
            """
        )


def _replace_order_review_consistency_guard(
    *,
    inactive_rejection_enabled: bool,
) -> None:
    terminal_branch_predicate = (
        """
              AND (
                  (
                      current_review.status = 'approved'
                      AND branch.status = 'active'
                  )
                  OR (
                      current_review.status = 'rejected'
                      AND branch.status IN ('active', 'inactive')
                  )
              )
        """
        if inactive_rejection_enabled
        else "AND branch.status = 'active'"
    )
    terminal_approver_error = (
        "agency_order_review requires eligible branch approver"
        if inactive_rejection_enabled
        else "agency_order_review requires active branch approver"
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION
            zhixing_validate_agency_order_review_consistency()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            current_order agency_order%ROWTYPE;
            current_review agency_order_review%ROWTYPE;
            expected_order_status text;
        BEGIN
            IF TG_TABLE_NAME = 'agency_order' THEN
                SELECT * INTO current_order
                FROM agency_order
                WHERE id = NEW.id;
                IF current_order.status NOT IN (
                    'pending_review', 'approved', 'review_rejected'
                ) THEN
                    RETURN NULL;
                END IF;
                IF current_order.status = 'pending_review' THEN
                    SELECT * INTO current_review
                    FROM agency_order_review
                    WHERE agency_id = current_order.agency_id
                      AND branch_id = current_order.branch_id
                      AND order_id = current_order.id
                      AND order_revision = current_order.revision
                      AND status = 'pending';
                ELSE
                    SELECT * INTO current_review
                    FROM agency_order_review
                    WHERE agency_id = current_order.agency_id
                      AND branch_id = current_order.branch_id
                      AND order_id = current_order.id
                      AND decision_order_revision = current_order.revision
                      AND status = CASE current_order.status
                          WHEN 'approved' THEN 'approved'
                          ELSE 'rejected'
                      END;
                END IF;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'agency_order requires matching final review state';
                END IF;
            ELSE
                SELECT * INTO current_review
                FROM agency_order_review
                WHERE id = NEW.id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'agency_order_review cannot disappear';
                END IF;
                SELECT * INTO current_order
                FROM agency_order
                WHERE agency_id = current_review.agency_id
                  AND branch_id = current_review.branch_id
                  AND id = current_review.order_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'agency_order_review requires matching order';
                END IF;
            END IF;

            IF current_review.agency_id
                    IS DISTINCT FROM current_order.agency_id
                OR current_review.branch_id
                    IS DISTINCT FROM current_order.branch_id
                OR current_review.order_id IS DISTINCT FROM current_order.id
                OR current_review.payload_hash
                    IS DISTINCT FROM current_order.payload_hash
                OR current_review.total_amount
                    IS DISTINCT FROM current_order.total_amount
                OR current_review.currency
                    IS DISTINCT FROM current_order.currency
                OR current_review.requested_by_user_id
                    IS DISTINCT FROM current_order.user_id
            THEN
                RAISE EXCEPTION
                    'agency_order_review binding does not match order';
            END IF;

            IF current_review.status = 'pending' THEN
                IF current_order.status <> 'pending_review'
                    OR current_review.order_revision
                        <> current_order.revision
                    OR current_review.decision_order_revision IS NOT NULL
                THEN
                    RAISE EXCEPTION
                        'pending agency_order_review does not match order';
                END IF;
                PERFORM 1
                FROM agency_membership membership
                JOIN agency
                  ON agency.id = membership.agency_id
                 AND agency.status = 'active'
                JOIN agency_branch_role_grant grant_row
                  ON grant_row.agency_id = membership.agency_id
                 AND grant_row.membership_id = membership.id
                JOIN agency_branch branch
                  ON branch.agency_id = grant_row.agency_id
                 AND branch.id = grant_row.branch_id
                 AND branch.status = 'active'
                WHERE membership.agency_id = current_review.agency_id
                  AND membership.role = 'approver'
                  AND membership.status = 'active'
                  AND grant_row.branch_id = current_review.branch_id
                  AND grant_row.role = 'approver'
                  AND grant_row.status = 'active'
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'pending review requires active branch approver';
                END IF;
                RETURN NULL;
            END IF;

            expected_order_status = CASE current_review.status
                WHEN 'approved' THEN 'approved'
                ELSE 'review_rejected'
            END;
            IF current_order.status <> expected_order_status
                OR current_review.order_revision + 1
                    <> current_order.revision
                OR current_review.decision_order_revision
                    IS DISTINCT FROM current_order.revision
                OR current_review.decided_by_user_id
                    IS NOT DISTINCT FROM current_order.user_id
            THEN
                IF current_review.decided_by_user_id
                    IS NOT DISTINCT FROM current_order.user_id
                THEN
                    RAISE EXCEPTION
                        'order customer cannot decide agency_order_review';
                END IF;
                RAISE EXCEPTION
                    'terminal agency_order_review does not match order';
            END IF;

            IF current_review.status = 'approved' THEN
                PERFORM 1
                FROM agency_customer customer
                WHERE customer.agency_id = current_order.agency_id
                  AND customer.branch_id = current_order.branch_id
                  AND customer.id = current_order.customer_id
                  AND customer.user_id = current_order.user_id
                  AND customer.status = 'active'
                  AND customer.consent_status = 'granted';
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'approved order requires active consented customer';
                END IF;
            END IF;

            PERFORM 1
            FROM agency_membership membership
            JOIN agency
              ON agency.id = membership.agency_id
             AND agency.status = 'active'
            JOIN agency_branch_role_grant grant_row
              ON grant_row.agency_id = membership.agency_id
             AND grant_row.membership_id = membership.id
            JOIN agency_branch branch
              ON branch.agency_id = grant_row.agency_id
             AND branch.id = grant_row.branch_id
             {terminal_branch_predicate}
            WHERE membership.agency_id = current_review.agency_id
              AND membership.user_id = current_review.decided_by_user_id
              AND membership.role = 'approver'
              AND membership.status = 'active'
              AND grant_row.branch_id = current_review.branch_id
              AND grant_row.role = 'approver'
              AND grant_row.status = 'active';
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    '{terminal_approver_error}';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )


def _replace_cancellation_case_guard(
    *,
    inactive_drain_enabled: bool,
) -> None:
    branch_predicate = (
        "IN ('active', 'inactive')"
        if inactive_drain_enabled
        else "= 'active'"
    )
    branch_error = (
        "active or inactive branch"
        if inactive_drain_enabled
        else "active branch"
    )
    update_branch_guard = (
        """
            PERFORM 1
            FROM agency_branch branch
            WHERE branch.agency_id = NEW.agency_id
              AND branch.id = NEW.branch_id
              AND branch.status IN ('active', 'inactive')
            FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'cancellation case update requires active or inactive branch';
            END IF;
        """
        if inactive_drain_enabled
        else ""
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION
            zhixing_guard_agency_order_cancellation_case()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            current_order agency_order%ROWTYPE;
            derived_refund_required boolean;
            derived_supplier_cancel_required boolean;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION
                    'agency_order_cancellation_case cannot be deleted';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.revision <> 1
                    OR NEW.status <> 'approval_pending'
                    OR NEW.external_action_triggered
                THEN
                    RAISE EXCEPTION
                        'new cancellation case must be inert revision one approval_pending';
                END IF;
                PERFORM 1
                FROM agency agency_row
                WHERE agency_row.id = NEW.agency_id
                  AND agency_row.status = 'active'
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'new cancellation case requires active agency';
                END IF;
                PERFORM 1
                FROM agency_branch branch
                WHERE branch.agency_id = NEW.agency_id
                  AND branch.id = NEW.branch_id
                  AND branch.status {branch_predicate}
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'new cancellation case requires {branch_error}';
                END IF;
                SELECT order_row.* INTO current_order
                FROM agency_order order_row
                WHERE order_row.agency_id = NEW.agency_id
                  AND order_row.branch_id = NEW.branch_id
                  AND order_row.customer_id = NEW.customer_id
                  AND order_row.id = NEW.order_id
                  AND order_row.revision = NEW.order_revision_at_request
                  AND order_row.currency = NEW.currency
                  AND order_row.cancelled_at IS NULL
                  AND (
                      (
                          order_row.status IN (
                              'draft',
                              'approved',
                              'processing',
                              'failed',
                              'manual_intervention'
                          )
                          AND order_row.cancellation_requested_at IS NULL
                      )
                      OR (
                          order_row.status IN (
                              'cancellation_pending',
                              'manual_intervention'
                          )
                          AND order_row.cancellation_requested_at IS NOT NULL
                      )
                  )
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'new cancellation case requires eligible unchanged order';
                END IF;
                PERFORM 1
                FROM payment_attempt payment
                WHERE payment.agency_id = NEW.agency_id
                  AND payment.order_id = NEW.order_id
                FOR SHARE;
                PERFORM 1
                FROM fulfillment_record fulfillment
                WHERE fulfillment.agency_id = NEW.agency_id
                  AND fulfillment.order_id = NEW.order_id
                FOR SHARE;
                derived_refund_required :=
                    current_order.payment_status <> 'not_started'
                    OR current_order.external_action_enabled
                    OR EXISTS (
                        SELECT 1
                        FROM payment_attempt payment
                        WHERE payment.agency_id = NEW.agency_id
                          AND payment.order_id = NEW.order_id
                          AND (
                              payment.status IN ('processing', 'succeeded')
                              OR payment.external_action_enabled
                              OR NULLIF(
                                  BTRIM(
                                      COALESCE(
                                          payment.provider_reference,
                                          ''
                                      )
                                  ),
                                  ''
                              ) IS NOT NULL
                          )
                    );
                derived_supplier_cancel_required :=
                    current_order.fulfillment_status <> 'not_started'
                    OR current_order.external_action_enabled
                    OR EXISTS (
                        SELECT 1
                        FROM fulfillment_record fulfillment
                        WHERE fulfillment.agency_id = NEW.agency_id
                          AND fulfillment.order_id = NEW.order_id
                          AND (
                              fulfillment.status <> 'not_started'
                              OR fulfillment.external_action_enabled
                              OR NULLIF(
                                  BTRIM(
                                      COALESCE(
                                          fulfillment.provider_reference,
                                          ''
                                      )
                                  ),
                                  ''
                              ) IS NOT NULL
                          )
                    );
                IF current_order.status IN (
                    'processing',
                    'failed',
                    'cancellation_pending',
                    'manual_intervention'
                )
                    AND NOT derived_refund_required
                    AND NOT derived_supplier_cancel_required
                THEN
                    derived_supplier_cancel_required := true;
                END IF;
                IF NEW.refund_required
                        IS DISTINCT FROM derived_refund_required
                    OR NEW.supplier_cancel_required
                        IS DISTINCT FROM derived_supplier_cancel_required
                THEN
                    RAISE EXCEPTION
                        'new cancellation case required actions must match locked ledgers';
                END IF;
                IF NOT EXISTS (
                    SELECT 1
                    FROM agency_membership membership
                    JOIN agency_branch_role_grant grant_row
                      ON grant_row.agency_id = membership.agency_id
                     AND grant_row.membership_id = membership.id
                    JOIN agency_order order_row
                      ON order_row.agency_id = NEW.agency_id
                     AND order_row.branch_id = NEW.branch_id
                     AND order_row.customer_id = NEW.customer_id
                     AND order_row.id = NEW.order_id
                    WHERE membership.agency_id = NEW.agency_id
                      AND membership.role = 'approver'
                      AND membership.status = 'active'
                      AND membership.user_id
                          <> NEW.requested_by_user_id
                      AND membership.user_id <> order_row.user_id
                      AND grant_row.branch_id = NEW.branch_id
                      AND grant_row.role = 'approver'
                      AND grant_row.status = 'active'
                ) THEN
                    RAISE EXCEPTION
                        'new cancellation case requires eligible branch approver';
                END IF;
                RETURN NEW;
            END IF;
            {update_branch_guard}
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.agency_id IS DISTINCT FROM OLD.agency_id
                OR NEW.branch_id IS DISTINCT FROM OLD.branch_id
                OR NEW.order_id IS DISTINCT FROM OLD.order_id
                OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
                OR NEW.order_revision_at_request
                    IS DISTINCT FROM OLD.order_revision_at_request
                OR NEW.reason_code IS DISTINCT FROM OLD.reason_code
                OR NEW.reason_detail IS DISTINCT FROM OLD.reason_detail
                OR NEW.supplier_cancel_required
                    IS DISTINCT FROM OLD.supplier_cancel_required
                OR NEW.refund_required
                    IS DISTINCT FROM OLD.refund_required
                OR NEW.currency IS DISTINCT FROM OLD.currency
                OR NEW.requested_by_user_id
                    IS DISTINCT FROM OLD.requested_by_user_id
                OR NEW.requested_at IS DISTINCT FROM OLD.requested_at
                OR NEW.external_action_triggered
                    IS DISTINCT FROM OLD.external_action_triggered
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION
                    'agency_order_cancellation_case binding is immutable';
            END IF;
            IF NEW.revision <> OLD.revision + 1 THEN
                RAISE EXCEPTION
                    'agency_order_cancellation_case revision must advance by one';
            END IF;
            IF OLD.status = 'approval_pending'
                AND NEW.status IN (
                    'rejected',
                    'action_pending',
                    'completed'
                )
            THEN
                PERFORM 1
                FROM agency_membership membership
                JOIN agency_branch_role_grant grant_row
                  ON grant_row.agency_id = membership.agency_id
                 AND grant_row.membership_id = membership.id
                JOIN agency agency_row
                  ON agency_row.id = membership.agency_id
                 AND agency_row.status = 'active'
                JOIN agency_branch branch
                  ON branch.agency_id = grant_row.agency_id
                 AND branch.id = grant_row.branch_id
                 AND branch.status {branch_predicate}
                WHERE membership.agency_id = NEW.agency_id
                  AND membership.user_id = NEW.reviewed_by_user_id
                  AND membership.role = 'approver'
                  AND membership.status = 'active'
                  AND grant_row.branch_id = NEW.branch_id
                  AND grant_row.role = 'approver'
                  AND grant_row.status = 'active'
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'cancellation review requires {branch_error} approver';
                END IF;
            END IF;
            IF NEW.reviewed_by_user_id IS NOT NULL
                AND EXISTS (
                    SELECT 1
                    FROM agency_order order_row
                    WHERE order_row.agency_id = NEW.agency_id
                      AND order_row.branch_id = NEW.branch_id
                      AND order_row.customer_id = NEW.customer_id
                      AND order_row.id = NEW.order_id
                      AND order_row.user_id = NEW.reviewed_by_user_id
                )
            THEN
                RAISE EXCEPTION
                    'order customer cannot review cancellation case';
            END IF;
            IF OLD.status IN ('rejected', 'completed') THEN
                RAISE EXCEPTION
                    'terminal agency_order_cancellation_case is immutable';
            END IF;
            IF OLD.review_decision IS NOT NULL
                AND (
                    NEW.review_decision
                        IS DISTINCT FROM OLD.review_decision
                    OR NEW.reviewed_by_user_id
                        IS DISTINCT FROM OLD.reviewed_by_user_id
                    OR NEW.reviewed_at
                        IS DISTINCT FROM OLD.reviewed_at
                    OR NEW.review_note
                        IS DISTINCT FROM OLD.review_note
                    OR NEW.approved_refund_amount
                        IS DISTINCT FROM OLD.approved_refund_amount
                )
            THEN
                RAISE EXCEPTION
                    'cancellation case review decision is immutable';
            END IF;
            IF NOT (
                (
                    OLD.status = 'approval_pending'
                    AND NEW.status IN (
                        'rejected',
                        'action_pending',
                        'completed'
                    )
                )
                OR (
                    OLD.status = 'action_pending'
                    AND NEW.status IN (
                        'reconciliation_pending',
                        'manual_intervention'
                    )
                )
                OR (
                    OLD.status = 'reconciliation_pending'
                    AND NEW.status IN (
                        'completed',
                        'manual_intervention'
                    )
                )
                OR (
                    OLD.status = 'manual_intervention'
                    AND NEW.status = 'action_pending'
                )
            ) THEN
                RAISE EXCEPTION
                    'invalid agency_order_cancellation_case status transition';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )


def _create_cancellation_drain_branch_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_cancellation_drain_branch_write()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM 1
            FROM agency_branch branch
            WHERE branch.agency_id = NEW.agency_id
              AND branch.id = NEW.branch_id
              AND branch.status IN ('active', 'inactive')
            FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'cancellation closeout write requires active or inactive branch';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    for table_name, trigger_name in (
        (
            "agency_order_cancellation_event",
            "trg_cancellation_event_drain_branch_guard",
        ),
        (
            "agency_order_compensation_record",
            "trg_compensation_record_drain_branch_guard",
        ),
        (
            "agency_order_reconciliation_record",
            "trg_reconciliation_record_drain_branch_guard",
        ),
    ):
        op.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE INSERT ON {table_name}
            FOR EACH ROW
            EXECUTE FUNCTION
                zhixing_guard_cancellation_drain_branch_write()
            """
        )


def _create_new_append_only_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_reject_0008_branch_governance_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$;
        """
    )
    for table_name, trigger_name in (
        (
            "agency_customer_branch_transfer",
            "trg_customer_branch_transfer_append_only",
        ),
        (
            "agency_branch_lifecycle_event",
            "trg_agency_branch_lifecycle_event_append_only",
        ),
    ):
        op.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW
            EXECUTE FUNCTION
                zhixing_reject_0008_branch_governance_mutation()
            """
        )


def create_0008_branch_transfer_closure_guards() -> None:
    _create_branch_lifecycle_guard()
    _create_branch_lifecycle_event_guards()
    _create_customer_lifecycle_guard()
    _create_customer_branch_transfer_guards()
    _create_invitation_guard()
    _create_consent_record_guards()
    _create_customer_event_insert_guard()
    _create_assignment_current_branch_guard()
    _create_claim_consent_consistency_guards()
    _replace_order_review_consistency_guard(
        inactive_rejection_enabled=True,
    )
    _replace_cancellation_case_guard(inactive_drain_enabled=True)
    _create_cancellation_drain_branch_guards()
    _create_new_append_only_guards()


_0008_TRIGGERS: tuple[tuple[str, str], ...] = (
    (
        "agency_branch_lifecycle_event",
        "trg_agency_branch_lifecycle_event_consistency",
    ),
    ("agency_branch", "trg_agency_branch_lifecycle_state_consistency"),
    (
        "agency_customer",
        "trg_agency_customer_branch_transfer_consistency",
    ),
    (
        "agency_customer_branch_transfer",
        "trg_customer_branch_transfer_consistency",
    ),
    (
        "agency_branch_lifecycle_event",
        "trg_agency_branch_lifecycle_event_append_only",
    ),
    (
        "agency_customer_branch_transfer",
        "trg_customer_branch_transfer_append_only",
    ),
    (
        "agency_branch_lifecycle_event",
        "trg_agency_branch_lifecycle_event_insert_guard",
    ),
    (
        "agency_customer_branch_transfer",
        "trg_customer_branch_transfer_insert_guard",
    ),
    (
        "agency_customer_advisor_assignment",
        "trg_customer_advisor_assignment_current_branch_consistency",
    ),
    (
        "agency_order_reconciliation_record",
        "trg_reconciliation_record_drain_branch_guard",
    ),
    (
        "agency_order_compensation_record",
        "trg_compensation_record_drain_branch_guard",
    ),
    (
        "agency_order_cancellation_event",
        "trg_cancellation_event_drain_branch_guard",
    ),
    ("agency_customer_event", "trg_agency_customer_event_insert_guard"),
    *_PRE_0008_TRIGGERS,
)

_0008_FUNCTIONS: tuple[str, ...] = (
    "zhixing_reject_0008_branch_governance_mutation",
    "zhixing_guard_cancellation_drain_branch_write",
    "zhixing_validate_agency_customer_claim_consent",
    "zhixing_validate_customer_advisor_assignment_current_branch",
    "zhixing_guard_agency_customer_event_insert",
    "zhixing_reject_agency_customer_consent_record_mutation",
    "zhixing_guard_new_agency_customer_consent_record",
    "zhixing_guard_agency_customer_invitation",
    "zhixing_validate_customer_branch_transfer",
    "zhixing_guard_customer_branch_transfer_insert",
    "zhixing_guard_agency_customer_lifecycle",
    "zhixing_validate_agency_branch_lifecycle_event",
    "zhixing_guard_agency_branch_lifecycle_event_insert",
    "zhixing_guard_agency_branch_lifecycle",
)


def drop_0008_branch_transfer_closure_guards() -> None:
    for table_name, trigger_name in _0008_TRIGGERS:
        op.execute(f"DROP TRIGGER {trigger_name} ON {table_name}")
    for function_name in _0008_FUNCTIONS:
        op.execute(f"DROP FUNCTION {function_name}()")
    _replace_order_review_consistency_guard(
        inactive_rejection_enabled=False,
    )
    _replace_cancellation_case_guard(inactive_drain_enabled=False)


def _restore_0007_branch_lifecycle_guard() -> None:
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


def restore_pre_0008_branch_customer_guards() -> None:
    _restore_0007_branch_lifecycle_guard()
    _restore_0005_customer_guard()
    _restore_0005_invitation_guard()
    _restore_0005_consent_record_guards()
    _restore_0006_consistency_guards()
