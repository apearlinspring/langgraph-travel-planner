"""PostgreSQL integration checks for the travel-agency transaction domain.

The suite is intentionally opt-in and never reads the repository ``.env``.
Run it against a dedicated database whose name contains ``test`` or ``ci``:

    $env:ZHIXING_TEST_POSTGRES_DSN = `
      "postgresql://travel_user:change-me@127.0.0.1:5432/zhixing_test"
    uv run python -m pytest --run-integration `
      tests/test_agency_transaction_postgres_integration.py -q

Every test uses a generated PostgreSQL schema and drops only that schema.
"""
from __future__ import annotations

import asyncio
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool


pytestmark = [pytest.mark.integration, pytest.mark.slow]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_DSN_ENV = "ZHIXING_TEST_POSTGRES_DSN"
_SAFE_DATABASE_NAME = re.compile(r"(^|[_-])(test|ci)($|[_-])", re.IGNORECASE)


@dataclass(frozen=True)
class PostgresSandbox:
    schema: str
    sync_url: URL
    alembic_config: Config

    def async_engine(self) -> AsyncEngine:
        return create_async_engine(
            self.sync_url,
            poolclass=NullPool,
            connect_args={"connect_timeout": 5},
        )


@dataclass(frozen=True)
class TenantActors:
    agency_id: uuid.UUID
    advisor_id: uuid.UUID
    approver_id: uuid.UUID
    customer_id: uuid.UUID


def _explicit_test_url() -> URL:
    raw_dsn = (os.getenv(TEST_DSN_ENV) or "").strip()
    if not raw_dsn:
        pytest.skip(f"{TEST_DSN_ENV} is not configured")

    try:
        parsed = make_url(raw_dsn)
    except Exception:
        pytest.fail(f"{TEST_DSN_ENV} is not a valid SQLAlchemy PostgreSQL DSN")

    if parsed.get_backend_name() != "postgresql":
        pytest.fail(f"{TEST_DSN_ENV} must use the PostgreSQL dialect")

    database_name = parsed.database or ""
    if not _SAFE_DATABASE_NAME.search(database_name):
        pytest.fail(
            f"{TEST_DSN_ENV} must target a dedicated database whose name "
            "contains a standalone 'test' or 'ci' segment"
        )

    return parsed.set(drivername="postgresql+psycopg")


def _schema_scoped_url(database_url: URL, schema: str) -> URL:
    query = dict(database_url.query)
    existing_options = str(query.get("options") or "").strip()
    search_path_option = f"-csearch_path={schema}"
    query["options"] = " ".join(
        option for option in (existing_options, search_path_option) if option
    )
    return database_url.set(query=query)


def _alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return config


@pytest.fixture
def postgres_schema(monkeypatch: pytest.MonkeyPatch) -> PostgresSandbox:
    """Create one isolated schema and route Alembic to it."""

    database_url = _explicit_test_url()
    schema = f"zhixing_tx_it_{uuid.uuid4().hex}"
    admin_engine = create_engine(
        database_url,
        poolclass=NullPool,
        connect_args={"connect_timeout": 5},
    )
    scoped_url = _schema_scoped_url(database_url, schema)
    config = _alembic_config()
    schema_created = False

    monkeypatch.setenv("ZHIXING_DISABLE_DOTENV", "1")
    import app.config as app_config
    import app.models  # noqa: F401

    migration_settings = SimpleNamespace(
        database_url=scoped_url.render_as_string(hide_password=False),
        postgres_connect_timeout_seconds=5,
        postgres_statement_timeout_seconds=10,
        sql_echo=False,
    )
    monkeypatch.setattr(app_config, "settings", migration_settings)

    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        schema_created = True

        scoped_probe = create_engine(
            scoped_url,
            poolclass=NullPool,
            connect_args={"connect_timeout": 5},
        )
        try:
            with scoped_probe.connect() as connection:
                current_schema = connection.scalar(text("SELECT current_schema()"))
            if current_schema != schema:
                pytest.fail("PostgreSQL test connection did not enter the isolated schema")
        finally:
            scoped_probe.dispose()

        yield PostgresSandbox(
            schema=schema,
            sync_url=scoped_url,
            alembic_config=config,
        )
    finally:
        if schema_created:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


@pytest.fixture
def migrated_postgres(postgres_schema: PostgresSandbox) -> PostgresSandbox:
    command.upgrade(postgres_schema.alembic_config, "head")
    return postgres_schema


def _business_tables(sandbox: PostgresSandbox) -> set[str]:
    engine = create_engine(
        sandbox.sync_url,
        poolclass=NullPool,
        connect_args={"connect_timeout": 5},
    )
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _session_factory(
    sandbox: PostgresSandbox,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = sandbox.async_engine()
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed_tenant(
    session_factory: async_sessionmaker[AsyncSession],
) -> TenantActors:
    from app.models.agency_transaction import (
        Agency,
        AgencyCustomer,
        AgencyMembership,
    )
    from app.models.user import User

    agency_id = uuid.uuid4()
    advisor_id = uuid.uuid4()
    approver_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    unique = uuid.uuid4().hex

    async with session_factory() as session, session.begin():
        session.add_all(
            [
                User(
                    id=advisor_id,
                    username=f"advisor-{unique}",
                    email=f"advisor-{unique}@example.test",
                    password_hash="integration-test-only",
                ),
                User(
                    id=customer_id,
                    username=f"customer-{unique}",
                    email=f"customer-{unique}@example.test",
                    password_hash="integration-test-only",
                ),
                User(
                    id=approver_id,
                    username=f"approver-{unique}",
                    email=f"approver-{unique}@example.test",
                    password_hash="integration-test-only",
                ),
                Agency(
                    id=agency_id,
                    agency_code=f"AG-{unique[:20]}",
                    name="PostgreSQL Integration Agency",
                    status="active",
                ),
                AgencyMembership(
                    agency_id=agency_id,
                    user_id=advisor_id,
                    role="travel_advisor",
                    status="active",
                    joined_at=datetime.now(UTC),
                ),
                AgencyMembership(
                    agency_id=agency_id,
                    user_id=approver_id,
                    role="approver",
                    status="active",
                    joined_at=datetime.now(UTC),
                ),
                AgencyCustomer(
                    agency_id=agency_id,
                    user_id=customer_id,
                    status="active",
                    activated_at=datetime.now(UTC),
                ),
            ]
        )

    return TenantActors(
        agency_id=agency_id,
        advisor_id=advisor_id,
        approver_id=approver_id,
        customer_id=customer_id,
    )


def _quote_request(actors: TenantActors):
    from app.schemas.agency_transaction import AgencyQuoteCreateRequest

    return AgencyQuoteCreateRequest(
        agency_id=actors.agency_id,
        customer_user_id=actors.customer_id,
        total_amount=Decimal("1288.00"),
        currency="CNY",
        quote_snapshot={
            "schema_version": "agency_quote.v1",
            "destination": "杭州",
        },
        valid_until=datetime.now(UTC) + timedelta(days=2),
    )


async def _transaction_call(
    session_factory: async_sessionmaker[AsyncSession],
    operation: Callable[[Any], Awaitable[Any]],
) -> tuple[str, Any]:
    from app.agency.transaction_service import AgencyTransactionConflict

    async with session_factory() as session:
        try:
            async with session.begin():
                result = await operation(session)
            return "ok", result
        except AgencyTransactionConflict as error:
            await session.rollback()
            return "conflict", error.code


def test_alembic_upgrade_downgrade_and_legacy_bootstrap(
    postgres_schema: PostgresSandbox,
) -> None:
    """Exercise both an empty schema and the legacy create_all adoption path."""

    command.upgrade(postgres_schema.alembic_config, "head")
    assert {
        "user",
        "conversation",
        "message",
        "agency",
        "agency_quote",
        "agency_order",
        "agency_order_review",
        "agency_order_event",
        "idempotency_record",
    }.issubset(_business_tables(postgres_schema))

    command.downgrade(postgres_schema.alembic_config, "base")
    assert not {
        "user",
        "conversation",
        "message",
        "agency",
        "agency_quote",
        "agency_order",
        "agency_order_review",
    }.intersection(_business_tables(postgres_schema))

    engine = create_engine(
        postgres_schema.sync_url,
        poolclass=NullPool,
        connect_args={"connect_timeout": 5},
    )
    try:
        with engine.begin() as connection:
            connection.execute(
                text('CREATE TABLE "user" (id UUID PRIMARY KEY)')
            )
            connection.execute(
                text(
                    "CREATE TABLE conversation ("
                    "id UUID PRIMARY KEY, "
                    'user_id UUID NOT NULL REFERENCES "user"(id)'
                    ")"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE message ("
                    "id UUID PRIMARY KEY, "
                    "conversation_id UUID NOT NULL REFERENCES conversation(id)"
                    ")"
                )
            )
    finally:
        engine.dispose()

    command.upgrade(postgres_schema.alembic_config, "head")
    assert {
        "agency",
        "agency_quote",
        "agency_order",
        "agency_order_review",
        "agency_order_event",
    }.issubset(_business_tables(postgres_schema))


@pytest.mark.asyncio
async def test_composite_tenant_fk_and_order_event_append_only_trigger(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.agency.order_review_service import AgencyOrderReviewService
    from app.models.agency_order_review import AgencyOrderReview
    from app.models.agency_transaction import (
        Agency,
        AgencyOrderEvent,
        AgencyQuote,
        SupplierProduct,
    )

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        other_agency_id = uuid.uuid4()
        other_product_id = uuid.uuid4()

        async with session_factory() as session, session.begin():
            session.add(
                Agency(
                    id=other_agency_id,
                    agency_code=f"OTHER-{uuid.uuid4().hex[:20]}",
                    name="Other Agency",
                    status="active",
                )
            )
            session.add(
                SupplierProduct(
                    id=other_product_id,
                    agency_id=other_agency_id,
                    supplier_code="supplier-other",
                    external_product_code=f"product-{uuid.uuid4().hex}",
                    name="Cross-tenant product",
                    product_type="package",
                    status="active",
                )
            )

        with pytest.raises(IntegrityError):
            async with session_factory() as session, session.begin():
                session.add(
                    AgencyQuote(
                        quote_no=f"Q-{uuid.uuid4().hex}",
                        idempotency_key=f"cross-tenant-{uuid.uuid4().hex}",
                        agency_id=actors.agency_id,
                        user_id=actors.customer_id,
                        product_id=other_product_id,
                        status="draft",
                        revision=1,
                        payload_hash="a" * 64,
                        total_amount=Decimal("10.00"),
                        currency="CNY",
                        snapshot_version="agency_quote.v1",
                        quote_snapshot={},
                        valid_until=datetime.now(UTC) + timedelta(days=1),
                    )
                )
                await session.flush()

        async with session_factory() as session, session.begin():
            quote = await AgencyOrderReviewService(session).create_quote(
                actor_user_id=actors.advisor_id,
                data=_quote_request(actors),
                idempotency_key=f"quote-{uuid.uuid4().hex}",
            )
            await AgencyOrderReviewService(session).issue_quote(
                actor_user_id=actors.advisor_id,
                quote_id=quote.id,
                expected_revision=quote.revision,
                idempotency_key=f"issue-{uuid.uuid4().hex}",
            )

        async with session_factory() as session, session.begin():
            service = AgencyOrderReviewService(session)
            accepted = await service.accept_quote(
                actor_user_id=actors.customer_id,
                quote_id=quote.id,
                expected_revision=2,
                idempotency_key=f"accept-{uuid.uuid4().hex}",
            )
            from app.schemas.agency_transaction import AgencyOrderCreateRequest

            order = await service.create_order(
                actor_user_id=actors.customer_id,
                data=AgencyOrderCreateRequest(
                    agency_id=actors.agency_id,
                    quote_id=accepted.id,
                    expected_quote_revision=accepted.revision,
                ),
                idempotency_key=f"order-{uuid.uuid4().hex}",
            )

        with pytest.raises(IntegrityError):
            async with session_factory() as session, session.begin():
                session.add(
                    AgencyOrderReview(
                        agency_id=other_agency_id,
                        order_id=order.id,
                        status="pending",
                        order_revision=order.revision,
                        payload_hash=order.payload_hash,
                        total_amount=order.total_amount,
                        currency=order.currency,
                        requested_by_user_id=actors.customer_id,
                    )
                )
                await session.flush()

        async with session_factory() as session:
            event_id = (
                await session.execute(
                    select(AgencyOrderEvent.id).where(
                        AgencyOrderEvent.order_id == order.id
                    )
                )
            ).scalar_one()

        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE agency_order_event "
                        "SET event_type = 'tampered' WHERE id = :event_id"
                    ),
                    {"event_id": event_id},
                )

        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM agency_order_event WHERE id = :event_id"),
                    {"event_id": event_id},
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_idempotency_revision_and_event_sequence(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.agency.order_review_service import AgencyOrderReviewService
    from app.models.agency_order_review import AgencyOrderReview
    from app.models.agency_transaction import (
        AgencyOrder,
        AgencyOrderEvent,
        AgencyQuote,
        IdempotencyRecord,
    )
    from app.schemas.agency_transaction import AgencyOrderCreateRequest

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        create_key = f"concurrent-quote-{uuid.uuid4().hex}"
        quote_data = _quote_request(actors)

        async def create_quote(session: AsyncSession):
            return await AgencyOrderReviewService(session).create_quote(
                actor_user_id=actors.advisor_id,
                data=quote_data,
                idempotency_key=create_key,
            )

        create_results = await asyncio.wait_for(
            asyncio.gather(
                _transaction_call(session_factory, create_quote),
                _transaction_call(session_factory, create_quote),
            ),
            timeout=20,
        )
        assert [status for status, _ in create_results] == ["ok", "ok"]
        quote_ids = {result.id for _, result in create_results}
        assert len(quote_ids) == 1
        quote_id = quote_ids.pop()

        async def issue_quote(session: AsyncSession, key: str):
            return await AgencyOrderReviewService(session).issue_quote(
                actor_user_id=actors.advisor_id,
                quote_id=quote_id,
                expected_revision=1,
                idempotency_key=key,
            )

        issue_results = await asyncio.wait_for(
            asyncio.gather(
                _transaction_call(
                    session_factory,
                    lambda session: issue_quote(
                        session,
                        f"issue-a-{uuid.uuid4().hex}",
                    ),
                ),
                _transaction_call(
                    session_factory,
                    lambda session: issue_quote(
                        session,
                        f"issue-b-{uuid.uuid4().hex}",
                    ),
                ),
            ),
            timeout=20,
        )
        assert sorted(status for status, _ in issue_results) == ["conflict", "ok"]
        assert [
            result
            for status, result in issue_results
            if status == "conflict"
        ] == ["transaction_revision_conflict"]

        async with session_factory() as session, session.begin():
            service = AgencyOrderReviewService(session)
            accepted = await service.accept_quote(
                actor_user_id=actors.customer_id,
                quote_id=quote_id,
                expected_revision=2,
                idempotency_key=f"accept-{uuid.uuid4().hex}",
            )
            order = await service.create_order(
                actor_user_id=actors.customer_id,
                data=AgencyOrderCreateRequest(
                    agency_id=actors.agency_id,
                    quote_id=quote_id,
                    expected_quote_revision=accepted.revision,
                ),
                idempotency_key=f"order-{uuid.uuid4().hex}",
            )

        submit_key = f"submit-{uuid.uuid4().hex}"

        async def submit_order(session: AsyncSession):
            return await AgencyOrderReviewService(session).submit_order(
                actor_user_id=actors.customer_id,
                order_id=order.id,
                expected_revision=1,
                idempotency_key=submit_key,
            )

        submit_results = await asyncio.wait_for(
            asyncio.gather(
                _transaction_call(session_factory, submit_order),
                _transaction_call(session_factory, submit_order),
            ),
            timeout=20,
        )
        assert [status for status, _ in submit_results] == ["ok", "ok"]
        assert {result.id for _, result in submit_results} == {order.id}

        approve_key = f"review-approve-{uuid.uuid4().hex}"
        reject_key = f"review-reject-{uuid.uuid4().hex}"

        async def decide_review(
            session: AsyncSession,
            *,
            decision: str,
            reason: str | None,
            key: str,
        ):
            return await AgencyOrderReviewService(session).decide_order_review(
                actor_user_id=actors.approver_id,
                order_id=order.id,
                decision=decision,
                expected_revision=2,
                reason=reason,
                idempotency_key=key,
            )

        decision_results = await asyncio.wait_for(
            asyncio.gather(
                _transaction_call(
                    session_factory,
                    lambda session: decide_review(
                        session,
                        decision="approve",
                        reason=None,
                        key=approve_key,
                    ),
                ),
                _transaction_call(
                    session_factory,
                    lambda session: decide_review(
                        session,
                        decision="reject",
                        reason="库存变化，需要重新报价",
                        key=reject_key,
                    ),
                ),
            ),
            timeout=20,
        )
        assert sorted(status for status, _ in decision_results) == [
            "conflict",
            "ok",
        ]
        assert [
            result
            for status, result in decision_results
            if status == "conflict"
        ] == ["transaction_revision_conflict"]

        async with session_factory() as session:
            stored_quote = await session.get(AgencyQuote, quote_id)
            stored_order = await session.get(AgencyOrder, order.id)
            stored_review = (
                await session.execute(
                    select(AgencyOrderReview).where(
                        AgencyOrderReview.order_id == order.id
                    )
                )
            ).scalar_one()
            events = list(
                (
                    await session.execute(
                        select(AgencyOrderEvent)
                        .where(AgencyOrderEvent.order_id == order.id)
                        .order_by(AgencyOrderEvent.event_sequence)
                    )
                )
                .scalars()
                .all()
            )
            completed_submit_records = (
                await session.execute(
                    select(func.count())
                    .select_from(IdempotencyRecord)
                    .where(IdempotencyRecord.agency_id == actors.agency_id)
                    .where(IdempotencyRecord.scope == "order.submit")
                    .where(IdempotencyRecord.key == submit_key)
                    .where(IdempotencyRecord.status == "completed")
                )
            ).scalar_one()
            completed_decision_records = (
                await session.execute(
                    select(func.count())
                    .select_from(IdempotencyRecord)
                    .where(IdempotencyRecord.agency_id == actors.agency_id)
                    .where(IdempotencyRecord.scope == "order.review.decide")
                    .where(IdempotencyRecord.key.in_([approve_key, reject_key]))
                    .where(IdempotencyRecord.status == "completed")
                )
            ).scalar_one()

        assert stored_quote is not None
        assert (stored_quote.status, stored_quote.revision) == ("accepted", 3)
        assert stored_order is not None
        expected_order_status = {
            "approved": "approved",
            "rejected": "review_rejected",
        }[stored_review.status]
        assert (stored_order.status, stored_order.revision) == (
            expected_order_status,
            3,
        )
        assert stored_review.order_revision == 2
        assert stored_review.decision_order_revision == 3
        assert stored_review.decided_by_user_id == actors.approver_id
        assert stored_review.status in {"approved", "rejected"}
        if stored_review.status == "rejected":
            assert stored_review.decision_reason
        assert [
            (event.event_sequence, event.order_revision, event.event_type)
            for event in events
        ] == [
            (1, 1, "order_created"),
            (2, 2, "order_submitted"),
            (3, 3, f"order_review_{stored_review.status}"),
        ]
        assert sum(
            event.event_type in {"order_review_approved", "order_review_rejected"}
            for event in events
        ) == 1
        assert completed_submit_records == 1
        assert completed_decision_records == 1

        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE agency_order_review "
                        "SET total_amount = total_amount + 1 "
                        "WHERE id = :review_id"
                    ),
                    {"review_id": stored_review.id},
                )

        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "DELETE FROM agency_order_review "
                        "WHERE id = :review_id"
                    ),
                    {"review_id": stored_review.id},
                )
    finally:
        await engine.dispose()
