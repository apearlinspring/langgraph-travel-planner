"""Initial business schema."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260511_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEGACY_BUSINESS_TABLES = {"user", "conversation", "message"}


def _bootstrap_legacy_create_all_schema() -> bool:
    """Adopt databases that already have legacy business tables but no revision."""

    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    if not (_LEGACY_BUSINESS_TABLES & existing_tables):
        return False

    import app.models  # noqa: F401
    from app.models.base import Base

    Base.metadata.create_all(bind=bind, checkfirst=True)
    return True


def upgrade() -> None:
    if _bootstrap_legacy_create_all_schema():
        return

    op.create_table(
        "user",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("preferences", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_email"), "user", ["email"], unique=True)
    op.create_index(op.f("ix_user_username"), "user", ["username"], unique=True)

    op.create_table(
        "conversation",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("extra_info", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_conversation_status"), "conversation", ["status"], unique=False)
    op.create_index(op.f("ix_conversation_user_id"), "conversation", ["user_id"], unique=False)

    op.create_table(
        "message",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("extra_info", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_message_conversation_id"), "message", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_message_created_at"), "message", ["created_at"], unique=False)
    op.create_index(op.f("ix_message_role"), "message", ["role"], unique=False)

    op.create_table(
        "approval_request",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_id", sa.String(length=40), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=True),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("is_blocking", sa.Boolean(), nullable=False),
        sa.Column("governance_boundary", sa.Text(), nullable=False),
        sa.Column("unsupported_without_integration", sa.JSON(), nullable=False),
        sa.Column("request_metadata", sa.JSON(), nullable=False),
        sa.Column("decided_by", sa.String(length=64), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_approval_request_action"), "approval_request", ["action"], unique=False)
    op.create_index(
        op.f("ix_approval_request_approval_id"),
        "approval_request",
        ["approval_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_approval_request_conversation_id"),
        "approval_request",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_approval_request_created_at"),
        "approval_request",
        ["created_at"],
        unique=False,
    )
    op.create_index(op.f("ix_approval_request_status"), "approval_request", ["status"], unique=False)
    op.create_index(op.f("ix_approval_request_user_id"), "approval_request", ["user_id"], unique=False)

    op.create_table(
        "approval_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_id", sa.String(length=40), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("event_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_approval_event_action"), "approval_event", ["action"], unique=False)
    op.create_index(
        "ix_approval_event_approval_created",
        "approval_event",
        ["approval_id", "created_at"],
        unique=False,
    )
    op.create_index(op.f("ix_approval_event_approval_id"), "approval_event", ["approval_id"], unique=False)
    op.create_index(op.f("ix_approval_event_actor_id"), "approval_event", ["actor_id"], unique=False)
    op.create_index(op.f("ix_approval_event_created_at"), "approval_event", ["created_at"], unique=False)
    op.create_index(op.f("ix_approval_event_event_type"), "approval_event", ["event_type"], unique=False)
    op.create_index(op.f("ix_approval_event_to_status"), "approval_event", ["to_status"], unique=False)

    op.create_table(
        "tool_audit_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("conversation_id", sa.String(length=64), nullable=True),
        sa.Column("tool_call_id", sa.String(length=120), nullable=True),
        sa.Column("approval_id", sa.String(length=40), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("elapsed_seconds", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("input_summary", sa.JSON(), nullable=False),
        sa.Column("output_summary", sa.JSON(), nullable=False),
        sa.Column("error_type", sa.String(length=120), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("evidence_type", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_tool_audit_event_approval_id"),
        "tool_audit_event",
        ["approval_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_audit_event_conversation_id"),
        "tool_audit_event",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_audit_event_created_at"),
        "tool_audit_event",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_audit_event_evidence_type"),
        "tool_audit_event",
        ["evidence_type"],
        unique=False,
    )
    op.create_index(op.f("ix_tool_audit_event_name"), "tool_audit_event", ["name"], unique=False)
    op.create_index(
        "ix_tool_audit_name_status",
        "tool_audit_event",
        ["name", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_audit_event_started_at"),
        "tool_audit_event",
        ["started_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_audit_event_status"),
        "tool_audit_event",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_audit_event_tool_call_id"),
        "tool_audit_event",
        ["tool_call_id"],
        unique=False,
    )
    op.create_index(
        "ix_tool_audit_user_conversation",
        "tool_audit_event",
        ["user_id", "conversation_id"],
        unique=False,
    )
    op.create_index(op.f("ix_tool_audit_event_user_id"), "tool_audit_event", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tool_audit_event_user_id"), table_name="tool_audit_event")
    op.drop_index("ix_tool_audit_user_conversation", table_name="tool_audit_event")
    op.drop_index(op.f("ix_tool_audit_event_tool_call_id"), table_name="tool_audit_event")
    op.drop_index(op.f("ix_tool_audit_event_status"), table_name="tool_audit_event")
    op.drop_index(op.f("ix_tool_audit_event_started_at"), table_name="tool_audit_event")
    op.drop_index("ix_tool_audit_name_status", table_name="tool_audit_event")
    op.drop_index(op.f("ix_tool_audit_event_name"), table_name="tool_audit_event")
    op.drop_index(op.f("ix_tool_audit_event_evidence_type"), table_name="tool_audit_event")
    op.drop_index(op.f("ix_tool_audit_event_created_at"), table_name="tool_audit_event")
    op.drop_index(op.f("ix_tool_audit_event_conversation_id"), table_name="tool_audit_event")
    op.drop_index(op.f("ix_tool_audit_event_approval_id"), table_name="tool_audit_event")
    op.drop_table("tool_audit_event")

    op.drop_index(op.f("ix_approval_event_to_status"), table_name="approval_event")
    op.drop_index(op.f("ix_approval_event_event_type"), table_name="approval_event")
    op.drop_index(op.f("ix_approval_event_created_at"), table_name="approval_event")
    op.drop_index(op.f("ix_approval_event_actor_id"), table_name="approval_event")
    op.drop_index(op.f("ix_approval_event_approval_id"), table_name="approval_event")
    op.drop_index("ix_approval_event_approval_created", table_name="approval_event")
    op.drop_index(op.f("ix_approval_event_action"), table_name="approval_event")
    op.drop_table("approval_event")

    op.drop_index(op.f("ix_approval_request_user_id"), table_name="approval_request")
    op.drop_index(op.f("ix_approval_request_status"), table_name="approval_request")
    op.drop_index(op.f("ix_approval_request_created_at"), table_name="approval_request")
    op.drop_index(op.f("ix_approval_request_conversation_id"), table_name="approval_request")
    op.drop_index(op.f("ix_approval_request_approval_id"), table_name="approval_request")
    op.drop_index(op.f("ix_approval_request_action"), table_name="approval_request")
    op.drop_table("approval_request")

    op.drop_index(op.f("ix_message_role"), table_name="message")
    op.drop_index(op.f("ix_message_created_at"), table_name="message")
    op.drop_index(op.f("ix_message_conversation_id"), table_name="message")
    op.drop_table("message")

    op.drop_index(op.f("ix_conversation_user_id"), table_name="conversation")
    op.drop_index(op.f("ix_conversation_status"), table_name="conversation")
    op.drop_table("conversation")

    op.drop_index(op.f("ix_user_username"), table_name="user")
    op.drop_index(op.f("ix_user_email"), table_name="user")
    op.drop_table("user")
