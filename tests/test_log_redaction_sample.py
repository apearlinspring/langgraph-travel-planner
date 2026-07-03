import json

from scripts import check_log_redaction_sample as log_redaction


def test_log_redaction_sample_passes_clean_logs():
    report = log_redaction.build_log_redaction_sample_report(
        text="\n".join(
            [
                "backend ready status=200 elapsed_ms=12",
                "token_count=42 estimated_total_tokens=128",
            ]
        )
    )

    assert report["status"] == "passed"
    assert report["line_count"] == 2
    assert report["finding_count"] == 0
    assert report["declaration_statuses"]["ZHIXING_LOG_REDACTION_SAMPLE_STATUS"] == "passed"


def test_log_redaction_sample_blocks_sensitive_shapes_without_echoing_raw_text():
    raw = "\n".join(
        [
            "GET https://mcp.example.test/path?key=amap-secret-1234567890",
            "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
            "customer phone 13800138000",
        ]
    )

    report = log_redaction.build_log_redaction_sample_report(text=raw)
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "blocked"
    assert report["finding_count"] >= 3
    assert report["category_counts"]["url_query_secret"] == 1
    assert report["category_counts"]["bearer_token"] == 1
    assert report["category_counts"]["phone"] == 1
    assert "amap-secret-1234567890" not in payload
    assert "abcdefghijklmnopqrstuvwxyz" not in payload
    assert "13800138000" not in payload


def test_log_redaction_sample_detects_secret_assignment_and_email():
    report = log_redaction.build_log_redaction_sample_report(
        text="password=supersecret user=a@example.com"
    )

    assert report["status"] == "blocked"
    assert report["category_counts"]["secret_assignment"] == 1
    assert report["category_counts"]["email"] == 1
