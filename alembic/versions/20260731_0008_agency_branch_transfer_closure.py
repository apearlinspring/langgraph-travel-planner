"""Add agency customer branch transfer and branch closure governance."""

from typing import Sequence, Union

from app.models._20260731_0008_agency_branch_transfer_closure_frozen import (
    downgrade_agency_branch_transfer_closure as _downgrade,
    upgrade_agency_branch_transfer_closure as _upgrade,
)


revision: str = "20260731_0008"
down_revision: Union[str, None] = "20260730_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    _upgrade()


def downgrade() -> None:
    _downgrade()
