"""Add the fail-closed agency order cancellation workflow."""

from typing import Sequence, Union

from app.models._20260730_0007_agency_cancellation_workflow_frozen import (
    downgrade_agency_cancellation_workflow as _downgrade,
    upgrade_agency_cancellation_workflow as _upgrade,
)


revision: str = "20260730_0007"
down_revision: Union[str, None] = "20260730_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    _upgrade()


def downgrade() -> None:
    _downgrade()
