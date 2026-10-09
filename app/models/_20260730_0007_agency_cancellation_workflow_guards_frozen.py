"""`20260730_0007` 的 revision-frozen PostgreSQL 取消域守卫。"""

from alembic import op


def drop_order_mutation_guard() -> None:
    op.execute(
        "DROP TRIGGER trg_agency_order_mutation_guard ON agency_order"
    )
    op.execute("DROP FUNCTION zhixing_guard_agency_order_mutation()")


def _create_0007_order_mutation_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_agency_order_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                PERFORM 1
                FROM agency_customer customer
                WHERE customer.agency_id = NEW.agency_id
                  AND customer.branch_id = NEW.branch_id
                  AND customer.id = NEW.customer_id
                  AND customer.user_id = NEW.user_id
                  AND customer.status = 'active'
                  AND customer.consent_status = 'granted'
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'new agency_order requires active consented customer';
                END IF;
                PERFORM 1
                FROM agency_branch branch
                WHERE branch.agency_id = NEW.agency_id
                  AND branch.id = NEW.branch_id
                  AND branch.status = 'active'
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'new agency_order requires active branch';
                END IF;
                PERFORM 1
                FROM agency_quote quote
                WHERE quote.agency_id = NEW.agency_id
                  AND quote.branch_id = NEW.branch_id
                  AND quote.customer_id = NEW.customer_id
                  AND quote.user_id = NEW.user_id
                  AND quote.id = NEW.quote_id
                  AND quote.status = 'accepted'
                  AND quote.valid_until > CURRENT_TIMESTAMP
                  AND quote.total_amount = NEW.total_amount
                  AND quote.currency = NEW.currency
                  AND quote.quote_snapshot::text = NEW.quote_snapshot::text
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'new agency_order requires accepted valid matching agency_quote';
                END IF;
                IF NEW.revision <> 1
                    OR NEW.status <> 'draft'
                    OR NEW.payment_status <> 'not_started'
                    OR NEW.fulfillment_status <> 'not_started'
                    OR NEW.external_action_enabled
                    OR NEW.confirmed_at IS NOT NULL
                    OR NEW.cancellation_requested_at IS NOT NULL
                    OR NEW.cancelled_at IS NOT NULL
                    OR NEW.completed_at IS NOT NULL
                THEN
                    RAISE EXCEPTION
                        'new agency_order must start as inert revision one draft';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'agency_order cannot be deleted';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.order_no IS DISTINCT FROM OLD.order_no
                OR NEW.agency_id IS DISTINCT FROM OLD.agency_id
                OR NEW.branch_id IS DISTINCT FROM OLD.branch_id
                OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
                OR NEW.quote_id IS DISTINCT FROM OLD.quote_id
                OR NEW.user_id IS DISTINCT FROM OLD.user_id
                OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
                OR NEW.payload_hash IS DISTINCT FROM OLD.payload_hash
                OR NEW.payment_status IS DISTINCT FROM OLD.payment_status
                OR NEW.fulfillment_status IS DISTINCT
                    FROM OLD.fulfillment_status
                OR NEW.total_amount IS DISTINCT FROM OLD.total_amount
                OR NEW.currency IS DISTINCT FROM OLD.currency
                OR NEW.quote_snapshot::text IS DISTINCT
                    FROM OLD.quote_snapshot::text
                OR NEW.external_action_enabled IS DISTINCT
                    FROM OLD.external_action_enabled
                OR NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at
                OR NEW.completed_at IS DISTINCT FROM OLD.completed_at
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'agency_order binding is immutable in 0007';
            END IF;
            IF NEW.revision <> OLD.revision + 1 THEN
                RAISE EXCEPTION 'agency_order revision must advance by one';
            END IF;
            IF OLD.status IN ('review_rejected', 'completed', 'cancelled') THEN
                RAISE EXCEPTION 'terminal agency_order is immutable';
            END IF;
            IF OLD.cancellation_requested_at IS NOT NULL
                AND NEW.cancellation_requested_at IS DISTINCT
                    FROM OLD.cancellation_requested_at
            THEN
                RAISE EXCEPTION
                    'agency_order cancellation request timestamp is immutable';
            END IF;
            IF OLD.cancellation_requested_at IS NULL
                AND NEW.cancellation_requested_at IS NOT NULL
                AND NEW.status NOT IN ('cancellation_pending', 'cancelled')
            THEN
                RAISE EXCEPTION
                    'agency_order cancellation request timestamp requires cancellation state';
            END IF;
            IF NEW.status = 'cancelled' AND NEW.cancelled_at IS NULL THEN
                RAISE EXCEPTION
                    'cancelled agency_order requires cancelled_at';
            END IF;
            IF NEW.status <> 'cancelled' AND NEW.cancelled_at IS NOT NULL THEN
                RAISE EXCEPTION
                    'agency_order cancelled_at only marks true cancellation';
            END IF;
            IF OLD.status = 'draft'
                AND NEW.status = 'pending_review'
                AND EXISTS (
                    SELECT 1
                    FROM agency_order_cancellation_case case_row
                    WHERE case_row.agency_id = NEW.agency_id
                      AND case_row.order_id = NEW.id
                      AND case_row.status IN (
                          'approval_pending',
                          'action_pending',
                          'reconciliation_pending',
                          'manual_intervention'
                      )
                )
            THEN
                RAISE EXCEPTION
                    'agency_order cannot enter review while cancellation case is open';
            END IF;
            IF OLD.status = 'draft'
                AND NEW.status = 'pending_review'
                AND NOT EXISTS (
                    SELECT 1
                    FROM agency_membership membership
                    JOIN agency_branch_role_grant grant_row
                      ON grant_row.agency_id = membership.agency_id
                     AND grant_row.membership_id = membership.id
                    WHERE membership.agency_id = NEW.agency_id
                      AND membership.role = 'approver'
                      AND membership.status = 'active'
                      AND membership.user_id <> NEW.user_id
                      AND grant_row.branch_id = NEW.branch_id
                      AND grant_row.role = 'approver'
                      AND grant_row.status = 'active'
                )
            THEN
                RAISE EXCEPTION
                    'pending agency_order requires active branch approver';
            END IF;
            IF NOT (
                (
                    OLD.status = 'draft'
                    AND NEW.status = 'pending_review'
                    AND NEW.cancellation_requested_at
                        IS NOT DISTINCT FROM OLD.cancellation_requested_at
                    AND NEW.cancelled_at IS NULL
                )
                OR (
                    OLD.status = 'pending_review'
                    AND NEW.status IN ('approved', 'review_rejected')
                    AND NEW.cancellation_requested_at
                        IS NOT DISTINCT FROM OLD.cancellation_requested_at
                    AND NEW.cancelled_at IS NULL
                )
                OR (
                    OLD.status IN ('draft', 'approved')
                    AND NEW.status = 'cancelled'
                    AND NEW.cancellation_requested_at IS NOT NULL
                    AND NEW.cancelled_at IS NOT NULL
                )
                OR (
                    OLD.status IN (
                        'draft',
                        'approved',
                        'processing',
                        'failed',
                        'manual_intervention'
                    )
                    AND NEW.status = 'cancellation_pending'
                    AND NEW.cancellation_requested_at IS NOT NULL
                    AND NEW.cancelled_at IS NULL
                )
                OR (
                    OLD.status = 'cancellation_pending'
                    AND NEW.status = 'manual_intervention'
                    AND NEW.cancellation_requested_at
                        IS NOT DISTINCT FROM OLD.cancellation_requested_at
                    AND NEW.cancelled_at IS NULL
                )
                OR (
                    OLD.status = 'manual_intervention'
                    AND NEW.status = 'cancellation_pending'
                    AND NEW.cancellation_requested_at
                        IS NOT DISTINCT FROM OLD.cancellation_requested_at
                    AND NEW.cancelled_at IS NULL
                )
                OR (
                    OLD.status IN (
                        'cancellation_pending',
                        'manual_intervention'
                    )
                    AND NEW.status = 'cancelled'
                    AND NEW.cancellation_requested_at
                        IS NOT DISTINCT FROM OLD.cancellation_requested_at
                    AND NEW.cancelled_at IS NOT NULL
                )
            ) THEN
                RAISE EXCEPTION 'invalid agency_order status transition';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agency_order_mutation_guard
        BEFORE INSERT OR UPDATE OR DELETE ON agency_order
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_guard_agency_order_mutation()
        """
    )


def _create_cancellation_ledger_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_cancellation_ledger_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            target_agency_id uuid;
            target_order_id uuid;
            locked_order agency_order%ROWTYPE;
        BEGIN
            IF TG_OP IN ('UPDATE', 'DELETE') THEN
                target_agency_id := OLD.agency_id;
                target_order_id := OLD.order_id;
            ELSE
                target_agency_id := NEW.agency_id;
                target_order_id := NEW.order_id;
            END IF;
            IF TG_OP = 'INSERT' THEN
                -- Inserts have no existing ledger row for the service to lock.
                -- Lock the order first so an approval cannot miss a concurrent
                -- new exposure row.
                SELECT order_row.* INTO locked_order
                FROM agency_order order_row
                WHERE order_row.agency_id = target_agency_id
                  AND order_row.id = target_order_id
                FOR UPDATE;
            ELSE
                -- PostgreSQL locks an UPDATE/DELETE target row before firing a
                -- row-level BEFORE trigger.  Taking the order row lock here
                -- would invert the service lock order (order -> ledger) and
                -- create a deadlock.  The service locks every existing ledger
                -- row, so the current row lock already serializes this path.
                SELECT order_row.* INTO locked_order
                FROM agency_order order_row
                WHERE order_row.agency_id = target_agency_id
                  AND order_row.id = target_order_id;
            END IF;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    '% requires matching agency_order', TG_TABLE_NAME;
            END IF;
            IF locked_order.cancellation_requested_at IS NOT NULL
                OR locked_order.status IN (
                    'cancellation_pending',
                    'manual_intervention',
                    'cancelled'
                )
                OR EXISTS (
                    SELECT 1
                    FROM agency_order_cancellation_case case_row
                    WHERE case_row.agency_id = target_agency_id
                      AND case_row.order_id = target_order_id
                      AND case_row.status IN (
                          'approval_pending',
                          'action_pending',
                          'reconciliation_pending',
                          'manual_intervention'
                      )
                )
            THEN
                RAISE EXCEPTION
                    '% is frozen while agency_order cancellation is active',
                    TG_TABLE_NAME;
            END IF;
            IF TG_OP = 'UPDATE'
                AND (
                    NEW.agency_id IS DISTINCT FROM OLD.agency_id
                    OR NEW.order_id IS DISTINCT FROM OLD.order_id
                )
            THEN
                RAISE EXCEPTION
                    '% order binding is immutable', TG_TABLE_NAME;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    for table, trigger in (
        (
            "payment_attempt",
            "trg_payment_attempt_cancellation_freeze",
        ),
        (
            "fulfillment_record",
            "trg_fulfillment_record_cancellation_freeze",
        ),
    ):
        op.execute(
            f"""
            CREATE TRIGGER {trigger}
            BEFORE INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION
                zhixing_guard_cancellation_ledger_mutation()
            """
        )


def _create_case_mutation_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_agency_order_cancellation_case()
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
                  AND branch.status = 'active'
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'new cancellation case requires active branch';
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
                 AND branch.status = 'active'
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
                        'cancellation review requires active branch approver';
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
    op.execute(
        """
        CREATE TRIGGER trg_agency_order_cancellation_case_mutation_guard
        BEFORE INSERT OR UPDATE OR DELETE
        ON agency_order_cancellation_case
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_guard_agency_order_cancellation_case()
        """
    )


def _create_cancellation_approver_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_cancellation_approver_availability()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.role = 'approver'
                AND OLD.status = 'active'
                AND NEW.status = 'revoked'
            THEN
                PERFORM 1
                FROM agency_branch branch
                WHERE branch.agency_id = OLD.agency_id
                  AND branch.id = OLD.branch_id
                FOR UPDATE;
                IF EXISTS (
                    SELECT 1
                    FROM agency_order_review review
                    JOIN agency_order order_row
                      ON order_row.agency_id = review.agency_id
                     AND order_row.branch_id = review.branch_id
                     AND order_row.id = review.order_id
                    WHERE review.agency_id = OLD.agency_id
                      AND review.branch_id = OLD.branch_id
                      AND review.status = 'pending'
                      AND NOT EXISTS (
                        SELECT 1
                        FROM agency_branch_role_grant replacement
                        JOIN agency_membership membership
                          ON membership.agency_id = replacement.agency_id
                         AND membership.id = replacement.membership_id
                        WHERE replacement.agency_id = OLD.agency_id
                          AND replacement.branch_id = OLD.branch_id
                          AND replacement.role = 'approver'
                          AND replacement.status = 'active'
                          AND replacement.id <> OLD.id
                          AND membership.role = 'approver'
                          AND membership.status = 'active'
                          AND membership.user_id
                              <> review.requested_by_user_id
                          AND membership.user_id <> order_row.user_id
                      )
                )
                THEN
                    RAISE EXCEPTION
                        'pending order review requires eligible replacement approver';
                END IF;
                IF EXISTS (
                    SELECT 1
                    FROM agency_order_cancellation_case case_row
                    JOIN agency_order order_row
                      ON order_row.agency_id = case_row.agency_id
                     AND order_row.branch_id = case_row.branch_id
                     AND order_row.id = case_row.order_id
                    WHERE case_row.agency_id = OLD.agency_id
                      AND case_row.branch_id = OLD.branch_id
                      AND case_row.status = 'approval_pending'
                      AND NOT EXISTS (
                        SELECT 1
                        FROM agency_branch_role_grant replacement
                        JOIN agency_membership membership
                          ON membership.agency_id = replacement.agency_id
                         AND membership.id = replacement.membership_id
                        WHERE replacement.agency_id = OLD.agency_id
                          AND replacement.branch_id = OLD.branch_id
                          AND replacement.role = 'approver'
                          AND replacement.status = 'active'
                          AND replacement.id <> OLD.id
                          AND membership.role = 'approver'
                          AND membership.status = 'active'
                          AND membership.user_id
                              <> case_row.requested_by_user_id
                          AND membership.user_id <> order_row.user_id
                    )
                )
                THEN
                    RAISE EXCEPTION
                        'pending cancellation approval requires eligible replacement approver';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER
            trg_agency_branch_role_grant_cancellation_approver_guard
        BEFORE UPDATE OF status ON agency_branch_role_grant
        FOR EACH ROW
        EXECUTE FUNCTION
            zhixing_guard_cancellation_approver_availability()
        """
    )
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_agency_membership_binding()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.agency_id IS DISTINCT FROM OLD.agency_id
                OR NEW.user_id IS DISTINCT FROM OLD.user_id
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'agency_membership binding is immutable';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agency_membership_binding_guard
        BEFORE UPDATE OF id, agency_id, user_id, created_at
        ON agency_membership
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_guard_agency_membership_binding()
        """
    )


def _create_append_only_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_reject_cancellation_append_only_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$;
        """
    )
    for table, trigger in (
        (
            "agency_order_cancellation_event",
            "trg_agency_order_cancellation_event_append_only",
        ),
        (
            "agency_order_compensation_record",
            "trg_agency_order_compensation_record_append_only",
        ),
        (
            "agency_order_reconciliation_record",
            "trg_agency_order_reconciliation_record_append_only",
        ),
    ):
        op.execute(
            f"""
            CREATE TRIGGER {trigger}
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION
                zhixing_reject_cancellation_append_only_mutation()
            """
        )


def _create_record_insert_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_cancellation_event_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM 1
            FROM agency_order_cancellation_case case_row
            WHERE case_row.agency_id = NEW.agency_id
              AND case_row.branch_id = NEW.branch_id
              AND case_row.order_id = NEW.order_id
              AND case_row.customer_id = NEW.customer_id
              AND case_row.id = NEW.cancellation_case_id
              AND NEW.case_revision = case_row.revision
            FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'cancellation event must match current case revision';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agency_order_cancellation_event_insert_guard
        BEFORE INSERT ON agency_order_cancellation_event
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_guard_cancellation_event_insert()
        """
    )
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_compensation_record_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            current_case agency_order_cancellation_case%ROWTYPE;
        BEGIN
            SELECT case_row.* INTO current_case
            FROM agency_order_cancellation_case case_row
            WHERE case_row.agency_id = NEW.agency_id
              AND case_row.branch_id = NEW.branch_id
              AND case_row.order_id = NEW.order_id
              AND case_row.customer_id = NEW.customer_id
              AND case_row.id = NEW.cancellation_case_id
              AND case_row.status IN (
                  'action_pending',
                  'reconciliation_pending',
                  'manual_intervention'
              )
              AND NEW.case_revision <= case_row.revision + 1
            FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'compensation record requires active matching case';
            END IF;
            IF NEW.currency <> current_case.currency THEN
                RAISE EXCEPTION
                    'compensation currency must match cancellation case';
            END IF;
            IF NEW.action_type = 'supplier_cancel'
                AND NOT current_case.supplier_cancel_required
            THEN
                RAISE EXCEPTION
                    'supplier cancellation result was not required';
            END IF;
            IF NEW.action_type = 'refund' THEN
                IF NOT current_case.refund_required
                    OR current_case.approved_refund_amount IS NULL
                    OR NEW.amount
                        <> current_case.approved_refund_amount
                THEN
                    RAISE EXCEPTION
                        'refund result must match approved cancellation amount';
                END IF;
            END IF;
            IF NEW.system_external_action_triggered THEN
                RAISE EXCEPTION
                    'system-triggered compensation action is disabled';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agency_order_compensation_record_insert_guard
        BEFORE INSERT ON agency_order_compensation_record
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_guard_compensation_record_insert()
        """
    )
    op.execute(
        """
        CREATE FUNCTION zhixing_guard_reconciliation_record_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            current_case agency_order_cancellation_case%ROWTYPE;
            current_compensation agency_order_compensation_record%ROWTYPE;
        BEGIN
            SELECT case_row.* INTO current_case
            FROM agency_order_cancellation_case case_row
            WHERE case_row.agency_id = NEW.agency_id
              AND case_row.branch_id = NEW.branch_id
              AND case_row.order_id = NEW.order_id
              AND case_row.customer_id = NEW.customer_id
              AND case_row.id = NEW.cancellation_case_id
              AND case_row.status IN (
                  'reconciliation_pending',
                  'manual_intervention',
                  'completed'
              )
              AND NEW.case_revision <= case_row.revision + 1
            FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'reconciliation record requires matching active case';
            END IF;
            SELECT record.* INTO current_compensation
            FROM agency_order_compensation_record record
            WHERE record.agency_id = NEW.agency_id
              AND record.branch_id = NEW.branch_id
              AND record.order_id = NEW.order_id
              AND record.customer_id = NEW.customer_id
              AND record.cancellation_case_id = NEW.cancellation_case_id
              AND record.id = NEW.compensation_record_id
            FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'reconciliation record requires matching compensation';
            END IF;
            IF NEW.reconciled_by_user_id
                    = current_compensation.recorded_by_user_id
            THEN
                RAISE EXCEPTION
                    'compensation recorder cannot reconcile own result';
            END IF;
            IF current_compensation.outcome <> 'succeeded' THEN
                RAISE EXCEPTION
                    'only successful compensation can be reconciled';
            END IF;
            IF current_compensation.action_type = 'supplier_cancel'
                AND (
                    NEW.observed_amount IS NOT NULL
                    OR NEW.currency IS NOT NULL
                )
            THEN
                RAISE EXCEPTION
                    'supplier cancellation reconciliation cannot include amount';
            END IF;
            IF NEW.outcome = 'matched'
                AND current_compensation.action_type = 'refund'
                AND (
                    NEW.observed_amount IS DISTINCT
                        FROM current_compensation.amount
                    OR NEW.currency IS DISTINCT
                        FROM current_compensation.currency
                )
            THEN
                RAISE EXCEPTION
                    'matched reconciliation amount must equal compensation';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agency_order_reconciliation_record_insert_guard
        BEFORE INSERT ON agency_order_reconciliation_record
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_guard_reconciliation_record_insert()
        """
    )


def _create_deferred_consistency_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION zhixing_validate_cancellation_case_consistency()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            current_case agency_order_cancellation_case%ROWTYPE;
            current_order agency_order%ROWTYPE;
        BEGIN
            SELECT * INTO current_case
            FROM agency_order_cancellation_case
            WHERE id = NEW.id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'cancellation case cannot disappear';
            END IF;
            SELECT * INTO current_order
            FROM agency_order
            WHERE agency_id = current_case.agency_id
              AND branch_id = current_case.branch_id
              AND customer_id = current_case.customer_id
              AND id = current_case.order_id;
            IF NOT FOUND
                OR current_order.currency <> current_case.currency
            THEN
                RAISE EXCEPTION
                    'cancellation case binding does not match order';
            END IF;
            IF current_case.approved_refund_amount
                    > current_order.total_amount
            THEN
                RAISE EXCEPTION
                    'approved refund exceeds agency_order total';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM agency_order_cancellation_event event_row
                WHERE event_row.agency_id = current_case.agency_id
                  AND event_row.branch_id = current_case.branch_id
                  AND event_row.order_id = current_case.order_id
                  AND event_row.customer_id = current_case.customer_id
                  AND event_row.cancellation_case_id = current_case.id
                  AND event_row.case_revision = current_case.revision
            ) THEN
                RAISE EXCEPTION
                    'cancellation case revision requires audit event';
            END IF;
            IF current_case.status = 'approval_pending' THEN
                IF current_order.revision
                        <> current_case.order_revision_at_request
                    OR current_order.status = 'cancelled'
                THEN
                    RAISE EXCEPTION
                        'unapproved cancellation case cannot mutate order';
                END IF;
                RETURN NULL;
            END IF;
            IF current_case.status = 'rejected' THEN
                RETURN NULL;
            END IF;
            IF current_case.status IN (
                'action_pending',
                'reconciliation_pending'
            ) THEN
                IF current_order.status <> 'cancellation_pending'
                    OR current_order.cancellation_requested_at IS NULL
                    OR current_order.cancelled_at IS NOT NULL
                THEN
                    RAISE EXCEPTION
                        'active cancellation case requires pending order';
                END IF;
            ELSIF current_case.status = 'manual_intervention' THEN
                IF current_order.status <> 'manual_intervention'
                    OR current_order.cancellation_requested_at IS NULL
                    OR current_order.cancelled_at IS NOT NULL
                THEN
                    RAISE EXCEPTION
                        'manual cancellation case requires manual order';
                END IF;
            ELSIF current_case.status = 'completed' THEN
                IF current_order.status <> 'cancelled'
                    OR current_order.cancelled_at IS NULL
                    OR current_order.cancellation_requested_at IS NULL
                THEN
                    RAISE EXCEPTION
                        'completed cancellation case requires cancelled order';
                END IF;
            END IF;
            IF current_case.status IN (
                'reconciliation_pending',
                'completed'
            ) THEN
                IF current_case.supplier_cancel_required
                    AND NOT EXISTS (
                        SELECT 1
                        FROM agency_order_compensation_record record
                        WHERE record.id = (
                            SELECT latest.id
                            FROM agency_order_compensation_record latest
                            WHERE latest.cancellation_case_id
                                    = current_case.id
                              AND latest.action_type = 'supplier_cancel'
                            ORDER BY latest.record_sequence DESC
                            LIMIT 1
                        )
                          AND record.outcome = 'succeeded'
                    )
                THEN
                    RAISE EXCEPTION
                        'supplier cancellation result is incomplete';
                END IF;
                IF current_case.refund_required
                    AND NOT EXISTS (
                        SELECT 1
                        FROM agency_order_compensation_record record
                        WHERE record.id = (
                            SELECT latest.id
                            FROM agency_order_compensation_record latest
                            WHERE latest.cancellation_case_id
                                    = current_case.id
                              AND latest.action_type = 'refund'
                            ORDER BY latest.record_sequence DESC
                            LIMIT 1
                        )
                          AND record.outcome = 'succeeded'
                          AND record.amount
                              = current_case.approved_refund_amount
                          AND record.currency = current_case.currency
                    )
                THEN
                    RAISE EXCEPTION
                        'approved refund result is incomplete';
                END IF;
            END IF;
            IF current_case.status = 'completed' THEN
                IF current_case.supplier_cancel_required
                    AND NOT EXISTS (
                        SELECT 1
                        FROM agency_order_compensation_record record
                        JOIN agency_order_reconciliation_record recon
                          ON recon.compensation_record_id = record.id
                         AND recon.outcome = 'matched'
                        WHERE record.id = (
                            SELECT latest.id
                            FROM agency_order_compensation_record latest
                            WHERE latest.cancellation_case_id
                                    = current_case.id
                              AND latest.action_type = 'supplier_cancel'
                            ORDER BY latest.record_sequence DESC
                            LIMIT 1
                        )
                          AND record.outcome = 'succeeded'
                    )
                THEN
                    RAISE EXCEPTION
                        'completed cancellation case requires matched supplier reconciliation';
                END IF;
                IF current_case.refund_required
                    AND NOT EXISTS (
                        SELECT 1
                        FROM agency_order_compensation_record record
                        JOIN agency_order_reconciliation_record recon
                          ON recon.compensation_record_id = record.id
                         AND recon.outcome = 'matched'
                        WHERE record.id = (
                            SELECT latest.id
                            FROM agency_order_compensation_record latest
                            WHERE latest.cancellation_case_id
                                    = current_case.id
                              AND latest.action_type = 'refund'
                            ORDER BY latest.record_sequence DESC
                            LIMIT 1
                        )
                          AND record.outcome = 'succeeded'
                    )
                THEN
                    RAISE EXCEPTION
                        'completed cancellation case requires matched refund reconciliation';
                END IF;
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER
            trg_agency_order_cancellation_case_consistency
        AFTER INSERT OR UPDATE ON agency_order_cancellation_case
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_validate_cancellation_case_consistency()
        """
    )
    op.execute(
        """
        CREATE FUNCTION zhixing_validate_order_cancellation_consistency()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            current_case agency_order_cancellation_case%ROWTYPE;
            customer_is_active boolean;
        BEGIN
            IF NEW.status = 'pending_review'
                AND EXISTS (
                    SELECT 1
                    FROM agency_order_cancellation_case case_row
                    WHERE case_row.agency_id = NEW.agency_id
                      AND case_row.order_id = NEW.id
                      AND case_row.status IN (
                          'approval_pending',
                          'action_pending',
                          'reconciliation_pending',
                          'manual_intervention'
                      )
                )
            THEN
                RAISE EXCEPTION
                    'pending agency_order cannot retain open cancellation case';
            END IF;
            IF NEW.status NOT IN (
                'cancellation_pending',
                'manual_intervention',
                'cancelled'
            )
                OR (
                    NEW.cancellation_requested_at IS NULL
                    AND NEW.status = 'cancelled'
                )
            THEN
                RETURN NULL;
            END IF;
            SELECT EXISTS (
                SELECT 1
                FROM agency_customer customer
                WHERE customer.agency_id = NEW.agency_id
                  AND customer.branch_id = NEW.branch_id
                  AND customer.id = NEW.customer_id
                  AND customer.status = 'active'
            ) INTO customer_is_active;
            SELECT case_row.* INTO current_case
            FROM agency_order_cancellation_case case_row
            WHERE case_row.agency_id = NEW.agency_id
              AND case_row.branch_id = NEW.branch_id
              AND case_row.order_id = NEW.id
              AND case_row.customer_id = NEW.customer_id
              AND case_row.status <> 'rejected'
            ORDER BY case_row.created_at DESC, case_row.id DESC
            LIMIT 1;
            IF NOT FOUND THEN
                IF customer_is_active THEN
                    RAISE EXCEPTION
                        'active customer cancellation state requires case';
                END IF;
                RETURN NULL;
            END IF;
            IF (
                    current_case.status IN (
                        'action_pending',
                        'reconciliation_pending'
                    )
                    AND NEW.status <> 'cancellation_pending'
                )
                OR (
                    current_case.status = 'manual_intervention'
                    AND NEW.status <> 'manual_intervention'
                )
                OR (
                    current_case.status = 'completed'
                    AND NEW.status <> 'cancelled'
                )
            THEN
                RAISE EXCEPTION
                    'agency_order cancellation state does not match case';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER
            trg_agency_order_cancellation_consistency
        AFTER INSERT OR UPDATE ON agency_order
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_validate_order_cancellation_consistency()
        """
    )
    op.execute(
        """
        CREATE FUNCTION zhixing_validate_compensation_case_consistency()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            current_case agency_order_cancellation_case%ROWTYPE;
        BEGIN
            SELECT * INTO current_case
            FROM agency_order_cancellation_case
            WHERE id = NEW.cancellation_case_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'compensation record requires cancellation case';
            END IF;
            IF NEW.case_revision <> current_case.revision THEN
                RAISE EXCEPTION
                    'compensation record revision must match current case';
            END IF;
            IF NEW.outcome IN ('failed', 'unknown')
                AND current_case.status <> 'manual_intervention'
            THEN
                RAISE EXCEPTION
                    'uncertain compensation requires manual intervention';
            END IF;
            IF NEW.outcome = 'succeeded'
                AND current_case.status NOT IN (
                    'action_pending',
                    'reconciliation_pending',
                    'manual_intervention',
                    'completed'
                )
            THEN
                RAISE EXCEPTION
                    'successful compensation has invalid case state';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER
            trg_agency_order_compensation_case_consistency
        AFTER INSERT ON agency_order_compensation_record
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION
            zhixing_validate_compensation_case_consistency()
        """
    )
    op.execute(
        """
        CREATE FUNCTION zhixing_validate_reconciliation_case_consistency()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            current_case agency_order_cancellation_case%ROWTYPE;
        BEGIN
            SELECT * INTO current_case
            FROM agency_order_cancellation_case
            WHERE id = NEW.cancellation_case_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'reconciliation record requires cancellation case';
            END IF;
            IF NEW.case_revision <> current_case.revision THEN
                RAISE EXCEPTION
                    'reconciliation record revision must match current case';
            END IF;
            IF NEW.outcome IN ('mismatched', 'unverifiable')
                AND current_case.status <> 'manual_intervention'
            THEN
                RAISE EXCEPTION
                    'unmatched reconciliation requires manual intervention';
            END IF;
            IF NEW.outcome = 'matched'
                AND current_case.status NOT IN (
                    'reconciliation_pending',
                    'manual_intervention',
                    'completed'
                )
            THEN
                RAISE EXCEPTION
                    'matched reconciliation has invalid case state';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER
            trg_agency_order_reconciliation_case_consistency
        AFTER INSERT ON agency_order_reconciliation_record
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION
            zhixing_validate_reconciliation_case_consistency()
        """
    )


def create_0007_cancellation_guards() -> None:
    _create_0007_order_mutation_guard()
    _create_cancellation_ledger_guards()
    _create_case_mutation_guard()
    _create_cancellation_approver_guard()
    _create_append_only_guards()
    _create_record_insert_guards()
    _create_deferred_consistency_guards()


def drop_0007_cancellation_guards() -> None:
    op.execute(
        "DROP TRIGGER trg_agency_membership_binding_guard "
        "ON agency_membership"
    )
    op.execute(
        "DROP FUNCTION zhixing_guard_agency_membership_binding()"
    )
    op.execute(
        "DROP TRIGGER "
        "trg_agency_branch_role_grant_cancellation_approver_guard "
        "ON agency_branch_role_grant"
    )
    op.execute(
        "DROP FUNCTION zhixing_guard_cancellation_approver_availability()"
    )
    for table, trigger in (
        (
            "agency_order_reconciliation_record",
            "trg_agency_order_reconciliation_case_consistency",
        ),
        (
            "agency_order_compensation_record",
            "trg_agency_order_compensation_case_consistency",
        ),
        (
            "agency_order",
            "trg_agency_order_cancellation_consistency",
        ),
        (
            "agency_order_cancellation_case",
            "trg_agency_order_cancellation_case_consistency",
        ),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
    for function in (
        "zhixing_validate_reconciliation_case_consistency",
        "zhixing_validate_compensation_case_consistency",
        "zhixing_validate_order_cancellation_consistency",
        "zhixing_validate_cancellation_case_consistency",
    ):
        op.execute(f"DROP FUNCTION {function}()")
    for table, trigger, function in (
        (
            "agency_order_reconciliation_record",
            "trg_agency_order_reconciliation_record_insert_guard",
            "zhixing_guard_reconciliation_record_insert",
        ),
        (
            "agency_order_compensation_record",
            "trg_agency_order_compensation_record_insert_guard",
            "zhixing_guard_compensation_record_insert",
        ),
        (
            "agency_order_cancellation_event",
            "trg_agency_order_cancellation_event_insert_guard",
            "zhixing_guard_cancellation_event_insert",
        ),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
        op.execute(f"DROP FUNCTION {function}()")
    for table, trigger in (
        (
            "agency_order_reconciliation_record",
            "trg_agency_order_reconciliation_record_append_only",
        ),
        (
            "agency_order_compensation_record",
            "trg_agency_order_compensation_record_append_only",
        ),
        (
            "agency_order_cancellation_event",
            "trg_agency_order_cancellation_event_append_only",
        ),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
    op.execute(
        "DROP FUNCTION zhixing_reject_cancellation_append_only_mutation()"
    )
    op.execute(
        "DROP TRIGGER "
        "trg_agency_order_cancellation_case_mutation_guard "
        "ON agency_order_cancellation_case"
    )
    op.execute(
        "DROP FUNCTION zhixing_guard_agency_order_cancellation_case()"
    )
    for table, trigger in (
        (
            "fulfillment_record",
            "trg_fulfillment_record_cancellation_freeze",
        ),
        (
            "payment_attempt",
            "trg_payment_attempt_cancellation_freeze",
        ),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
    op.execute("DROP FUNCTION zhixing_guard_cancellation_ledger_mutation()")
    drop_order_mutation_guard()


def restore_0004_order_mutation_guard() -> None:
    """恢复 0004/0006 时存在的原订单守卫，不改写历史 frozen helper。"""

    op.execute(
        """
        CREATE FUNCTION zhixing_guard_agency_order_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                PERFORM 1
                FROM agency_customer customer
                WHERE customer.agency_id = NEW.agency_id
                  AND customer.branch_id = NEW.branch_id
                  AND customer.id = NEW.customer_id
                  AND customer.user_id = NEW.user_id
                  AND customer.status = 'active'
                  AND customer.consent_status = 'granted'
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'new agency_order requires active consented customer';
                END IF;
                PERFORM 1
                FROM agency_branch branch
                WHERE branch.agency_id = NEW.agency_id
                  AND branch.id = NEW.branch_id
                  AND branch.status = 'active'
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'new agency_order requires active branch';
                END IF;
                PERFORM 1
                FROM agency_quote quote
                WHERE quote.agency_id = NEW.agency_id
                  AND quote.branch_id = NEW.branch_id
                  AND quote.customer_id = NEW.customer_id
                  AND quote.user_id = NEW.user_id
                  AND quote.id = NEW.quote_id
                  AND quote.status = 'accepted'
                  AND quote.valid_until > CURRENT_TIMESTAMP
                  AND quote.total_amount = NEW.total_amount
                  AND quote.currency = NEW.currency
                  AND quote.quote_snapshot::text = NEW.quote_snapshot::text
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'new agency_order requires accepted valid matching agency_quote';
                END IF;
                IF NEW.revision <> 1
                    OR NEW.status <> 'draft'
                    OR NEW.payment_status <> 'not_started'
                    OR NEW.fulfillment_status <> 'not_started'
                    OR NEW.external_action_enabled
                    OR NEW.confirmed_at IS NOT NULL
                    OR NEW.cancelled_at IS NOT NULL
                    OR NEW.completed_at IS NOT NULL
                THEN
                    RAISE EXCEPTION
                        'new agency_order must start as inert revision one draft';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'agency_order cannot be deleted';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.order_no IS DISTINCT FROM OLD.order_no
                OR NEW.agency_id IS DISTINCT FROM OLD.agency_id
                OR NEW.branch_id IS DISTINCT FROM OLD.branch_id
                OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
                OR NEW.quote_id IS DISTINCT FROM OLD.quote_id
                OR NEW.user_id IS DISTINCT FROM OLD.user_id
                OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
                OR NEW.payload_hash IS DISTINCT FROM OLD.payload_hash
                OR NEW.payment_status IS DISTINCT FROM OLD.payment_status
                OR NEW.fulfillment_status IS DISTINCT
                    FROM OLD.fulfillment_status
                OR NEW.total_amount IS DISTINCT FROM OLD.total_amount
                OR NEW.currency IS DISTINCT FROM OLD.currency
                OR NEW.quote_snapshot::text IS DISTINCT
                    FROM OLD.quote_snapshot::text
                OR NEW.external_action_enabled IS DISTINCT
                    FROM OLD.external_action_enabled
                OR NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at
                OR NEW.completed_at IS DISTINCT FROM OLD.completed_at
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'agency_order binding is immutable in 0004';
            END IF;
            IF NEW.revision <> OLD.revision + 1 THEN
                RAISE EXCEPTION 'agency_order revision must advance by one';
            END IF;
            IF OLD.status IN ('review_rejected', 'completed', 'cancelled') THEN
                RAISE EXCEPTION 'terminal agency_order is immutable';
            END IF;
            IF OLD.status = 'draft'
                AND NEW.status = 'pending_review'
                AND NOT EXISTS (
                    SELECT 1
                    FROM agency_membership membership
                    JOIN agency_branch_role_grant grant_row
                      ON grant_row.agency_id = membership.agency_id
                     AND grant_row.membership_id = membership.id
                    WHERE membership.agency_id = NEW.agency_id
                      AND membership.role = 'approver'
                      AND membership.status = 'active'
                      AND grant_row.branch_id = NEW.branch_id
                      AND grant_row.role = 'approver'
                      AND grant_row.status = 'active'
                )
            THEN
                RAISE EXCEPTION
                    'pending agency_order requires active branch approver';
            END IF;
            IF NOT (
                (
                    OLD.status = 'draft'
                    AND NEW.status = 'pending_review'
                    AND NEW.cancelled_at IS NOT DISTINCT
                        FROM OLD.cancelled_at
                )
                OR (
                    OLD.status = 'pending_review'
                    AND NEW.status IN ('approved', 'review_rejected')
                    AND NEW.cancelled_at IS NOT DISTINCT
                        FROM OLD.cancelled_at
                )
                OR (
                    OLD.status IN ('draft', 'approved')
                    AND NEW.status = 'cancelled'
                    AND NEW.cancelled_at IS NOT NULL
                )
                OR (
                    OLD.status IN ('draft', 'approved', 'processing', 'failed')
                    AND NEW.status = 'cancellation_pending'
                    AND NEW.cancelled_at IS NOT NULL
                )
            ) THEN
                RAISE EXCEPTION 'invalid agency_order status transition';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agency_order_mutation_guard
        BEFORE INSERT OR UPDATE OR DELETE ON agency_order
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_guard_agency_order_mutation()
        """
    )
