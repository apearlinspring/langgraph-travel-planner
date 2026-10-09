import json

from scripts import check_production_image_build_execution_record as build_record


def _valid_record():
    return {
        "record_version": build_record.PRODUCTION_IMAGE_BUILD_EXECUTION_RECORD_VERSION,
        "build_id": "production-image-build-20260703-private",
        "mode": "remote_background_build",
        "started_at": "2026-07-03T03:00:00+08:00",
        "ended_at": "2026-07-03T03:18:00+08:00",
        "duration_seconds": 1080,
        "release_label": "private-release-label",
        "build_reason": "private runtime dependency split verification",
        "owners": {
            "build_owner": "alice private build owner",
            "release_owner": "bob private release owner",
            "verifier": "carol private verifier",
        },
        "background_execution": {
            "wrapper": "nohup",
            "timeout_seconds": 1800,
            "pid_recorded": "passed",
            "log_path_recorded": "passed",
            "log_redacted": "passed",
            "started_in_background": "passed",
            "exit_code_recorded": "passed",
            "exit_code": 0,
            "timed_out": False,
        },
        "package_mirror": {
            "pip_index_url_configured": "passed",
            "pip_trusted_host_policy_recorded": "passed",
            "mirror_used_recorded": "passed",
            "secret_values_in_url": False,
            "mirror_failure_policy": "retry configured mirror; fallback requires operator note",
        },
        "runtime_input": {
            "runtime_requirements_used": "passed",
            "dockerfile_runtime_input_verified": "passed",
            "runtime_dependency_scope_passed": "passed",
            "full_requirements_used": False,
            "dev_dependencies_installed": False,
            "optional_gpu_stack_installed": False,
        },
        "image_evidence": {
            "image_id_before_present": "passed",
            "image_id_after_present": "passed",
            "image_changed": True,
            "image_size_recorded": "passed",
            "image_size_mb_after": 1400,
        },
        "safety": {
            "disk_guard_passed": "passed",
            "current_release_unchanged_until_success": "passed",
            "no_runtime_data_modified": "passed",
            "used_docker_system_prune": False,
            "deleted_docker_volume": False,
            "deleted_env_file": False,
            "deleted_vectorstore": False,
            "deleted_backup": False,
            "used_bulk_delete": False,
        },
        "post_build_verification": {
            "compose_ps_status": "passed",
            "health_live_status": "passed",
            "health_ready_status": "passed",
            "mock_checkout_status": "not_applicable",
            "mock_checkout_reason": "Image build scoped to runtime health.",
        },
        "redaction_boundary": {
            "raw_logs_included": False,
            "raw_urls_included": False,
            "ssh_target_included": False,
            "deploy_dir_included": False,
            "secret_values_included": False,
            "customer_pii_included": False,
        },
    }


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def test_valid_production_image_build_execution_record_passes_without_echoing_private_text():
    report = build_record.build_production_image_build_execution_record_report(_valid_record())
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["declaration_statuses"] == {
        "ZHIXING_PRODUCTION_IMAGE_BUILD_EXECUTION_STATUS": "passed",
        "ZHIXING_PRODUCTION_IMAGE_RUNTIME_INPUT_STATUS": "passed",
        "ZHIXING_PRODUCTION_IMAGE_EVIDENCE_STATUS": "passed",
        "ZHIXING_PRODUCTION_IMAGE_SAFETY_STATUS": "passed",
        "ZHIXING_PRODUCTION_IMAGE_POST_BUILD_HEALTH_STATUS": "passed",
    }
    assert "alice private build owner" not in payload
    assert "private-release-label" not in payload
    assert "private runtime dependency split verification" not in payload
    assert report["policy"]["record_text_echoed"] is False


def test_missing_background_execution_blocks_execution_status():
    record = _valid_record()
    record["background_execution"]["started_in_background"] = "pending"

    report = build_record.build_production_image_build_execution_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["background_execution"]["status"] == "blocked"
    assert (
        report["declaration_statuses"]["ZHIXING_PRODUCTION_IMAGE_BUILD_EXECUTION_STATUS"]
        == "blocked"
    )


def test_full_requirements_runtime_input_blocks_runtime_status():
    record = _valid_record()
    record["runtime_input"]["full_requirements_used"] = True

    report = build_record.build_production_image_build_execution_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["runtime_input"]["status"] == "blocked"
    assert (
        report["declaration_statuses"]["ZHIXING_PRODUCTION_IMAGE_RUNTIME_INPUT_STATUS"]
        == "blocked"
    )


def test_docker_system_prune_blocks_safety_status():
    record = _valid_record()
    record["safety"]["used_docker_system_prune"] = True

    report = build_record.build_production_image_build_execution_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["safety"]["status"] == "blocked"
    assert (
        report["declaration_statuses"]["ZHIXING_PRODUCTION_IMAGE_SAFETY_STATUS"]
        == "blocked"
    )


def test_missing_health_ready_blocks_post_build_health_status():
    record = _valid_record()
    record["post_build_verification"]["health_ready_status"] = "blocked"

    report = build_record.build_production_image_build_execution_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["post_build_verification"]["status"] == "blocked"
    assert (
        report["declaration_statuses"]["ZHIXING_PRODUCTION_IMAGE_POST_BUILD_HEALTH_STATUS"]
        == "blocked"
    )


def test_secret_like_value_blocks_record_and_is_not_echoed():
    record = _valid_record()
    raw_text = json.dumps(record, ensure_ascii=False) + "\napi_key=private-secret-token-123456"

    report = build_record.build_production_image_build_execution_record_report(record, raw_text=raw_text)
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert report["checks"]["redaction_boundary"]["status"] == "blocked"
    assert "private-secret-token-123456" not in payload


def test_template_contains_remote_background_build_sections():
    template = build_record._template_record()

    assert template["mode"] == "remote_background_build"
    assert "background_execution" in template
    assert "runtime_input" in template
    assert "image_evidence" in template
    assert "post_build_verification" in template


def test_template_placeholders_do_not_validate_as_real_record():
    template = build_record._template_record()

    report = build_record.build_production_image_build_execution_record_report(template)

    assert report["status"] == "blocked"
    assert report["checks"]["required_fields"]["status"] == "blocked"
    assert report["checks"]["owners"]["status"] == "blocked"
