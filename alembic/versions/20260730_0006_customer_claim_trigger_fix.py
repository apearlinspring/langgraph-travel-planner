"""Fix table-specific NEW field access in customer consistency triggers."""

from typing import Sequence, Union

from app.models._20260730_0006_customer_claim_trigger_fix_frozen import (
    downgrade_customer_claim_trigger_fix as _downgrade_customer_claim_trigger_fix,
    upgrade_customer_claim_trigger_fix as _upgrade_customer_claim_trigger_fix,
)


revision: str = "20260730_0006"
down_revision: Union[str, None] = "20260730_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    _upgrade_customer_claim_trigger_fix()


def downgrade() -> None:
    _downgrade_customer_claim_trigger_fix()
