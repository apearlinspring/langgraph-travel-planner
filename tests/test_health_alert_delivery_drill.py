import json

from scripts import run_health_alert_delivery_drill as drill


def test_health_alert_delivery_drill_writes_file_sink(monkeypatch, tmp_path):
    def fake_probe(**kwargs):
        return drill.ProbeResult(
            label=kwargs["label"],
            path=kwargs["path"],
            status="passed",
            http_status=200,
            finding="ok",
        )

    monkeypatch.setattr(drill, "_probe_endpoint", fake_probe)
    sink_file = tmp_path / "alerts" / "drill.jsonl"

    report = drill.build_health_alert_delivery_drill_report(
        base_url="http://127.0.0.1:8000",
        sink_file=str(sink_file),
        allow_local_base_url=True,
    )
    payload = json.dumps(report, ensure_ascii=False)
    lines = sink_file.read_text(encoding="utf-8").splitlines()

    assert report["status"] == "passed"
    assert report["delivery"]["delivered_events"] == 2
    assert report["declaration_statuses"] == {
        "ZHIXING_HEALTH_ALERT_DELIVERY_STATUS": "passed",
        "ZHIXING_READINESS_ALERT_DELIVERY_STATUS": "passed",
    }
    assert len(lines) == 2
    assert str(sink_file) not in payload
    assert "127.0.0.1:8000" not in payload


def test_health_alert_delivery_drill_blocks_missing_sink_file(monkeypatch):
    def fake_probe(**kwargs):
        raise AssertionError("probe should not run when sink is missing")

    monkeypatch.setattr(drill, "_probe_endpoint", fake_probe)

    report = drill.build_health_alert_delivery_drill_report(
        base_url="https://example.com",
        sink_file="",
    )

    assert report["status"] == "blocked"
    assert report["delivery"]["status"] == "not_checked"
    assert any(item["finding"] == "Missing alert sink file path." for item in report["blocked_reasons"])


def test_health_alert_delivery_drill_rejects_workspace_sink(tmp_path):
    sink_file = drill.PROJECT_ROOT / "alert-drill.jsonl"

    report = drill.build_health_alert_delivery_drill_report(
        base_url="https://example.com",
        sink_file=str(sink_file),
    )

    assert report["status"] == "blocked"
    assert any("outside the Git workspace" in item["finding"] for item in report["blocked_reasons"])
