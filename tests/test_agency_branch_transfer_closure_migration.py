from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import CheckConstraint, Column

import app.models._20260730_0005_agency_customer_invitation_claim_guards_frozen as guards_0005
import app.models._20260730_0006_customer_claim_trigger_fix_frozen as guards_0006
import app.models._20260731_0008_agency_branch_transfer_closure_frozen as frozen
import app.models._20260731_0008_agency_branch_transfer_closure_guards_frozen as guards
from app.models.agency_customer_lifecycle import (
    AgencyBranchLifecycleEvent,
    AgencyCustomerBranchTransfer,
)


ROOT = Path(__file__).resolve().parents[1]
REVISION_PATH = (
    ROOT
    / "alembic/versions/20260731_0008_agency_branch_transfer_closure.py"
)


def _load_revision() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "agency_branch_transfer_closure_revision_test",
        REVISION_PATH,
    )
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return revision


class _MigrationRecorder:
    def __init__(self) -> None:
        self.added_columns: dict[str, dict[str, Column[Any]]] = {}
        self.created_tables: dict[str, tuple[object, ...]] = {}
        self.created_uniques: dict[str, tuple[str, tuple[str, ...]]] = {}
        self.created_checks: dict[str, tuple[str, str]] = {}
        self.created_foreign_keys: dict[
            str,
            tuple[
                str,
                str,
                tuple[str, ...],
                tuple[str, ...],
                dict[str, Any],
            ],
        ] = {}
        self.created_indexes: dict[
            tuple[str, str],
            tuple[tuple[str, ...], dict[str, Any]],
        ] = {}
        self.dropped_constraints: list[tuple[str, str, str | None]] = []
        self.dropped_indexes: list[tuple[str, str]] = []
        self.dropped_tables: list[str] = []
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

    def create_table(
        self,
        table_name: str,
        *elements: object,
        **_kwargs: object,
    ) -> None:
        self.created_tables[table_name] = elements
        self.operations.append(("create_table", table_name))

    def create_unique_constraint(
        self,
        name: str,
        table_name: str,
        columns: list[str],
    ) -> None:
        self.created_uniques[name] = (table_name, tuple(columns))
        self.operations.append(("create_unique", name))

    def create_check_constraint(
        self,
        name: str,
        table_name: str,
        condition: str,
    ) -> None:
        self.created_checks[name] = (table_name, condition)
        self.operations.append(("create_check", name))

    def create_foreign_key(
        self,
        name: str,
        source_table: str,
        referent_table: str,
        local_cols: list[str],
        remote_cols: list[str],
        **kwargs: Any,
    ) -> None:
        self.created_foreign_keys[name] = (
            source_table,
            referent_table,
            tuple(local_cols),
            tuple(remote_cols),
            kwargs,
        )
        self.operations.append(("create_foreign_key", name))

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

    def drop_constraint(
        self,
        name: str,
        table_name: str,
        *,
        type_: str | None = None,
    ) -> None:
        self.dropped_constraints.append((name, table_name, type_))
        self.operations.append(("drop_constraint", name))

    def drop_index(self, name: str, *, table_name: str) -> None:
        self.dropped_indexes.append((name, table_name))
        self.operations.append(("drop_index", name))

    def drop_table(self, table_name: str) -> None:
        self.dropped_tables.append(table_name)
        self.operations.append(("drop_table", table_name))

    def drop_column(self, table_name: str, column_name: str) -> None:
        self.dropped_columns.append((table_name, column_name))
        self.operations.append(("drop_column", f"{table_name}.{column_name}"))


class _RejectingDowngradeRecorder(_MigrationRecorder):
    def execute(self, statement: object) -> None:
        sql = str(statement)
        super().execute(sql)
        if "cannot downgrade 0008 after branch transfer" in sql:
            raise RuntimeError("simulated PostgreSQL 0008 data rejection")


def _patch_ops(
    monkeypatch: pytest.MonkeyPatch,
    recorder: _MigrationRecorder,
) -> None:
    monkeypatch.setattr(frozen, "op", recorder)
    monkeypatch.setattr(guards, "op", recorder)
    monkeypatch.setattr(guards_0005, "op", recorder)
    monkeypatch.setattr(guards_0006, "op", recorder)


def _record_upgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ModuleType, _MigrationRecorder]:
    recorder = _MigrationRecorder()
    _patch_ops(monkeypatch, recorder)
    revision = _load_revision()
    revision.upgrade()
    return revision, recorder


def _statement_containing(
    recorder: _MigrationRecorder,
    token: str,
) -> str:
    return next(sql for sql in recorder.executed_sql if token in sql)


def _operation_index(
    recorder: _MigrationRecorder,
    operation_name: str,
    token: str,
) -> int:
    return next(
        index
        for index, operation in enumerate(recorder.operations)
        if operation[0] == operation_name and token in operation[1]
    )


def _table_column_names(elements: tuple[object, ...]) -> tuple[str, ...]:
    return tuple(
        element.name
        for element in elements
        if isinstance(element, Column)
    )


def _named_table_constraints(
    elements: tuple[object, ...],
) -> dict[str, object]:
    return {
        str(element.name): element
        for element in elements
        if getattr(element, "name", None) is not None
        and not isinstance(element, Column)
    }


def test_0008_revision_uses_frozen_helper_contract():
    revision = _load_revision()

    assert revision.revision == "20260731_0008"
    assert revision.down_revision == "20260730_0007"
    assert revision._upgrade.__module__ == (
        "app.models._20260731_0008_agency_branch_transfer_closure_frozen"
    )
    assert revision._downgrade.__module__ == (
        "app.models._20260731_0008_agency_branch_transfer_closure_frozen"
    )
    assert "revision-frozen" in (frozen.__doc__ or "")
    assert "revision-frozen" in (guards.__doc__ or "")
    assert "后续" in (frozen.__doc__ or "")


def test_0008_upgrade_matches_new_table_and_branch_lifecycle_contract(
    monkeypatch: pytest.MonkeyPatch,
):
    _revision, recorder = _record_upgrade(monkeypatch)

    closed_at = recorder.added_columns["agency_branch"]["closed_at"]
    assert closed_at.nullable is True
    branch_check = recorder.created_checks[
        "ck_agency_branch_lifecycle_timestamps"
    ]
    assert branch_check[0] == "agency_branch"
    assert "status = 'active'" in branch_check[1]
    assert "status = 'inactive'" in branch_check[1]
    assert "status = 'closed'" in branch_check[1]
    assert "closed_at >= deactivated_at" in branch_check[1]

    transfer_elements = recorder.created_tables[
        "agency_customer_branch_transfer"
    ]
    branch_event_elements = recorder.created_tables[
        "agency_branch_lifecycle_event"
    ]
    assert _table_column_names(transfer_elements) == tuple(
        AgencyCustomerBranchTransfer.__table__.columns.keys()
    )
    assert _table_column_names(branch_event_elements) == tuple(
        AgencyBranchLifecycleEvent.__table__.columns.keys()
    )

    transfer_constraints = _named_table_constraints(transfer_elements)
    branch_event_constraints = _named_table_constraints(
        branch_event_elements
    )
    live_transfer_names = {
        constraint.name
        for constraint in AgencyCustomerBranchTransfer.__table__.constraints
        if constraint.name is not None
    }
    live_branch_event_names = {
        constraint.name
        for constraint in AgencyBranchLifecycleEvent.__table__.constraints
        if constraint.name is not None
    }
    assert live_transfer_names <= set(transfer_constraints)
    assert live_branch_event_names <= set(branch_event_constraints)

    transfer_reason = transfer_constraints[
        "ck_customer_branch_transfer_reason"
    ]
    event_reason = branch_event_constraints[
        "ck_agency_branch_lifecycle_event_reason"
    ]
    assert isinstance(transfer_reason, CheckConstraint)
    assert isinstance(event_reason, CheckConstraint)
    assert str(transfer_reason.sqltext) == (
        "length(trim(reason)) BETWEEN 1 AND 500"
    )
    assert str(event_reason.sqltext) == (
        "length(trim(reason)) BETWEEN 1 AND 500"
    )
    assert (
        "event_type IN ('deactivated', 'closed')"
        == str(
            branch_event_constraints[
                "ck_agency_branch_lifecycle_event_type"
            ].sqltext
        )
    )


def test_0008_upgrade_rejects_legacy_closed_branches_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
):
    _revision, recorder = _record_upgrade(monkeypatch)

    first_operation, preflight = recorder.operations[0]
    assert first_operation == "execute"
    assert "LOCK TABLE" in preflight
    assert "IN SHARE ROW EXCLUSIVE MODE" in preflight
    assert "branch.status = 'closed'" in preflight
    assert (
        "cannot upgrade 0008: legacy closed agency_branch "
        "has current customers or open work"
    ) in preflight
    for table_name in (
        "agency_customer",
        "agency_customer_invitation",
        "agency_customer_advisor_assignment",
        "agency_branch_role_grant",
        "agency_order_review",
        "agency_order",
        "agency_quote",
        "agency_order_cancellation_case",
    ):
        assert f"FROM {table_name}" in preflight
    assert recorder.operations[1] == (
        "execute",
        "SET CONSTRAINTS ALL IMMEDIATE",
    )
    assert recorder.operations[2] == (
        "execute",
        "SET CONSTRAINTS ALL DEFERRED",
    )
    assert recorder.operations[3][0:2] == (
        "execute",
        "DROP TRIGGER trg_agency_customer_consent_record_consistency "
        "ON agency_customer_consent_record",
    )


def test_0008_reshapes_customer_identity_without_rewriting_history(
    monkeypatch: pytest.MonkeyPatch,
):
    _revision, recorder = _record_upgrade(monkeypatch)

    expected_uniques = {
        "uq_agency_customer_agency_id": (
            "agency_customer",
            ("agency_id", "id"),
        ),
        "uq_agency_customer_quote_binding": (
            "agency_customer",
            ("agency_id", "id", "user_id"),
        ),
        "uq_agency_customer_invitation_customer_id": (
            "agency_customer_invitation",
            ("agency_id", "customer_id", "id"),
        ),
        "uq_agency_customer_consent_record_customer_id": (
            "agency_customer_consent_record",
            ("agency_id", "customer_id", "id"),
        ),
        "uq_agency_customer_consent_record_sequence": (
            "agency_customer_consent_record",
            ("agency_id", "customer_id", "consent_sequence"),
        ),
        "uq_agency_customer_consent_record_revision": (
            "agency_customer_consent_record",
            ("agency_id", "customer_id", "customer_revision"),
        ),
        "uq_agency_customer_event_sequence": (
            "agency_customer_event",
            ("agency_id", "customer_id", "event_sequence"),
        ),
    }
    for name, expected in expected_uniques.items():
        assert recorder.created_uniques[name] == expected

    assert recorder.created_indexes[
        (
            "uq_agency_customer_invitation_pending",
            "agency_customer_invitation",
        )
    ][0] == ("agency_id", "customer_id")
    assert recorder.created_indexes[
        (
            "uq_customer_advisor_assignment_active",
            "agency_customer_advisor_assignment",
        )
    ][0] == ("agency_id", "customer_id")

    expected_customer_fks = {
        "fk_agency_customer_invitation_customer": (
            ("agency_id", "customer_id"),
            ("agency_id", "id"),
        ),
        "fk_agency_customer_consent_record_customer": (
            ("agency_id", "customer_id"),
            ("agency_id", "id"),
        ),
        "fk_agency_customer_event_customer": (
            ("agency_id", "customer_id"),
            ("agency_id", "id"),
        ),
        "fk_customer_advisor_assignment_customer": (
            ("agency_id", "customer_id"),
            ("agency_id", "id"),
        ),
        "fk_agency_order_customer": (
            ("agency_id", "customer_id"),
            ("agency_id", "id"),
        ),
        "fk_agency_quote_customer": (
            ("agency_id", "customer_id", "user_id"),
            ("agency_id", "id", "user_id"),
        ),
    }
    for name, (local_columns, remote_columns) in expected_customer_fks.items():
        foreign_key = recorder.created_foreign_keys[name]
        assert foreign_key[2] == local_columns
        assert foreign_key[3] == remote_columns
        assert "branch_id" not in foreign_key[2]
        assert "branch_id" not in foreign_key[3]

    claimed_fk = recorder.created_foreign_keys[
        "fk_agency_customer_claimed_invitation"
    ]
    consent_fk = recorder.created_foreign_keys[
        "fk_agency_customer_current_consent_record"
    ]
    assert claimed_fk[2:4] == (
        ("agency_id", "id", "claimed_invitation_id"),
        ("agency_id", "customer_id", "id"),
    )
    assert consent_fk[2:4] == (
        ("agency_id", "id", "current_consent_record_id"),
        ("agency_id", "customer_id", "id"),
    )
    assert claimed_fk[4]["deferrable"] is True
    assert claimed_fk[4]["initially"] == "DEFERRED"
    assert consent_fk[4]["deferrable"] is True
    assert consent_fk[4]["initially"] == "DEFERRED"


def test_0008_upgrade_orders_guard_fk_unique_and_table_operations(
    monkeypatch: pytest.MonkeyPatch,
):
    _revision, recorder = _record_upgrade(monkeypatch)

    flush_pending_events = _operation_index(
        recorder,
        "execute",
        "SET CONSTRAINTS ALL IMMEDIATE",
    )
    restore_deferred_mode = _operation_index(
        recorder,
        "execute",
        "SET CONSTRAINTS ALL DEFERRED",
    )
    drop_guard = _operation_index(
        recorder,
        "execute",
        "DROP TRIGGER trg_agency_branch_lifecycle_guard",
    )
    add_closed_at = _operation_index(
        recorder,
        "add_column",
        "agency_branch.closed_at",
    )
    drop_customer_fk = _operation_index(
        recorder,
        "drop_constraint",
        "fk_agency_customer_invitation_customer",
    )
    drop_old_unique = _operation_index(
        recorder,
        "drop_constraint",
        "uq_agency_customer_branch_id",
    )
    create_new_unique = _operation_index(
        recorder,
        "create_unique",
        "uq_agency_customer_agency_id",
    )
    create_customer_fk = _operation_index(
        recorder,
        "create_foreign_key",
        "fk_agency_customer_invitation_customer",
    )
    create_transfer = _operation_index(
        recorder,
        "create_table",
        "agency_customer_branch_transfer",
    )
    create_branch_event = _operation_index(
        recorder,
        "create_table",
        "agency_branch_lifecycle_event",
    )
    create_guard = _operation_index(
        recorder,
        "execute",
        "CREATE FUNCTION zhixing_guard_agency_branch_lifecycle()",
    )
    assert (
        flush_pending_events
        < restore_deferred_mode
        < drop_guard
        < add_closed_at
        < drop_customer_fk
        < drop_old_unique
        < create_new_unique
        < create_customer_fk
        < create_transfer
        < create_branch_event
        < create_guard
    )


def test_0008_guards_enforce_transfer_lock_order_and_bidirectional_binding(
    monkeypatch: pytest.MonkeyPatch,
):
    _revision, recorder = _record_upgrade(monkeypatch)

    transfer_guard = _statement_containing(
        recorder,
        "CREATE FUNCTION zhixing_guard_customer_branch_transfer_insert()",
    )
    customer_lock = transfer_guard.index("SELECT customer.*")
    branch_lock = transfer_guard.index("FROM agency_branch branch")
    assert customer_lock < branch_lock
    assert "ORDER BY branch.id\n            FOR UPDATE" in transfer_guard
    assert "current_customer.status" not in transfer_guard
    assert "branch.status IN ('active', 'inactive')" in transfer_guard
    assert "branch.status = 'active'" in transfer_guard
    assert "membership.role IN ('owner', 'admin')" in transfer_guard
    assert "pending invitation cleanup" in transfer_guard
    assert "open work cleanup" in transfer_guard

    all_sql = "\n".join(recorder.executed_sql)
    for trigger_name in (
        "trg_customer_branch_transfer_consistency",
        "trg_agency_customer_branch_transfer_consistency",
        "trg_agency_branch_lifecycle_state_consistency",
        "trg_agency_branch_lifecycle_event_consistency",
        "trg_customer_advisor_assignment_current_branch_consistency",
    ):
        trigger_sql = _statement_containing(recorder, trigger_name)
        assert "DEFERRABLE INITIALLY DEFERRED" in trigger_sql
    assert "agency_customer branch change requires matching transfer" in all_sql
    assert "customer branch transfer must match final customer state" in all_sql
    assert (
        "active advisor assignment requires active customer in current branch"
        in all_sql
    )
    assignment_guard = _statement_containing(
        recorder,
        "zhixing_validate_customer_advisor_assignment_current_branch()",
    )
    assert "TG_OP = 'INSERT' OR NEW.status = 'active'" in assignment_guard
    assert "customer.status = 'active'" in assignment_guard
    transfer_consistency = _statement_containing(
        recorder,
        "CREATE FUNCTION zhixing_validate_customer_branch_transfer()",
    )
    assert "current_customer.status <> 'active'" in transfer_consistency
    assert (
        "active advisor assignment requires active customer "
        "in transferred branch"
    ) in transfer_consistency
    assert "agency_customer_branch_transfer" in all_sql
    assert "agency_branch_lifecycle_event" in all_sql
    assert "% is append-only" in all_sql


def test_0008_guards_keep_history_but_validate_new_current_branch_records(
    monkeypatch: pytest.MonkeyPatch,
):
    _revision, recorder = _record_upgrade(monkeypatch)

    invitation_guard = _statement_containing(
        recorder,
        "CREATE FUNCTION zhixing_guard_agency_customer_invitation()",
    )
    consent_guard = _statement_containing(
        recorder,
        "CREATE FUNCTION zhixing_guard_new_agency_customer_consent_record()",
    )
    event_guard = _statement_containing(
        recorder,
        "CREATE FUNCTION zhixing_guard_agency_customer_event_insert()",
    )
    claim_consent_guard = _statement_containing(
        recorder,
        "CREATE FUNCTION zhixing_validate_agency_customer_claim_consent()",
    )
    assert "customer.branch_id = NEW.branch_id" in invitation_guard
    assert "customer.branch_id = NEW.branch_id" in consent_guard
    assert "customer.branch_id = NEW.branch_id" in event_guard
    assert re.search(
        r"IF TG_TABLE_NAME = 'agency_customer_invitation' THEN\s+"
        r"IF NEW\.status",
        claim_consent_guard,
    )
    assert re.search(
        r"IF TG_TABLE_NAME = 'agency_customer_consent_record' THEN\s+"
        r"IF current_customer\.current_consent_record_id",
        claim_consent_guard,
    )
    assert not re.search(
        r"IF TG_TABLE_NAME = 'agency_customer_(?:invitation|consent_record)'\s+"
        r"AND\b",
        claim_consent_guard,
    )

    assert "record.branch_id" not in consent_guard
    assert (
        "WHERE record.agency_id = NEW.agency_id\n"
        "              AND record.customer_id = NEW.customer_id"
        in consent_guard
    )
    assert "event.branch_id" not in event_guard
    assert (
        "WHERE event.agency_id = NEW.agency_id\n"
        "              AND event.customer_id = NEW.customer_id"
        in event_guard
    )


def test_0008_closure_guard_requires_inactive_terminal_and_full_drain(
    monkeypatch: pytest.MonkeyPatch,
):
    _revision, recorder = _record_upgrade(monkeypatch)

    branch_guard = _statement_containing(
        recorder,
        "CREATE FUNCTION zhixing_guard_agency_branch_lifecycle()",
    )
    assert "OLD.status = 'active' AND NEW.status = 'inactive'" in branch_guard
    assert "OLD.status = 'inactive' AND NEW.status = 'closed'" in branch_guard
    assert "closed agency_branch is immutable" in branch_guard
    customer_block = branch_guard[
        branch_guard.index("FROM agency_customer customer") :
        branch_guard.index("FROM agency_customer_invitation invitation")
    ]
    assert "customer.status" not in customer_block
    for table_name in (
        "agency_customer",
        "agency_customer_invitation",
        "agency_customer_advisor_assignment",
        "agency_branch_role_grant",
        "agency_order_review",
        "agency_order",
        "agency_quote",
        "agency_order_cancellation_case",
    ):
        assert f"FROM {table_name}" in branch_guard
    assert (
        "agency_branch closure requires zero current customers and open work"
        in branch_guard
    )

    lifecycle_event_guard = _statement_containing(
        recorder,
        "zhixing_guard_agency_branch_lifecycle_event_insert()",
    )
    assert "membership.role IN ('owner', 'admin')" in lifecycle_event_guard
    assert "NEW.event_type = 'deactivated'" in lifecycle_event_guard
    assert "NEW.event_type = 'closed'" in lifecycle_event_guard
    assert "event.event_sequence" in lifecycle_event_guard
    lifecycle_event_consistency = _statement_containing(
        recorder,
        "CREATE FUNCTION zhixing_validate_agency_branch_lifecycle_event()",
    )
    assert (
        "current_branch.status <> (CASE NEW.event_type"
        in lifecycle_event_consistency
    )
    assert "WHEN 'closed' THEN 'closed'\n                END)" in (
        lifecycle_event_consistency
    )


def test_0008_replaces_live_guards_for_inactive_branch_drain_only(
    monkeypatch: pytest.MonkeyPatch,
):
    _revision, recorder = _record_upgrade(monkeypatch)

    customer_guard = _statement_containing(
        recorder,
        "CREATE FUNCTION zhixing_guard_agency_customer_lifecycle()",
    )
    assert "branch.status = 'inactive'" in customer_guard
    assert "OLD.status = 'active'" in customer_guard
    assert (
        "active branch except unchanged drain revision"
        in customer_guard
    )

    review_guard = _statement_containing(
        recorder,
        "CREATE OR REPLACE FUNCTION\n"
        "            zhixing_validate_agency_order_review_consistency()",
    )
    assert "pending review requires active branch approver" in review_guard
    assert "current_review.status = 'approved'" in review_guard
    assert "current_review.status = 'rejected'" in review_guard
    assert "branch.status IN ('active', 'inactive')" in review_guard

    cancellation_guard = _statement_containing(
        recorder,
        "CREATE OR REPLACE FUNCTION\n"
        "            zhixing_guard_agency_order_cancellation_case()",
    )
    assert "branch.status IN ('active', 'inactive')" in cancellation_guard
    assert (
        "cancellation case update requires active or inactive branch"
        in cancellation_guard
    )
    assert (
        "cancellation review requires active or inactive branch approver"
        in cancellation_guard
    )

    drain_guard = _statement_containing(
        recorder,
        "CREATE FUNCTION zhixing_guard_cancellation_drain_branch_write()",
    )
    assert "branch.status IN ('active', 'inactive')" in drain_guard
    for trigger_name in (
        "trg_cancellation_event_drain_branch_guard",
        "trg_compensation_record_drain_branch_guard",
        "trg_reconciliation_record_drain_branch_guard",
    ):
        assert trigger_name in "\n".join(recorder.executed_sql)


def test_0008_empty_downgrade_is_fail_closed_and_restores_0007_shape(
    monkeypatch: pytest.MonkeyPatch,
):
    recorder = _MigrationRecorder()
    _patch_ops(monkeypatch, recorder)
    revision = _load_revision()

    revision.downgrade()

    first_operation, first_sql = recorder.operations[0]
    assert first_operation == "execute"
    assert "cannot downgrade 0008 after branch transfer" in first_sql
    assert "cannot downgrade 0008 while historical branch" in first_sql
    for table_name in (
        "agency_customer_invitation",
        "agency_customer_consent_record",
        "agency_customer_event",
        "agency_customer_advisor_assignment",
        "agency_quote",
        "agency_order",
    ):
        assert f"FROM {table_name} child" in first_sql

    assert recorder.dropped_tables == [
        "agency_branch_lifecycle_event",
        "agency_customer_branch_transfer",
    ]
    assert ("agency_branch", "closed_at") in recorder.dropped_columns
    assert recorder.created_uniques["uq_agency_customer_branch_id"] == (
        "agency_customer",
        ("agency_id", "branch_id", "id"),
    )
    old_quote_fk = recorder.created_foreign_keys["fk_agency_quote_customer"]
    assert old_quote_fk[2:4] == (
        ("agency_id", "branch_id", "customer_id", "user_id"),
        ("agency_id", "branch_id", "id", "user_id"),
    )
    assert recorder.created_indexes[
        (
            "uq_agency_customer_invitation_pending",
            "agency_customer_invitation",
        )
    ][0] == ("agency_id", "branch_id", "customer_id")
    sql = "\n".join(recorder.executed_sql)
    assert "CREATE FUNCTION zhixing_guard_agency_branch_lifecycle()" in sql
    assert "active or open branch relations must be closed first" in sql
    assert (
        "CREATE OR REPLACE FUNCTION "
        "zhixing_guard_agency_customer_lifecycle()" in sql
    )
    assert (
        "CREATE FUNCTION zhixing_validate_agency_customer_claim_consent()"
        in sql
    )
    restored_review = _statement_containing(
        recorder,
        "CREATE OR REPLACE FUNCTION\n"
        "            zhixing_validate_agency_order_review_consistency()",
    )
    restored_cancellation = _statement_containing(
        recorder,
        "CREATE OR REPLACE FUNCTION\n"
        "            zhixing_guard_agency_order_cancellation_case()",
    )
    assert "current_review.status = 'rejected'" not in restored_review
    assert "AND branch.status = 'active'" in restored_review
    assert "branch.status IN ('active', 'inactive')" not in restored_cancellation
    assert "cancellation case update requires active" not in restored_cancellation


def test_0008_business_data_rejection_precedes_destructive_downgrade(
    monkeypatch: pytest.MonkeyPatch,
):
    recorder = _RejectingDowngradeRecorder()
    _patch_ops(monkeypatch, recorder)

    with pytest.raises(
        RuntimeError,
        match="simulated PostgreSQL 0008 data rejection",
    ):
        frozen.downgrade_agency_branch_transfer_closure()

    guard_sql = recorder.executed_sql[0]
    assert "SELECT 1 FROM agency_customer_branch_transfer" in guard_sql
    assert "SELECT 1 FROM agency_branch_lifecycle_event" in guard_sql
    assert "RAISE EXCEPTION" in guard_sql
    assert recorder.dropped_tables == []
    assert recorder.dropped_indexes == []
    assert recorder.dropped_constraints == []
    assert recorder.dropped_columns == []
