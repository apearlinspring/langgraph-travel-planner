"""`20260726_0004` 的 revision-frozen Alembic 操作。

该模块是 0004 revision 的组成部分，不是通用 models helper。发布后不得随应用模型
演进而修改；后续数据库变化必须新增 revision。
"""

from alembic import op


def create_transaction_mutation_guards() -> None:
    """Freeze transaction bindings and the transitions supported by 0004."""

    op.execute(
        """
        CREATE FUNCTION zhixing_guard_agency_quote_mutation()
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
                        'new agency_quote requires active consented customer';
                END IF;
                PERFORM 1
                FROM agency_branch branch
                WHERE branch.agency_id = NEW.agency_id
                  AND branch.id = NEW.branch_id
                  AND branch.status = 'active'
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'new agency_quote requires active branch';
                END IF;
                IF NEW.valid_until <= CURRENT_TIMESTAMP THEN
                    RAISE EXCEPTION
                        'new agency_quote valid_until must be in the future';
                END IF;
                IF NEW.revision <> 1
                    OR NEW.status <> 'draft'
                    OR NEW.issued_at IS NOT NULL
                    OR NEW.accepted_at IS NOT NULL
                THEN
                    RAISE EXCEPTION
                        'new agency_quote must start as revision one draft';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'agency_quote cannot be deleted';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.quote_no IS DISTINCT FROM OLD.quote_no
                OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
                OR NEW.agency_id IS DISTINCT FROM OLD.agency_id
                OR NEW.branch_id IS DISTINCT FROM OLD.branch_id
                OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
                OR NEW.user_id IS DISTINCT FROM OLD.user_id
                OR NEW.conversation_id IS DISTINCT FROM OLD.conversation_id
                OR NEW.product_id IS DISTINCT FROM OLD.product_id
                OR NEW.payload_hash IS DISTINCT FROM OLD.payload_hash
                OR NEW.total_amount IS DISTINCT FROM OLD.total_amount
                OR NEW.currency IS DISTINCT FROM OLD.currency
                OR NEW.snapshot_version IS DISTINCT FROM OLD.snapshot_version
                OR NEW.quote_snapshot::text IS DISTINCT
                    FROM OLD.quote_snapshot::text
                OR NEW.valid_until IS DISTINCT FROM OLD.valid_until
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'agency_quote binding is immutable';
            END IF;
            IF NEW.revision <> OLD.revision + 1 THEN
                RAISE EXCEPTION 'agency_quote revision must advance by one';
            END IF;
            IF OLD.status IN ('expired', 'cancelled') THEN
                RAISE EXCEPTION 'terminal agency_quote is immutable';
            END IF;
            IF OLD.status IN ('draft', 'offered')
                AND NEW.status IN ('offered', 'accepted')
                AND OLD.valid_until <= CURRENT_TIMESTAMP
            THEN
                RAISE EXCEPTION
                    'expired agency_quote cannot be offered or accepted';
            END IF;
            IF NOT (
                (
                    OLD.status = 'draft'
                    AND NEW.status = 'offered'
                    AND NEW.valid_until > CURRENT_TIMESTAMP
                    AND OLD.issued_at IS NULL
                    AND NEW.issued_at IS NOT NULL
                    AND NEW.accepted_at IS NULL
                )
                OR (
                    OLD.status = 'offered'
                    AND NEW.status = 'accepted'
                    AND NEW.valid_until > CURRENT_TIMESTAMP
                    AND NEW.issued_at IS NOT DISTINCT FROM OLD.issued_at
                    AND OLD.accepted_at IS NULL
                    AND NEW.accepted_at IS NOT NULL
                )
                OR (
                    OLD.status = 'offered'
                    AND NEW.status = 'expired'
                    AND NEW.valid_until <= CURRENT_TIMESTAMP
                    AND NEW.issued_at IS NOT DISTINCT FROM OLD.issued_at
                    AND NEW.accepted_at IS NOT DISTINCT FROM OLD.accepted_at
                )
                OR (
                    OLD.status IN ('draft', 'offered', 'accepted')
                    AND NEW.status = 'cancelled'
                    AND NEW.issued_at IS NOT DISTINCT FROM OLD.issued_at
                    AND NEW.accepted_at IS NOT DISTINCT FROM OLD.accepted_at
                    AND (
                        OLD.status <> 'accepted'
                        OR NOT EXISTS (
                            SELECT 1
                            FROM agency_order order_row
                            WHERE order_row.agency_id = OLD.agency_id
                              AND order_row.branch_id = OLD.branch_id
                              AND order_row.customer_id = OLD.customer_id
                              AND order_row.user_id = OLD.user_id
                              AND order_row.quote_id = OLD.id
                        )
                    )
                )
            ) THEN
                RAISE EXCEPTION 'invalid agency_quote status transition';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agency_quote_mutation_guard
        BEFORE INSERT OR UPDATE OR DELETE ON agency_quote
        FOR EACH ROW
        EXECUTE FUNCTION zhixing_guard_agency_quote_mutation()
        """
    )
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
    op.execute(
        """
        CREATE FUNCTION zhixing_validate_agency_order_review_consistency()
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
             AND branch.status = 'active'
            WHERE membership.agency_id = current_review.agency_id
              AND membership.user_id = current_review.decided_by_user_id
              AND membership.role = 'approver'
              AND membership.status = 'active'
              AND grant_row.branch_id = current_review.branch_id
              AND grant_row.role = 'approver'
              AND grant_row.status = 'active';
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'agency_order_review requires active branch approver';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
    for table, trigger in (
        ("agency_order", "trg_agency_order_review_consistency"),
        (
            "agency_order_review",
            "trg_agency_order_review_state_consistency",
        ),
    ):
        op.execute(
            f"""
            CREATE CONSTRAINT TRIGGER {trigger}
            AFTER INSERT OR UPDATE ON {table}
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW
            EXECUTE FUNCTION
                zhixing_validate_agency_order_review_consistency()
            """
        )


def drop_transaction_mutation_guards() -> None:
    for table, trigger in (
        (
            "agency_order_review",
            "trg_agency_order_review_state_consistency",
        ),
        ("agency_order", "trg_agency_order_review_consistency"),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
    op.execute(
        "DROP FUNCTION zhixing_validate_agency_order_review_consistency()"
    )
    for table, trigger, function in (
        (
            "agency_order",
            "trg_agency_order_mutation_guard",
            "zhixing_guard_agency_order_mutation",
        ),
        (
            "agency_quote",
            "trg_agency_quote_mutation_guard",
            "zhixing_guard_agency_quote_mutation",
        ),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
        op.execute(f"DROP FUNCTION {function}()")
