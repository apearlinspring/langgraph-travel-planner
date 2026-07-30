"""Add secure customer invitations, claims and consent evidence."""

from typing import Sequence, Union

from app.models._20260730_0005_agency_customer_invitation_claim_frozen import (
    downgrade_invitation_claim_schema as _downgrade_invitation_claim_schema,
    upgrade_invitation_claim_schema as _upgrade_invitation_claim_schema,
)


revision: str = "20260730_0005"
down_revision: Union[str, None] = "20260726_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    _upgrade_invitation_claim_schema()


def downgrade() -> None:
    _downgrade_invitation_claim_schema()
