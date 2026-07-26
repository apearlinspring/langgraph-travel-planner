"""Database migration ownership boundaries."""

BUSINESS_MANAGED_TABLES: tuple[str, ...] = (
    "user",
    "conversation",
    "message",
    "approval_request",
    "approval_event",
    "tool_audit_event",
    "agency",
    "agency_membership",
    "agency_customer",
    "supplier_product",
    "agency_quote",
    "agency_order",
    "agency_order_event",
    "agency_order_review",
    "idempotency_record",
    "payment_attempt",
    "fulfillment_record",
)

LANGGRAPH_CHECKPOINT_TABLES: tuple[str, ...] = (
    "checkpoint_migrations",
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
)

LANGGRAPH_STORE_TABLES: tuple[str, ...] = (
    "store_migrations",
    "store",
    "vector_migrations",
    "store_vectors",
)

EXTERNALLY_MANAGED_DATABASE_OBJECTS: tuple[str, ...] = (
    *LANGGRAPH_CHECKPOINT_TABLES,
    *LANGGRAPH_STORE_TABLES,
    "vector extension",
)
