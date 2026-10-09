from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    UniqueConstraint,
)

from app.models import (
    BRANCH_ROLES,
    AgencyBranch,
    AgencyBranchLifecycleEvent,
    AgencyBranchRoleGrant,
    AgencyCustomer,
    AgencyCustomerAdvisorAssignment,
    AgencyCustomerBranchTransfer,
    AgencyCustomerConsentRecord,
    AgencyCustomerEvent,
    AgencyCustomerInvitation,
    AgencyMembership,
    AgencyOrder,
    AgencyOrderEvent,
    AgencyOrderReview,
    AgencyQuote,
)
from app.models.base import Base
from app.models.migration_contract import BUSINESS_MANAGED_TABLES
from app.schemas.agency_customer_lifecycle import (
    AgencyBranchCloseRequest,
    AgencyBranchClosureReadinessResponse,
    AgencyBranchDeactivateRequest,
    AgencyBranchResponse,
    AgencyCustomerBranchTransferRequest,
    AgencyCustomerBranchTransferResponse,
)


REVISION_PATH = Path(
    "alembic/versions/20260726_0004_agency_customer_lifecycle.py"
)
FROZEN_HELPER_PATH = Path(
    "app/models/_20260726_0004_agency_customer_lifecycle_frozen.py"
)
TRANSACTION_GUARDS_HELPER_PATH = Path(
    "app/models/_20260726_0004_agency_transaction_guards_frozen.py"
)
FROZEN_0004_TABLE_NAMES = {
    "agency_branch",
    "agency_branch_role_grant",
    "agency_customer_event",
    "agency_customer_advisor_assignment",
}
UNCHANGED_0004_TABLE_MODELS = (
    AgencyBranchRoleGrant,
)


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _constraint_names(model, constraint_type) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, constraint_type) and constraint.name
    }


def _constraint_columns(constraint) -> tuple[str, ...]:
    if isinstance(constraint, ForeignKeyConstraint):
        return tuple(constraint.column_keys)
    pending = getattr(constraint, "_pending_colargs", ())
    if pending:
        return tuple(
            item if isinstance(item, str) else item.name
            for item in pending
        )
    return tuple(column.name for column in constraint.columns)


def _named_table_constraints(elements: tuple[object, ...]) -> dict[str, object]:
    return {
        element.name: element
        for element in elements
        if isinstance(
            element,
            (CheckConstraint, ForeignKeyConstraint, UniqueConstraint),
        )
        and element.name
    }


class _LifecycleMigrationRecorder:
    def __init__(self) -> None:
        self.created_tables: dict[str, tuple[object, ...]] = {}
        self.added_columns: dict[str, dict[str, Column[Any]]] = {}
        self.altered_columns: list[tuple[str, str, dict[str, Any]]] = []
        self.created_constraints: dict[str, tuple[str, str, tuple[str, ...]]] = {}
        self.dropped_constraints: set[tuple[str, str, str | None]] = set()
        self.created_indexes: dict[
            tuple[str, str],
            tuple[tuple[str, ...], dict[str, Any]],
        ] = {}
        self.dropped_indexes: set[tuple[str, str]] = set()
        self.executed_sql: list[str] = []

    def execute(self, statement: object) -> None:
        self.executed_sql.append(str(statement))

    def create_table(self, table_name: str, *elements, **_kwargs) -> None:
        self.created_tables[table_name] = elements

    def add_column(self, table_name: str, column: Column[Any]) -> None:
        self.added_columns.setdefault(table_name, {})[column.name] = column

    def alter_column(
        self,
        table_name: str,
        column_name: str,
        **kwargs,
    ) -> None:
        self.altered_columns.append((table_name, column_name, kwargs))

    def create_check_constraint(
        self,
        name: str,
        table_name: str,
        condition: str,
    ) -> None:
        self.created_constraints[name] = (
            "check",
            table_name,
            (str(condition),),
        )

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

    def create_foreign_key(
        self,
        name: str,
        source: str,
        _target: str,
        local: list[str],
        _remote: list[str],
        **_kwargs,
    ) -> None:
        self.created_constraints[name] = (
            "foreignkey",
            source,
            tuple(local),
        )

    def drop_constraint(
        self,
        name: str,
        table_name: str,
        *,
        type_: str | None = None,
    ) -> None:
        self.dropped_constraints.add((name, table_name, type_))

    def create_index(
        self,
        name: str,
        table_name: str,
        columns: list[str],
        **kwargs,
    ) -> None:
        self.created_indexes[(name, table_name)] = (tuple(columns), kwargs)

    def drop_index(self, name: str, *, table_name: str) -> None:
        self.dropped_indexes.add((name, table_name))


def _record_upgrade() -> tuple[ModuleType, ModuleType, _LifecycleMigrationRecorder]:
    frozen = _load_module(FROZEN_HELPER_PATH, "agency_lifecycle_frozen_test")
    revision = _load_module(REVISION_PATH, "agency_lifecycle_revision_test")
    recorder = _LifecycleMigrationRecorder()
    revision.op = recorder
    frozen.op = recorder

    # 0004 imports these callables from the canonical frozen module name.
    imported_frozen = revision._create_branch_table.__globals__
    imported_frozen["op"] = recorder
    imported_transaction_guards = (
        revision._create_transaction_mutation_guards.__globals__
    )
    imported_transaction_guards["op"] = recorder
    revision.upgrade()
    return revision, frozen, recorder


def test_lifecycle_models_are_registered_and_migration_owned():
    assert FROZEN_0004_TABLE_NAMES.issubset(Base.metadata.tables)
    assert FROZEN_0004_TABLE_NAMES.issubset(BUSINESS_MANAGED_TABLES)
    assert {
        "agency_customer_branch_transfer",
        "agency_branch_lifecycle_event",
    }.issubset(Base.metadata.tables)


def test_branch_model_has_terminal_lifecycle_timestamps():
    columns = AgencyBranch.__table__.columns
    assert columns["deactivated_at"].nullable is True
    assert columns["closed_at"].nullable is True
    lifecycle = next(
        constraint
        for constraint in AgencyBranch.__table__.constraints
        if constraint.name == "ck_agency_branch_lifecycle_timestamps"
    )
    lifecycle_sql = str(lifecycle.sqltext)
    assert "status = 'active'" in lifecycle_sql
    assert "status = 'inactive'" in lifecycle_sql
    assert "status = 'closed'" in lifecycle_sql
    assert "closed_at >= deactivated_at" in lifecycle_sql


def test_customer_identity_fks_preserve_historical_branch_attribution():
    expected_unique_columns = {
        (AgencyCustomer, "uq_agency_customer_agency_id"): (
            "agency_id",
            "id",
        ),
        (AgencyCustomer, "uq_agency_customer_quote_binding"): (
            "agency_id",
            "id",
            "user_id",
        ),
        (
            AgencyCustomerInvitation,
            "uq_agency_customer_invitation_customer_id",
        ): ("agency_id", "customer_id", "id"),
        (
            AgencyCustomerConsentRecord,
            "uq_agency_customer_consent_record_customer_id",
        ): ("agency_id", "customer_id", "id"),
        (
            AgencyCustomerConsentRecord,
            "uq_agency_customer_consent_record_sequence",
        ): ("agency_id", "customer_id", "consent_sequence"),
        (
            AgencyCustomerConsentRecord,
            "uq_agency_customer_consent_record_revision",
        ): ("agency_id", "customer_id", "customer_revision"),
    }
    for (model, name), columns in expected_unique_columns.items():
        constraint = next(
            item
            for item in model.__table__.constraints
            if item.name == name
        )
        assert _constraint_columns(constraint) == columns

    expected_fk_columns = {
        (AgencyCustomer, "fk_agency_customer_claimed_invitation"): (
            "agency_id",
            "id",
            "claimed_invitation_id",
        ),
        (AgencyCustomer, "fk_agency_customer_current_consent_record"): (
            "agency_id",
            "id",
            "current_consent_record_id",
        ),
        (
            AgencyCustomerInvitation,
            "fk_agency_customer_invitation_customer",
        ): ("agency_id", "customer_id"),
        (
            AgencyCustomerConsentRecord,
            "fk_agency_customer_consent_record_customer",
        ): ("agency_id", "customer_id"),
        (
            AgencyCustomerConsentRecord,
            "fk_agency_customer_consent_record_invitation",
        ): ("agency_id", "customer_id", "invitation_id"),
        (AgencyCustomerEvent, "fk_agency_customer_event_customer"): (
            "agency_id",
            "customer_id",
        ),
        (
            AgencyCustomerAdvisorAssignment,
            "fk_customer_advisor_assignment_customer",
        ): ("agency_id", "customer_id"),
        (AgencyQuote, "fk_agency_quote_customer"): (
            "agency_id",
            "customer_id",
            "user_id",
        ),
        (AgencyOrder, "fk_agency_order_customer"): (
            "agency_id",
            "customer_id",
        ),
    }
    for (model, name), columns in expected_fk_columns.items():
        constraint = next(
            item
            for item in model.__table__.constraints
            if item.name == name
        )
        assert _constraint_columns(constraint) == columns


def test_branch_roles_are_store_scoped_and_exclude_tenant_admin_roles():
    assert BRANCH_ROLES == (
        "travel_advisor",
        "booking_operator",
        "approver",
        "finance",
        "auditor",
        "branch_manager",
    )
    role_constraint = next(
        constraint
        for constraint in AgencyBranchRoleGrant.__table__.constraints
        if constraint.name == "ck_branch_role_grant_role"
    )
    role_sql = str(role_constraint.sqltext)
    for role in BRANCH_ROLES:
        assert role in role_sql
    assert "owner" not in role_sql
    assert "admin" not in role_sql

    membership_role = next(
        constraint
        for constraint in AgencyMembership.__table__.constraints
        if constraint.name == "ck_agency_membership_role"
    )
    assert "branch_manager" in str(membership_role.sqltext)
    assert "uq_agency_membership_agency_id" in _constraint_names(
        AgencyMembership,
        UniqueConstraint,
    )


def test_customer_and_transaction_bindings_are_branch_explicit():
    assert AgencyCustomer.__table__.columns["user_id"].nullable is True
    assert AgencyQuote.__table__.columns["user_id"].nullable is False
    for model in (AgencyCustomer, AgencyQuote, AgencyOrder):
        assert model.__table__.columns["branch_id"].nullable is False
    for model in (AgencyQuote, AgencyOrder):
        assert model.__table__.columns["customer_id"].nullable is False
    for model in (AgencyOrderEvent, AgencyOrderReview):
        assert model.__table__.columns["branch_id"].nullable is False

    assert {
        "uq_agency_customer_agency_id",
        "uq_agency_customer_branch_no",
        "uq_agency_customer_quote_binding",
    }.issubset(_constraint_names(AgencyCustomer, UniqueConstraint))
    assert "fk_agency_quote_customer" in _constraint_names(
        AgencyQuote,
        ForeignKeyConstraint,
    )
    assert "fk_agency_order_quote_binding" in _constraint_names(
        AgencyOrder,
        ForeignKeyConstraint,
    )


def test_advisor_assignment_has_one_active_owner_and_auditable_ending():
    active_index = next(
        index
        for index in AgencyCustomerAdvisorAssignment.__table__.indexes
        if index.name == "uq_customer_advisor_assignment_active"
    )
    assert active_index.unique is True
    assert tuple(column.name for column in active_index.columns) == (
        "agency_id",
        "customer_id",
    )
    assert str(active_index.dialect_options["postgresql"]["where"]) == (
        "status = 'active'"
    )
    assert AgencyCustomerAdvisorAssignment.__table__.columns[
        "ended_reason"
    ].nullable is True
    ending_constraint = next(
        constraint
        for constraint in AgencyCustomerAdvisorAssignment.__table__.constraints
        if constraint.name == "ck_customer_advisor_assignment_ending"
    )
    ending_sql = str(ending_constraint.sqltext)
    assert "ended_reason IS NOT NULL" in ending_sql
    assert "length(trim(ended_reason)) > 0" in ending_sql


def test_customer_event_model_is_append_only_shaped_and_revisioned():
    columns = AgencyCustomerEvent.__table__.columns
    assert "updated_at" not in columns
    assert columns["customer_revision"].nullable is False
    sequence = next(
        constraint
        for constraint in AgencyCustomerEvent.__table__.constraints
        if constraint.name == "uq_agency_customer_event_sequence"
    )
    assert _constraint_columns(sequence) == (
        "agency_id",
        "customer_id",
        "event_sequence",
    )


def test_branch_transfer_model_is_append_only_and_revision_bound():
    columns = AgencyCustomerBranchTransfer.__table__.columns
    assert "updated_at" not in columns
    assert {
        "id",
        "agency_id",
        "customer_id",
        "from_branch_id",
        "to_branch_id",
        "customer_revision",
        "transferred_by_user_id",
        "reason",
        "transferred_at",
        "created_at",
    } == set(columns.keys())

    revision = next(
        constraint
        for constraint in AgencyCustomerBranchTransfer.__table__.constraints
        if constraint.name == "uq_customer_branch_transfer_revision"
    )
    assert _constraint_columns(revision) == (
        "agency_id",
        "customer_id",
        "customer_revision",
    )
    customer_fk = next(
        constraint
        for constraint in AgencyCustomerBranchTransfer.__table__.constraints
        if constraint.name == "fk_customer_branch_transfer_customer"
    )
    assert _constraint_columns(customer_fk) == (
        "agency_id",
        "customer_id",
    )
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in AgencyCustomerBranchTransfer.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert (
        checks["ck_customer_branch_transfer_distinct_branches"]
        == "from_branch_id <> to_branch_id"
    )
    assert "customer_revision >= 2" in checks[
        "ck_customer_branch_transfer_revision"
    ]
    assert "length(trim(reason)) BETWEEN 1 AND 500" in checks[
        "ck_customer_branch_transfer_reason"
    ]


def test_branch_lifecycle_event_model_is_append_only_and_redactable():
    columns = AgencyBranchLifecycleEvent.__table__.columns
    assert "updated_at" not in columns
    assert {
        "id",
        "agency_id",
        "branch_id",
        "event_sequence",
        "branch_revision",
        "event_type",
        "actor_user_id",
        "reason",
        "created_at",
    } == set(columns.keys())
    sequence = next(
        constraint
        for constraint in AgencyBranchLifecycleEvent.__table__.constraints
        if constraint.name == "uq_agency_branch_lifecycle_event_sequence"
    )
    revision = next(
        constraint
        for constraint in AgencyBranchLifecycleEvent.__table__.constraints
        if constraint.name == "uq_agency_branch_lifecycle_event_revision"
    )
    assert _constraint_columns(sequence) == (
        "agency_id",
        "branch_id",
        "event_sequence",
    )
    assert _constraint_columns(revision) == (
        "agency_id",
        "branch_id",
        "branch_revision",
    )
    event_type = next(
        constraint
        for constraint in AgencyBranchLifecycleEvent.__table__.constraints
        if constraint.name == "ck_agency_branch_lifecycle_event_type"
    )
    assert "deactivated" in str(event_type.sqltext)
    assert "closed" in str(event_type.sqltext)


def test_branch_lifecycle_and_transfer_dtos_are_strict_and_redacted():
    for request_model in (
        AgencyBranchDeactivateRequest,
        AgencyBranchCloseRequest,
        AgencyCustomerBranchTransferRequest,
    ):
        assert request_model.model_config["extra"] == "forbid"

    assert "closed_at" in AgencyBranchResponse.model_fields
    assert set(AgencyBranchClosureReadinessResponse.model_fields) == {
        "branch_id",
        "status",
        "revision",
        "ready",
        "current_customer_count",
        "pending_invitation_count",
        "active_assignment_count",
        "active_role_grant_count",
        "pending_review_count",
        "open_quote_count",
        "open_order_count",
        "open_cancellation_case_count",
    }
    transfer_fields = set(AgencyCustomerBranchTransferResponse.model_fields)
    assert transfer_fields == {
        "id",
        "agency_id",
        "customer_id",
        "from_branch_id",
        "to_branch_id",
        "customer_revision",
        "transferred_at",
        "created_at",
    }
    assert "reason" not in transfer_fields
    assert "transferred_by_user_id" not in transfer_fields


def test_0004_revision_uses_revision_frozen_helper_contract():
    revision = _load_module(REVISION_PATH, "agency_lifecycle_revision_metadata")
    frozen = _load_module(FROZEN_HELPER_PATH, "agency_lifecycle_frozen_metadata")
    transaction_guards = _load_module(
        TRANSACTION_GUARDS_HELPER_PATH,
        "agency_transaction_guards_frozen_metadata",
    )

    assert revision.revision == "20260726_0004"
    assert revision.down_revision == "20260726_0003"
    assert FROZEN_HELPER_PATH.name == (
        "_20260726_0004_agency_customer_lifecycle_frozen.py"
    )
    assert "revision-frozen" in (frozen.__doc__ or "")
    assert "后续数据库变化必须新增 revision" in (frozen.__doc__ or "")
    assert "revision-frozen" in (transaction_guards.__doc__ or "")
    assert revision._create_branch_table.__module__ == (
        "app.models._20260726_0004_agency_customer_lifecycle_frozen"
    )
    assert revision._create_transaction_mutation_guards.__module__ == (
        "app.models._20260726_0004_agency_transaction_guards_frozen"
    )


def test_0004_orders_quote_binding_ddl_for_postgres_dependencies():
    source = REVISION_PATH.read_text(encoding="utf-8")
    upgrade_source, downgrade_source = source.split("def downgrade()", maxsplit=1)

    assert upgrade_source.index(
        '"fk_agency_order_quote_tenant_user"'
    ) < upgrade_source.index('"uq_agency_quote_agency_user_id"')
    assert downgrade_source.index(
        '"uq_agency_quote_agency_user_id"'
    ) < downgrade_source.index('"fk_agency_order_quote_tenant_user"')
    assert upgrade_source.index(
        "_create_transaction_mutation_guards()"
    ) > upgrade_source.index('"fk_agency_order_quote_binding"')
    assert downgrade_source.index(
        "_drop_transaction_mutation_guards()"
    ) < downgrade_source.index(
        '_drop_columns("agency_order", "customer_id", "branch_id")'
    )


def test_0004_unchanged_table_contract_still_matches_live_model():
    _revision, _frozen, recorder = _record_upgrade()

    assert set(recorder.created_tables) == FROZEN_0004_TABLE_NAMES
    for model in UNCHANGED_0004_TABLE_MODELS:
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

        migrated_constraints = _named_table_constraints(elements)
        model_constraints = {
            constraint.name: constraint
            for constraint in model.__table__.constraints
            if isinstance(
                constraint,
                (CheckConstraint, ForeignKeyConstraint, UniqueConstraint),
            )
            and constraint.name
        }
        assert set(migrated_constraints) == set(model_constraints)
        for name, constraint in model_constraints.items():
            assert _constraint_columns(migrated_constraints[name]) == (
                _constraint_columns(constraint)
            )

        migrated_indexes = {
            name: details
            for (name, indexed_table), details
            in recorder.created_indexes.items()
            if indexed_table == table_name
        }
        assert set(migrated_indexes) == {
            index.name for index in model.__table__.indexes
        }
        for index in model.__table__.indexes:
            columns, kwargs = migrated_indexes[index.name]
            assert columns == tuple(column.name for column in index.columns)
            assert bool(kwargs.get("unique", False)) is bool(index.unique)
            expected_where = index.dialect_options["postgresql"].get("where")
            actual_where = kwargs.get("postgresql_where")
            assert str(actual_where) == str(expected_where)


def test_0004_delta_supplies_branch_customer_constraints_to_legacy_tables():
    _revision, _frozen, recorder = _record_upgrade()

    expected_added_columns = {
        "agency_customer": {
            "branch_id",
            "customer_no",
            "source_type",
            "source_reference",
            "consent_status",
            "consent_version",
            "consent_evidence_hash",
            "consent_updated_at",
            "lifecycle_revision",
            "invited_at",
            "deactivated_at",
        },
        "agency_quote": {"branch_id", "customer_id"},
        "agency_order": {"branch_id", "customer_id"},
        "agency_order_event": {"branch_id"},
        "agency_order_review": {"branch_id"},
    }
    assert {
        table: set(columns)
        for table, columns in recorder.added_columns.items()
    } == expected_added_columns

    expected_constraint_columns = {
        "uq_agency_membership_agency_id": (
            "agency_id",
            "id",
        ),
        "uq_agency_customer_branch_id": (
            "agency_id",
            "branch_id",
            "id",
        ),
        "uq_agency_customer_quote_binding": (
            "agency_id",
            "branch_id",
            "id",
            "user_id",
        ),
        "uq_agency_quote_order_binding": (
            "agency_id",
            "branch_id",
            "customer_id",
            "user_id",
            "id",
        ),
        "fk_agency_quote_customer": (
            "agency_id",
            "branch_id",
            "customer_id",
            "user_id",
        ),
        "fk_agency_order_quote_binding": (
            "agency_id",
            "branch_id",
            "customer_id",
            "user_id",
            "quote_id",
        ),
        "fk_agency_order_event_order_branch": (
            "agency_id",
            "branch_id",
            "order_id",
        ),
        "fk_agency_order_review_order_branch": (
            "agency_id",
            "branch_id",
            "order_id",
        ),
    }
    for name, columns in expected_constraint_columns.items():
        assert recorder.created_constraints[name][2] == columns

    assert {
        ("uq_agency_quote_agency_user_id", "agency_quote", "unique"),
        (
            "fk_agency_order_quote_tenant_user",
            "agency_order",
            "foreignkey",
        ),
        (
            "fk_agency_order_event_order_tenant",
            "agency_order_event",
            "foreignkey",
        ),
        (
            "fk_agency_order_review_order_tenant",
            "agency_order_review",
            "foreignkey",
        ),
    }.issubset(recorder.dropped_constraints)

    altered_to_required = {
        (table, column)
        for table, column, kwargs in recorder.altered_columns
        if kwargs.get("nullable") is False
    }
    assert {
        ("agency_customer", "branch_id"),
        ("agency_customer", "customer_no"),
        ("agency_quote", "branch_id"),
        ("agency_quote", "customer_id"),
        ("agency_order", "branch_id"),
        ("agency_order", "customer_id"),
        ("agency_order_event", "branch_id"),
        ("agency_order_review", "branch_id"),
    }.issubset(altered_to_required)


def test_0004_sql_guards_customer_revision_and_append_only_events():
    _revision, _frozen, recorder = _record_upgrade()
    sql = "\n".join(recorder.executed_sql)

    assert "CREATE TRIGGER trg_agency_branch_lifecycle_guard" in sql
    assert "agency_branch revision must advance by one" in sql
    assert "active or open branch relations must be closed first" in sql
    assert "pending reviews require another active approver" in sql
    assert "CREATE TRIGGER trg_agency_customer_event_append_only" in sql
    assert "BEFORE UPDATE OR DELETE ON agency_customer_event" in sql
    assert "agency_customer_event is append-only" in sql
    assert "CREATE TRIGGER trg_agency_customer_lifecycle_guard" in sql
    assert (
        "NEW.lifecycle_revision <> OLD.lifecycle_revision + 1"
        in sql
    )
    assert "blocked agency_customer requires risk review" in sql
    assert (
        "pending customer order review must be rejected before reactivation"
        in sql
    )
    assert "OLD.consent_status = 'unknown'" in sql
    assert "new agency_customer revision must be one" in sql
    assert "CREATE TRIGGER trg_customer_advisor_assignment_guard" in sql
    assert "NEW.revision <> OLD.revision + 1" in sql
    assert "CREATE TRIGGER trg_agency_order_review_mutation_guard" in sql
    assert "NEW.branch_id IS DISTINCT FROM OLD.branch_id" in sql
    assert "CREATE TRIGGER trg_agency_quote_mutation_guard" in sql
    assert "new agency_quote requires active consented customer" in sql
    assert "new agency_quote requires active branch" in sql
    assert "new agency_quote valid_until must be in the future" in sql
    assert "expired agency_quote cannot be offered or accepted" in sql
    assert "NEW.valid_until <= CURRENT_TIMESTAMP" in sql
    assert "agency_quote revision must advance by one" in sql
    assert "invalid agency_quote status transition" in sql
    assert "OR NOT EXISTS (" in sql
    assert "order_row.quote_id = OLD.id" in sql
    assert "CREATE TRIGGER trg_agency_order_mutation_guard" in sql
    assert "new agency_order requires active consented customer" in sql
    assert "new agency_order requires active branch" in sql
    assert "new agency_order requires accepted valid matching agency_quote" in sql
    assert "quote.valid_until > CURRENT_TIMESTAMP" in sql
    assert "quote.total_amount = NEW.total_amount" in sql
    assert "quote.currency = NEW.currency" in sql
    assert "quote.quote_snapshot::text = NEW.quote_snapshot::text" in sql
    assert sql.index(
        "new agency_order requires active consented customer"
    ) < sql.index("new agency_order requires active branch")
    assert sql.index("new agency_order requires active branch") < sql.index(
        "new agency_order requires accepted valid matching agency_quote"
    )
    assert (
        "OLD.status IN ('draft', 'approved', 'processing', 'failed')" in sql
    )
    assert "agency_order revision must advance by one" in sql
    assert "invalid agency_order status transition" in sql
    assert "pending agency_order requires active branch approver" in sql
    assert "pending review requires active branch approver" in sql
    assert "new agency_order must start as inert revision one draft" in sql
    assert (
        "CREATE FUNCTION zhixing_validate_agency_order_review_consistency()"
        in sql
    )
    assert "trg_agency_order_review_consistency" in sql
    assert "trg_agency_order_review_state_consistency" in sql
    assert sql.count("DEFERRABLE INITIALLY DEFERRED") == 2
    assert "agency_order requires matching final review state" in sql
    assert "agency_order_review binding does not match order" in sql
    assert "agency_order_review requires active branch approver" in sql
    assert "approved order requires active consented customer" in sql
    assert "AND agency.status = 'active'" in sql
    assert "AND branch.status = 'active'" in sql
