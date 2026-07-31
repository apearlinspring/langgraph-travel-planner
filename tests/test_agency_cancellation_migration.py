from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    UniqueConstraint,
)

import app.models._20260730_0007_agency_cancellation_workflow_frozen as frozen
import app.models._20260730_0007_agency_cancellation_workflow_guards_frozen as guards
from app.models import (
    AgencyOrderCancellationCase,
    AgencyOrderCancellationEvent,
    AgencyOrderCompensationRecord,
    AgencyOrderReconciliationRecord,
)


ROOT = Path(__file__).resolve().parents[1]
REVISION_PATH = (
    ROOT / "alembic/versions/20260730_0007_agency_cancellation_workflow.py"
)
NEW_MODELS = (
    AgencyOrderCancellationCase,
    AgencyOrderCancellationEvent,
    AgencyOrderCompensationRecord,
    AgencyOrderReconciliationRecord,
)


def _load_revision() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "agency_cancellation_workflow_revision_test",
        REVISION_PATH,
    )
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return revision


def _constraint_columns(constraint: object) -> tuple[str, ...]:
    if isinstance(constraint, ForeignKeyConstraint):
        return tuple(constraint.column_keys)
    pending = getattr(constraint, "_pending_colargs", ())
    if pending:
        return tuple(
            item if isinstance(item, str) else item.name
            for item in pending
        )
    return tuple(column.name for column in constraint.columns)


class _CancellationMigrationRecorder:
    def __init__(self) -> None:
        self.created_tables: dict[str, tuple[object, ...]] = {}
        self.added_columns: dict[str, dict[str, Column[Any]]] = {}
        self.created_constraints: dict[
            str,
            tuple[str, str, tuple[str, ...]],
        ] = {}
        self.created_indexes: dict[
            tuple[str, str],
            tuple[tuple[str, ...], dict[str, Any]],
        ] = {}
        self.dropped_indexes: list[tuple[str, str]] = []
        self.dropped_tables: list[str] = []
        self.dropped_constraints: list[tuple[str, str, str | None]] = []
        self.dropped_columns: list[tuple[str, str]] = []
        self.executed_sql: list[str] = []
        self.operations: list[tuple[str, str]] = []

    def execute(self, statement: object) -> None:
        sql = str(statement)
        self.executed_sql.append(sql)
        self.operations.append(("execute", sql))

    def add_column(self, table_name: str, column: Column[Any]) -> None:
        self.added_columns.setdefault(table_name, {})[column.name] = column
        self.operations.append(("add_column", f"{table_name}.{column.name}"))

    def create_unique_constraint(
        self,
        name: str,
        table_name: str,
        columns: list[str],
    ) -> None:
        self.created_constraints[name] = (
            "unique",
            table_name,
            tuple(columns),
        )
        self.operations.append(("create_constraint", name))

    def create_table(
        self,
        table_name: str,
        *elements: object,
        **_kwargs: object,
    ) -> None:
        self.created_tables[table_name] = elements
        self.operations.append(("create_table", table_name))

    def create_index(
        self,
        name: str,
        table_name: str,
        columns: list[str],
        **kwargs: Any,
    ) -> None:
        self.created_indexes[(name, table_name)] = (
            tuple(columns),
            kwargs,
        )
        self.operations.append(("create_index", name))

    def drop_index(self, name: str, *, table_name: str) -> None:
        self.dropped_indexes.append((name, table_name))
        self.operations.append(("drop_index", name))

    def drop_table(self, table_name: str) -> None:
        self.dropped_tables.append(table_name)
        self.operations.append(("drop_table", table_name))

    def drop_constraint(
        self,
        name: str,
        table_name: str,
        *,
        type_: str | None = None,
    ) -> None:
        self.dropped_constraints.append((name, table_name, type_))
        self.operations.append(("drop_constraint", name))

    def drop_column(self, table_name: str, column_name: str) -> None:
        self.dropped_columns.append((table_name, column_name))
        self.operations.append(("drop_column", f"{table_name}.{column_name}"))


class _RejectingDowngradeRecorder(_CancellationMigrationRecorder):
    def execute(self, statement: object) -> None:
        sql = str(statement)
        super().execute(sql)
        if "cannot downgrade 0007 after cancellation workflow data exists" in sql:
            raise RuntimeError("simulated PostgreSQL business data rejection")


def _patch_ops(
    monkeypatch: pytest.MonkeyPatch,
    recorder: _CancellationMigrationRecorder,
) -> None:
    monkeypatch.setattr(frozen, "op", recorder)
    monkeypatch.setattr(guards, "op", recorder)


def _record_upgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ModuleType, _CancellationMigrationRecorder]:
    recorder = _CancellationMigrationRecorder()
    _patch_ops(monkeypatch, recorder)
    revision = _load_revision()
    revision.upgrade()
    return revision, recorder


def test_0007_revision_uses_frozen_helper_contract():
    revision = _load_revision()

    assert revision.revision == "20260730_0007"
    assert revision.down_revision == "20260730_0006"
    assert revision._upgrade.__module__ == (
        "app.models._20260730_0007_agency_cancellation_workflow_frozen"
    )
    assert revision._downgrade.__module__ == (
        "app.models._20260730_0007_agency_cancellation_workflow_frozen"
    )
    assert "revision-frozen" in (frozen.__doc__ or "")
    assert "revision-frozen" in (guards.__doc__ or "")
    assert "后续数据库" in (frozen.__doc__ or "")


def test_0007_upgrade_adds_order_delta_and_four_bound_tables(
    monkeypatch: pytest.MonkeyPatch,
):
    _revision, recorder = _record_upgrade(monkeypatch)

    assert set(recorder.added_columns) == {"agency_order"}
    request_column = recorder.added_columns["agency_order"][
        "cancellation_requested_at"
    ]
    assert request_column.nullable is True
    assert recorder.created_constraints[
        "uq_agency_order_branch_customer_id"
    ] == (
        "unique",
        "agency_order",
        ("agency_id", "branch_id", "customer_id", "id"),
    )
    drop_guard_at = next(
        index
        for index, operation in enumerate(recorder.operations)
        if operation[0] == "execute"
        and "DROP TRIGGER trg_agency_order_mutation_guard"
        in operation[1]
    )
    backfill_at = next(
        index
        for index, operation in enumerate(recorder.operations)
        if operation[0] == "execute"
        and "UPDATE agency_order" in operation[1]
    )
    parent_constraint_at = recorder.operations.index(
        (
            "create_constraint",
            "uq_agency_order_branch_customer_id",
        )
    )
    create_guard_at = next(
        index
        for index, operation in enumerate(recorder.operations)
        if operation[0] == "execute"
        and "CREATE TRIGGER trg_agency_order_mutation_guard"
        in operation[1]
    )
    assert parent_constraint_at < backfill_at
    assert drop_guard_at < backfill_at < create_guard_at
    assert list(recorder.created_tables) == [
        "agency_order_cancellation_case",
        "agency_order_cancellation_event",
        "agency_order_compensation_record",
        "agency_order_reconciliation_record",
    ]

    allowed_extra_constraints = {
        "agency_order_cancellation_case": {
            "fk_agency_order_cancellation_case_requester",
            "fk_agency_order_cancellation_case_reviewer",
        },
        "agency_order_cancellation_event": {
            "fk_agency_order_cancellation_event_actor",
        },
        "agency_order_compensation_record": {
            "fk_agency_order_compensation_record_recorder",
        },
        "agency_order_reconciliation_record": {
            "fk_agency_order_reconciliation_record_reconciler",
        },
    }
    for model in NEW_MODELS:
        table_name = model.__tablename__
        elements = recorder.created_tables[table_name]
        migrated_columns = {
            element.name: element
            for element in elements
            if isinstance(element, Column)
        }
        assert set(migrated_columns) == {
            column.name for column in model.__table__.columns
        }
        for column in model.__table__.columns:
            assert migrated_columns[column.name].nullable == column.nullable

        migrated_constraints = {
            element.name: element
            for element in elements
            if isinstance(
                element,
                (
                    CheckConstraint,
                    ForeignKeyConstraint,
                    UniqueConstraint,
                ),
            )
            and element.name
        }
        model_constraints = {
            constraint.name: constraint
            for constraint in model.__table__.constraints
            if isinstance(
                constraint,
                (
                    CheckConstraint,
                    ForeignKeyConstraint,
                    UniqueConstraint,
                ),
            )
            and constraint.name
        }
        assert set(migrated_constraints) == (
            set(model_constraints)
            | allowed_extra_constraints[table_name]
        )
        for name, model_constraint in model_constraints.items():
            assert _constraint_columns(migrated_constraints[name]) == (
                _constraint_columns(model_constraint)
            )


def test_0007_indexes_match_models_and_open_case_is_partial_unique(
    monkeypatch: pytest.MonkeyPatch,
):
    _revision, recorder = _record_upgrade(monkeypatch)

    for model in NEW_MODELS:
        migrated = {
            name: details
            for (name, table_name), details
            in recorder.created_indexes.items()
            if table_name == model.__tablename__
        }
        assert set(migrated) == {
            index.name for index in model.__table__.indexes
        }
        for index in model.__table__.indexes:
            columns, kwargs = migrated[index.name]
            assert columns == tuple(column.name for column in index.columns)
            assert bool(kwargs.get("unique", False)) is bool(index.unique)
            expected_where = index.dialect_options["postgresql"].get("where")
            actual_where = kwargs.get("postgresql_where")
            assert str(actual_where) == str(expected_where)

    columns, kwargs = recorder.created_indexes[
        (
            "uq_agency_order_cancellation_case_open",
            "agency_order_cancellation_case",
        )
    ]
    assert columns == ("agency_id", "order_id")
    assert kwargs["unique"] is True
    where = str(kwargs["postgresql_where"])
    assert "approval_pending" in where
    assert "action_pending" in where
    assert "reconciliation_pending" in where
    assert "manual_intervention" in where
    assert "completed" not in where
    assert "rejected" not in where


def test_0007_table_ddl_has_four_eyes_external_false_and_composite_bindings(
    monkeypatch: pytest.MonkeyPatch,
):
    _revision, recorder = _record_upgrade(monkeypatch)

    case_constraints = {
        element.name: element
        for element in recorder.created_tables[
            "agency_order_cancellation_case"
        ]
        if isinstance(
            element,
            (CheckConstraint, ForeignKeyConstraint, UniqueConstraint),
        )
        and element.name
    }
    assert "reviewed_by_user_id <> requested_by_user_id" in str(
        case_constraints[
            "ck_agency_order_cancellation_case_four_eyes"
        ].sqltext
    )
    assert "NOT external_action_triggered" in str(
        case_constraints[
            "ck_agency_order_cancellation_case_external_action"
        ].sqltext
    )
    review_shape_sql = str(
        case_constraints[
            "ck_agency_order_cancellation_case_review_shape"
        ].sqltext
    )
    assert review_shape_sql.count("review_decision IS NOT NULL") == 3
    case_order_fk = case_constraints[
        "fk_agency_order_cancellation_case_order"
    ]
    assert tuple(case_order_fk.column_keys) == (
        "agency_id",
        "branch_id",
        "customer_id",
        "order_id",
    )

    compensation_constraints = {
        element.name: element
        for element in recorder.created_tables[
            "agency_order_compensation_record"
        ]
        if isinstance(
            element,
            (CheckConstraint, ForeignKeyConstraint, UniqueConstraint),
        )
        and element.name
    }
    assert "NOT system_external_action_triggered" in str(
        compensation_constraints[
            "ck_agency_order_compensation_record_external_action"
        ].sqltext
    )
    assert tuple(
        compensation_constraints[
            "fk_agency_order_compensation_record_case"
        ].column_keys
    ) == (
        "agency_id",
        "branch_id",
        "order_id",
        "customer_id",
        "cancellation_case_id",
    )

    reconciliation_constraints = {
        element.name: element
        for element in recorder.created_tables[
            "agency_order_reconciliation_record"
        ]
        if isinstance(
            element,
            (CheckConstraint, ForeignKeyConstraint, UniqueConstraint),
        )
        and element.name
    }
    assert tuple(
        reconciliation_constraints[
            "fk_agency_order_reconciliation_record_compensation"
        ].column_keys
    ) == (
        "agency_id",
        "branch_id",
        "order_id",
        "customer_id",
        "cancellation_case_id",
        "compensation_record_id",
    )
    assert tuple(
        reconciliation_constraints[
            "uq_agency_order_reconciliation_compensation"
        ]._pending_colargs
    ) == ("compensation_record_id",)
    reconciliation_amount_sql = str(
        reconciliation_constraints[
            "ck_agency_order_reconciliation_record_amount"
        ].sqltext
    )
    assert "observed_amount IS NOT NULL" in reconciliation_amount_sql
    assert "currency IS NOT NULL" in reconciliation_amount_sql


def test_0007_guard_sql_freezes_state_machine_and_time_semantics(
    monkeypatch: pytest.MonkeyPatch,
):
    _revision, recorder = _record_upgrade(monkeypatch)
    sql = "\n".join(recorder.executed_sql)

    assert "DROP TRIGGER trg_agency_order_mutation_guard" in sql
    assert "CREATE TRIGGER trg_agency_order_mutation_guard" in sql
    assert "agency_order revision must advance by one" in sql
    assert "NEW.payment_status IS DISTINCT FROM OLD.payment_status" in sql
    assert "NEW.fulfillment_status IS DISTINCT" in sql
    assert "NEW.external_action_enabled IS DISTINCT" in sql
    assert (
        "agency_order cancelled_at only marks true cancellation" in sql
    )
    assert (
        "agency_order cancellation request timestamp is immutable" in sql
    )
    assert "NEW.status = 'cancelled'" in sql
    assert "NEW.cancelled_at IS NOT NULL" in sql
    assert "NEW.cancellation_requested_at IS NOT NULL" in sql
    assert "OLD.status = 'cancellation_pending'" in sql
    assert "OLD.status = 'manual_intervention'" in sql
    assert "NEW.status = 'manual_intervention'" in sql
    assert (
        "agency_order cannot enter review while cancellation case is open"
        in sql
    )
    assert (
        "pending agency_order cannot retain open cancellation case" in sql
    )
    assert "membership.user_id <> NEW.user_id" in sql

    assert (
        "new cancellation case must be inert revision one "
        "approval_pending"
    ) in sql
    assert "new cancellation case requires active agency" in sql
    assert "new cancellation case requires active branch" in sql
    assert "new cancellation case requires eligible branch approver" in sql
    assert "membership.user_id" in sql
    assert "<> NEW.requested_by_user_id" in sql
    assert "membership.user_id <> order_row.user_id" in sql
    assert "order customer cannot review cancellation case" in sql
    assert "cancellation review requires active branch approver" in sql
    assert "agency_row.status = 'active'" in sql
    assert "branch.status = 'active'" in sql
    assert (
        "pending cancellation approval requires eligible replacement "
        "approver" in sql
    )
    assert (
        "pending order review requires eligible replacement approver" in sql
    )
    assert "agency_membership binding is immutable" in sql
    assert "trg_agency_membership_binding_guard" in sql
    assert (
        "trg_agency_branch_role_grant_cancellation_approver_guard" in sql
    )
    assert (
        "agency_order_cancellation_case revision must advance by one"
        in sql
    )
    assert (
        "terminal agency_order_cancellation_case is immutable" in sql
    )
    assert (
        "OLD.status = 'approval_pending'"
        in sql
        and "'rejected'," in sql
        and "'action_pending'," in sql
        and "'completed'" in sql
    )
    assert "OLD.status = 'action_pending'" in sql
    assert "OLD.status = 'reconciliation_pending'" in sql
    assert "OLD.status = 'manual_intervention'" in sql
    assert (
        "invalid agency_order_cancellation_case status transition" in sql
    )


def test_0007_guards_allow_legacy_pending_and_use_latest_action_result(
    monkeypatch: pytest.MonkeyPatch,
):
    _revision, recorder = _record_upgrade(monkeypatch)
    sql = "\n".join(recorder.executed_sql)

    assert (
        "order_row.status IN (\n"
        "                              'cancellation_pending',\n"
        "                              'manual_intervention'"
    ) in sql
    assert "order_row.cancellation_requested_at IS NOT NULL" in sql
    assert "order_row.cancelled_at IS NULL" in sql
    assert "current_order.status = 'cancelled'" in sql
    assert sql.count("ORDER BY latest.record_sequence DESC") == 4
    assert "latest.action_type = 'supplier_cancel'" in sql
    assert "latest.action_type = 'refund'" in sql
    assert "recon.outcome = 'matched'" in sql
    assert (
        "completed cancellation case requires matched "
        "supplier reconciliation"
    ) in sql
    assert (
        "completed cancellation case requires matched refund "
        "reconciliation"
    ) in sql


def test_0007_guards_enforce_append_only_self_review_and_revision_binding(
    monkeypatch: pytest.MonkeyPatch,
):
    _revision, recorder = _record_upgrade(monkeypatch)
    sql = "\n".join(recorder.executed_sql)

    for table in (
        "agency_order_cancellation_event",
        "agency_order_compensation_record",
        "agency_order_reconciliation_record",
    ):
        assert f"BEFORE UPDATE OR DELETE ON {table}" in sql
    assert "is append-only" in sql
    assert "compensation recorder cannot reconcile own result" in sql
    assert "only successful compensation can be reconciled" in sql
    assert (
        "supplier cancellation reconciliation cannot include amount" in sql
    )
    assert (
        "new cancellation case required actions must match locked ledgers"
        in sql
    )
    assert "system-triggered compensation action is disabled" in sql
    assert "compensation record revision must match current case" in sql
    assert "reconciliation record revision must match current case" in sql
    assert "cancellation case revision requires audit event" in sql
    assert "zhixing_guard_cancellation_ledger_mutation" in sql
    assert "BEFORE INSERT OR UPDATE OR DELETE ON payment_attempt" in sql
    assert "BEFORE INSERT OR UPDATE OR DELETE ON fulfillment_record" in sql
    assert "locked_order.cancellation_requested_at IS NOT NULL" in sql
    assert "case_row.status IN (" in sql
    assert "'approval_pending'," in sql
    assert "'cancellation_pending'," in sql
    assert "'manual_intervention'," in sql
    assert "'cancelled'" in sql
    assert "FOR UPDATE" in sql


def test_0007_empty_downgrade_drops_in_dependency_order_and_restores_guard(
    monkeypatch: pytest.MonkeyPatch,
):
    recorder = _CancellationMigrationRecorder()
    _patch_ops(monkeypatch, recorder)
    revision = _load_revision()

    revision.downgrade()

    first_operation, first_sql = recorder.operations[0]
    assert first_operation == "execute"
    assert "IF EXISTS" in first_sql
    assert (
        "cannot downgrade 0007 after cancellation workflow data exists"
        in first_sql
    )
    assert recorder.dropped_tables == [
        "agency_order_reconciliation_record",
        "agency_order_compensation_record",
        "agency_order_cancellation_event",
        "agency_order_cancellation_case",
    ]
    assert (
        "uq_agency_order_branch_customer_id",
        "agency_order",
        "unique",
    ) in recorder.dropped_constraints
    assert recorder.dropped_columns == [
        ("agency_order", "cancellation_requested_at")
    ]
    sql = "\n".join(recorder.executed_sql)
    assert "CREATE FUNCTION zhixing_guard_agency_order_mutation()" in sql
    assert "agency_order binding is immutable in 0004" in sql
    assert "DROP TRIGGER trg_payment_attempt_cancellation_freeze" in sql
    assert "DROP TRIGGER trg_fulfillment_record_cancellation_freeze" in sql
    assert "DROP FUNCTION zhixing_guard_cancellation_ledger_mutation()" in sql
    assert "DROP TRIGGER trg_agency_membership_binding_guard" in sql
    assert (
        "DROP FUNCTION zhixing_guard_agency_membership_binding()" in sql
    )
    assert (
        "DROP TRIGGER "
        "trg_agency_branch_role_grant_cancellation_approver_guard" in sql
    )
    assert (
        "DROP FUNCTION "
        "zhixing_guard_cancellation_approver_availability()" in sql
    )
    assert sql.rindex(
        "CREATE FUNCTION zhixing_guard_agency_order_mutation()"
    ) > sql.index(
        "cannot downgrade 0007 after cancellation workflow data exists"
    )


def test_0007_business_data_rejection_precedes_destructive_downgrade(
    monkeypatch: pytest.MonkeyPatch,
):
    recorder = _RejectingDowngradeRecorder()
    _patch_ops(monkeypatch, recorder)

    with pytest.raises(
        RuntimeError,
        match="simulated PostgreSQL business data rejection",
    ):
        frozen.downgrade_agency_cancellation_workflow()

    guard_sql = recorder.executed_sql[0]
    for table in (
        "agency_order_cancellation_case",
        "agency_order_cancellation_event",
        "agency_order_compensation_record",
        "agency_order_reconciliation_record",
    ):
        assert f"SELECT 1 FROM {table}" in guard_sql
    assert "cancellation_requested_at IS NOT NULL" in guard_sql
    assert "RAISE EXCEPTION" in guard_sql
    assert recorder.dropped_tables == []
    assert recorder.dropped_indexes == []
    assert recorder.dropped_constraints == []
    assert recorder.dropped_columns == []
