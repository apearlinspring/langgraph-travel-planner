import importlib.util
import re
from pathlib import Path

from app.models import _20260730_0006_customer_claim_trigger_fix_frozen as frozen


ROOT = Path(__file__).resolve().parents[1]
REVISION_PATH = (
    ROOT / "alembic/versions/20260730_0006_customer_claim_trigger_fix.py"
)


class _OperationRecorder:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: object) -> None:
        self.statements.append(str(statement))


def _load_revision():
    spec = importlib.util.spec_from_file_location(
        "agency_customer_claim_trigger_fix_revision",
        REVISION_PATH,
    )
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return revision


def test_0006_revision_uses_frozen_helper_contract():
    revision = _load_revision()

    assert revision.revision == "20260730_0006"
    assert revision.down_revision == "20260730_0005"
    assert revision._upgrade_customer_claim_trigger_fix.__module__ == (
        "app.models._20260730_0006_customer_claim_trigger_fix_frozen"
    )
    assert "Revision-frozen" in (frozen.__doc__ or "")


def test_0006_guards_table_specific_new_fields_inside_table_branch(monkeypatch):
    recorder = _OperationRecorder()
    monkeypatch.setattr(frozen, "op", recorder)

    frozen.upgrade_customer_claim_trigger_fix()
    sql = "\n".join(recorder.statements)

    assert sql.count("CREATE CONSTRAINT TRIGGER") == 3
    assert "IF TG_TABLE_NAME = 'agency_customer_invitation' THEN" in sql
    assert "NEW.target_user_id" in sql
    assert "NEW.customer_revision" in sql
    assert not re.search(
        r"IF TG_TABLE_NAME = 'agency_customer_invitation'\s+AND NEW\.",
        sql,
    )
