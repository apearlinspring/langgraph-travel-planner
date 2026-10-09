import json

from scripts import collect_m1_runtime_probe_metrics as metrics


def _passing_probe(**kwargs):
    latency = 12.0 if kwargs["label"] == "live" else 18.0
    return metrics.ProbeSample(
        endpoint=kwargs["label"],
        status="passed",
        http_status=200,
        latency_ms=latency,
        finding="ok",
    )


def test_m1_runtime_probe_metrics_passes_and_redacts_target():
    report = metrics.build_m1_runtime_probe_metrics_report(
        base_url="http://127.0.0.1:8000",
        allow_local_base_url=True,
        sample_count=3,
        probe_func=_passing_probe,
    )
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "passed"
    assert report["endpoint_summaries"]["live"]["sample_count"] == 3
    assert report["endpoint_summaries"]["ready"]["error_rate"] == 0
    assert report["declaration_statuses"] == {
        "ZHIXING_ERROR_RATE_MONITOR_STATUS": "passed",
        "ZHIXING_P95_LATENCY_MONITOR_STATUS": "passed",
    }
    assert "127.0.0.1:8000" not in payload


def test_m1_runtime_probe_metrics_blocks_error_rate():
    calls = {"count": 0}

    def flaky_probe(**kwargs):
        calls["count"] += 1
        if kwargs["label"] == "ready" and calls["count"] % 2 == 0:
            return metrics.ProbeSample(
                endpoint=kwargs["label"],
                status="failed",
                http_status=503,
                latency_ms=10.0,
                finding="failed",
            )
        return _passing_probe(**kwargs)

    report = metrics.build_m1_runtime_probe_metrics_report(
        base_url="https://example.com",
        sample_count=2,
        max_error_rate=0,
        probe_func=flaky_probe,
    )

    assert report["status"] == "blocked"
    assert report["declaration_statuses"]["ZHIXING_ERROR_RATE_MONITOR_STATUS"] == "blocked"
    assert any(item["metric"] == "error_rate" for item in report["blocked_reasons"])


def test_m1_runtime_probe_metrics_degrades_slow_p95():
    def slow_probe(**kwargs):
        return metrics.ProbeSample(
            endpoint=kwargs["label"],
            status="passed",
            http_status=200,
            latency_ms=1500.0,
            finding="slow",
        )

    report = metrics.build_m1_runtime_probe_metrics_report(
        base_url="https://example.com",
        sample_count=2,
        max_p95_ms=1000,
        probe_func=slow_probe,
    )

    assert report["status"] == "degraded"
    assert report["declaration_statuses"]["ZHIXING_P95_LATENCY_MONITOR_STATUS"] == "degraded"
    assert any(item["metric"] == "p95_latency_ms" for item in report["degraded_reasons"])


def test_m1_runtime_probe_metrics_rejects_repo_output_path():
    report = {
        "checks": {
            "output": metrics._validate_output_path(
                str(metrics.PROJECT_ROOT / "m1-runtime-probe.json")
            )
        }
    }

    assert report["checks"]["output"]["status"] == "blocked"
    assert "outside the Git workspace" in report["checks"]["output"]["finding"]
