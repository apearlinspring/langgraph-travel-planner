import json
import subprocess

from scripts import collect_m1_smoke_evidence as smoke


PUBLIC_URL = "https://m1.zhixing.com"


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def test_default_smoke_evidence_is_plan_only_and_redacted():
    report = smoke.build_m1_smoke_evidence_report(
        environ={},
        base_url=PUBLIC_URL,
    )
    payload = _payload_text(report)

    assert report["status"] == "not_checked"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["network_probe_requested"] is False
    assert report["policy"]["runs_acceptance_smoke"] is False
    assert report["sections"] == {}
    assert "<public-url>" in payload
    assert PUBLIC_URL not in payload


def test_health_probe_blocks_localhost_without_network_call():
    calls = []

    def fake_probe(url, *, timeout_seconds):
        calls.append(url)
        return 200

    report = smoke.build_m1_smoke_evidence_report(
        environ={},
        base_url="http://127.0.0.1:8000",
        check_health_url=True,
        probe_url=fake_probe,
    )

    assert report["status"] == "blocked"
    assert report["sections"]["public_health"]["status"] == "blocked"
    assert calls == []
    assert "127.0.0.1" not in _payload_text(report)


def test_health_probe_passes_without_echoing_public_url():
    calls = []

    def fake_probe(url, *, timeout_seconds):
        calls.append(url)
        return 200

    report = smoke.build_m1_smoke_evidence_report(
        environ={},
        base_url=PUBLIC_URL,
        check_health_url=True,
        probe_url=fake_probe,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["sections"]["public_health"]["status"] == "passed"
    assert len(calls) == 2
    assert all(call.startswith(PUBLIC_URL) for call in calls)
    assert PUBLIC_URL not in payload


def test_run_gate_embeds_redacted_gate_report(monkeypatch):
    captured = {}

    def fake_gate(**kwargs):
        captured.update(kwargs)
        return {
            "status": "passed",
            "base_url": kwargs["base_url"],
            "section_statuses": {"runtime_readiness": "passed"},
        }

    monkeypatch.setattr(smoke, "build_m1_deployment_gate_report", fake_gate)

    report = smoke.build_m1_smoke_evidence_report(
        environ={"ZHIXING_PUBLIC_BASE_URL": PUBLIC_URL},
        run_gate=True,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert captured["include_acceptance"] is True
    assert captured["check_backend"] is True
    assert captured["check_server_docker"] is True
    assert captured["check_server_deploy_dir"] is True
    assert captured["check_server_disk"] is True
    assert captured["check_server_health_url"] is False
    assert report["sections"]["m1_deployment_gate"]["report"]["base_url"] == "<public-url>"
    assert PUBLIC_URL not in payload


def test_run_acceptance_smoke_summarizes_json_without_raw_payload():
    calls = []

    def fake_runner(args, *, timeout_seconds):
        calls.append(list(args))
        stdout = json.dumps(
            {
                "status": "passed",
                "passed": True,
                "preflight": {"status": "passed"},
                "acceptance_summary": {
                    "selected_count": 2,
                    "result_count": 2,
                    "base_url": PUBLIC_URL,
                },
                "blocking_reasons": [],
                "failure_classification_counts": {},
            }
        )
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    report = smoke.build_m1_smoke_evidence_report(
        environ={},
        base_url=PUBLIC_URL,
        run_acceptance_smoke=True,
        command_runner=fake_runner,
    )
    section = report["sections"]["acceptance_smoke"]
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert section["status"] == "passed"
    assert section["summary"]["selected_count"] == 2
    assert section["summary"]["result_count"] == 2
    assert section["summary"]["raw_payload_included"] is False
    assert calls and PUBLIC_URL in calls[0]
    assert PUBLIC_URL not in payload


def test_run_acceptance_smoke_failure_redacts_output():
    def fake_runner(args, *, timeout_seconds):
        return subprocess.CompletedProcess(
            args,
            2,
            stdout=f"not json from {PUBLIC_URL}\n",
            stderr="API_KEY=secret-value\n",
        )

    report = smoke.build_m1_smoke_evidence_report(
        environ={},
        base_url=PUBLIC_URL,
        run_acceptance_smoke=True,
        command_runner=fake_runner,
    )
    section = report["sections"]["acceptance_smoke"]
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert section["status"] == "blocked"
    assert PUBLIC_URL not in payload
    assert "secret-value" not in payload
    assert "<public-url>" in section["stdout_first_line"]
    assert "[REDACTED]" in section["stderr_first_line"]


def test_smoke_evidence_markdown_keeps_boundary_and_sections():
    report = smoke.build_m1_smoke_evidence_report(
        environ={},
        base_url=PUBLIC_URL,
    )

    markdown = smoke.build_m1_smoke_evidence_markdown(report)

    assert "M1 Smoke Evidence" in markdown
    assert "Section 状态" in markdown
    assert "Plan-only mode proves no deployment result" in markdown
    assert PUBLIC_URL not in markdown
