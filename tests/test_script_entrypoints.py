import asyncio
import importlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    "script_name",
    (
        "check_concurrency_rate_limit_evidence_record.py",
        "check_external_dependency_resilience_record.py",
        "check_postgres_redis_recovery_record.py",
        "check_m1_rollout_execution_record.py",
        "check_m1_operations_review_record.py",
        "check_production_image_build_execution_record.py",
        "check_rollback_execution_record.py",
        "check_incident_tabletop_status.py",
        "check_disk_remediation_approval.py",
        "check_docker_build_cache_cleanup_approval.py",
        "check_live_chat_concurrency_probe_approval.py",
        "check_live_chat_probe_execution_approval.py",
        "check_restore_drill_feasibility.py",
        "collect_backup_schedule_live_probe.py",
        "collect_docker_build_cache_cleanup_plan.py",
        "collect_docker_disk_cleanup_plan.py",
        "collect_live_server_probe.py",
        "collect_postgres_redis_live_probe.py",
        "collect_postgres_restore_drill_live_probe.py",
        "collect_server_capacity_snapshot.py",
        "converge_server_shared_env.py",
        "execute_docker_disk_cleanup.py",
        "prepare_production_image_build_execution.py",
    ),
)
def test_refactored_script_runs_as_direct_script(script_name):
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(project_root / "scripts" / script_name), "--help"],
        cwd=project_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()


def test_init_db_script_imports_cleanly():
    module = importlib.import_module("scripts.init_db")
    assert hasattr(module, "init_database")


def test_init_rag_script_imports_cleanly():
    module = importlib.import_module("scripts.init_rag")
    assert hasattr(module, "main")


def test_init_rag_help_does_not_start_initialization():
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(project_root / "scripts" / "init_rag.py"), "--help"],
        cwd=project_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
    assert "开始初始化 RAG 系统" not in result.stdout


def test_validate_rag_knowledge_script_imports_cleanly():
    module = importlib.import_module("scripts.validate_rag_knowledge")
    assert hasattr(module, "main")


def test_runtime_readiness_script_imports_cleanly():
    module = importlib.import_module("scripts.check_runtime_readiness")
    assert hasattr(module, "build_runtime_readiness_report")
    assert hasattr(module, "build_database_migration_readiness_report")
    assert hasattr(module, "build_docker_compose_readiness_report")


def test_runtime_dependency_scope_script_imports_cleanly():
    module = importlib.import_module("scripts.check_runtime_dependency_scope")
    assert hasattr(module, "build_runtime_dependency_scope_report")
    assert hasattr(module, "build_runtime_dependency_scope_markdown")
    assert module.RUNTIME_DEPENDENCY_SCOPE_VERSION == "runtime_dependency_scope.v1"


def test_production_image_build_policy_script_imports_cleanly():
    module = importlib.import_module("scripts.check_production_image_build_policy")
    assert hasattr(module, "build_production_image_build_policy_report")
    assert hasattr(module, "build_production_image_build_policy_markdown")
    assert (
        module.PRODUCTION_IMAGE_BUILD_POLICY_VERSION
        == "production_image_build_policy.v1"
    )


def test_production_image_build_execution_record_script_imports_cleanly():
    module = importlib.import_module("scripts.check_production_image_build_execution_record")
    assert hasattr(module, "build_production_image_build_execution_record_report")
    assert hasattr(module, "build_production_image_build_execution_record_markdown")
    assert (
        module.PRODUCTION_IMAGE_BUILD_EXECUTION_RECORD_VERSION
        == "production_image_build_execution_record.v1"
    )


def test_production_image_build_execution_preparer_imports_cleanly():
    module = importlib.import_module("scripts.prepare_production_image_build_execution")
    assert hasattr(module, "build_production_image_build_execution_prep_report")
    assert hasattr(module, "build_production_image_build_execution_prep_markdown")
    assert (
        module.PRODUCTION_IMAGE_BUILD_EXECUTION_PREP_VERSION
        == "production_image_build_execution_prep.v1"
    )


def test_m1_launch_inputs_script_imports_cleanly():
    module = importlib.import_module("scripts.check_m1_launch_inputs")
    assert hasattr(module, "build_m1_launch_inputs_report")
    assert module.M1_LAUNCH_INPUTS_VERSION == "m1_launch_inputs.v1"


def test_m1_execution_input_gap_script_imports_cleanly():
    module = importlib.import_module("scripts.check_m1_execution_input_gap")
    assert hasattr(module, "build_m1_execution_input_gap_report")
    assert hasattr(module, "build_m1_execution_input_gap_markdown")
    assert module.M1_EXECUTION_INPUT_GAP_VERSION == "m1_execution_input_gap.v1"


def test_m1_private_execution_workspace_preparer_imports_cleanly():
    module = importlib.import_module("scripts.prepare_m1_private_execution_workspace")
    assert hasattr(module, "build_m1_private_execution_workspace_report")
    assert hasattr(module, "build_m1_private_execution_workspace_markdown")
    assert (
        module.M1_PRIVATE_EXECUTION_WORKSPACE_VERSION
        == "m1_private_execution_workspace.v1"
    )


def test_m1_resource_request_renderer_imports_cleanly():
    module = importlib.import_module("scripts.render_m1_resource_request")
    assert hasattr(module, "build_m1_resource_request_report")
    assert hasattr(module, "build_m1_resource_request_markdown")
    assert module.M1_RESOURCE_REQUEST_VERSION == "m1_resource_request.v1"


def test_server_env_checklist_renderer_imports_cleanly():
    module = importlib.import_module("scripts.render_server_env_checklist")
    assert hasattr(module, "build_server_env_checklist_report")
    assert hasattr(module, "build_server_env_checklist_markdown")
    assert module.SERVER_ENV_CHECKLIST_VERSION == "server_env_checklist.v1"


def test_server_env_file_check_script_imports_cleanly():
    module = importlib.import_module("scripts.check_server_env_file")
    assert hasattr(module, "build_server_env_file_check_report")
    assert hasattr(module, "build_server_env_file_check_markdown")
    assert module.SERVER_ENV_FILE_CHECK_VERSION == "server_env_file_check.v1"


def test_m1_first_deploy_dry_run_script_imports_cleanly():
    module = importlib.import_module("scripts.check_m1_first_deploy_dry_run")
    assert hasattr(module, "build_m1_first_deploy_dry_run_report")
    assert hasattr(module, "build_m1_first_deploy_dry_run_markdown")
    assert module.M1_FIRST_DEPLOY_DRY_RUN_VERSION == "m1_first_deploy_dry_run.v1"


def test_m1_rollout_execution_record_script_imports_cleanly():
    module = importlib.import_module("scripts.check_m1_rollout_execution_record")
    assert hasattr(module, "build_m1_rollout_execution_record_report")
    assert hasattr(module, "build_m1_rollout_execution_record_draft")
    assert module.M1_ROLLOUT_EXECUTION_RECORD_VERSION == "m1_rollout_execution_record.v1"


def test_m1_operations_review_record_script_imports_cleanly():
    module = importlib.import_module("scripts.check_m1_operations_review_record")
    assert hasattr(module, "build_m1_operations_review_record_report")
    assert hasattr(module, "build_m1_operations_review_record_draft")
    assert module.M1_OPERATIONS_REVIEW_RECORD_VERSION == "m1_operations_review_record.v1"


def test_release_artifact_builder_imports_cleanly():
    module = importlib.import_module("scripts.build_release_artifact")
    assert hasattr(module, "build_release_artifact_report")
    assert hasattr(module, "build_release_artifact_markdown")
    assert module.RELEASE_ARTIFACT_VERSION == "release_artifact.v1"


def test_release_candidate_freeze_script_imports_cleanly():
    module = importlib.import_module("scripts.check_release_candidate_freeze")
    assert hasattr(module, "build_release_candidate_freeze_report")
    assert hasattr(module, "build_release_candidate_freeze_markdown")
    assert module.RELEASE_CANDIDATE_FREEZE_VERSION == "release_candidate_freeze.v1"


def test_release_candidate_freeze_record_renderer_imports_cleanly():
    module = importlib.import_module("scripts.render_release_candidate_freeze_record")
    assert hasattr(module, "build_release_candidate_freeze_record_report")
    assert hasattr(module, "build_release_candidate_freeze_record_markdown")
    assert module.RELEASE_CANDIDATE_FREEZE_RECORD_VERSION == "release_candidate_freeze_record.v1"


def test_release_candidate_freeze_signoff_script_imports_cleanly():
    module = importlib.import_module("scripts.check_release_candidate_freeze_signoff")
    assert hasattr(module, "build_release_candidate_freeze_signoff_report")
    assert hasattr(module, "build_release_candidate_freeze_signoff_markdown")
    assert module.RELEASE_CANDIDATE_FREEZE_SIGNOFF_VERSION == "release_candidate_freeze_signoff.v1"


def test_m1_deployment_gate_script_imports_cleanly():
    module = importlib.import_module("scripts.check_m1_deployment_gate")
    assert hasattr(module, "build_m1_deployment_gate_report")
    assert module.M1_DEPLOYMENT_GATE_VERSION == "m1_deployment_gate.v1"
    source = Path(module.__file__).read_text(encoding="utf-8")
    config_source = Path("app/config.py").read_text(encoding="utf-8")

    assert "ZHIXING_DISABLE_DOTENV" in source
    assert "ZHIXING_DISABLE_DOTENV" in config_source


def test_backup_restore_readiness_script_imports_cleanly():
    module = importlib.import_module("scripts.check_backup_restore_readiness")
    assert hasattr(module, "build_backup_restore_readiness_report")
    assert module.BACKUP_RESTORE_READINESS_VERSION == "backup_restore_readiness.v1"


def test_postgres_redis_ops_status_script_imports_cleanly():
    module = importlib.import_module("scripts.check_postgres_redis_ops_status")
    assert hasattr(module, "build_postgres_redis_ops_status_report")
    assert module.POSTGRES_REDIS_OPS_STATUS_VERSION == "postgres_redis_ops_status.v1"


def test_postgres_redis_recovery_record_script_imports_cleanly():
    module = importlib.import_module("scripts.check_postgres_redis_recovery_record")
    assert hasattr(module, "build_postgres_redis_recovery_record_report")
    assert module.POSTGRES_REDIS_RECOVERY_RECORD_VERSION == "postgres_redis_recovery_record.v1"


def test_postgres_redis_live_probe_script_imports_cleanly():
    module = importlib.import_module("scripts.collect_postgres_redis_live_probe")
    assert hasattr(module, "build_postgres_redis_live_probe_report")
    assert module.POSTGRES_REDIS_LIVE_PROBE_VERSION == "postgres_redis_live_probe.v1"


def test_postgres_redis_ops_summary_renderer_imports_cleanly():
    module = importlib.import_module("scripts.render_postgres_redis_ops_summary")
    assert hasattr(module, "build_postgres_redis_ops_summary_report")
    assert hasattr(module, "build_postgres_redis_ops_summary_markdown")
    assert module.POSTGRES_REDIS_OPS_SUMMARY_VERSION == "postgres_redis_ops_summary.v1"


def test_postgres_redis_ops_declaration_request_renderer_imports_cleanly():
    module = importlib.import_module("scripts.render_postgres_redis_ops_declaration_request")
    assert hasattr(module, "build_postgres_redis_ops_declaration_request")
    assert hasattr(module, "build_postgres_redis_ops_declaration_request_markdown")
    assert (
        module.POSTGRES_REDIS_OPS_DECLARATION_REQUEST_VERSION
        == "postgres_redis_ops_declaration_request.v1"
    )


def test_postgres_redis_ops_declaration_record_script_imports_cleanly():
    module = importlib.import_module("scripts.check_postgres_redis_ops_declaration_record")
    assert hasattr(module, "build_postgres_redis_ops_declaration_record_report")
    assert hasattr(module, "build_postgres_redis_ops_declaration_record_draft")
    assert (
        module.POSTGRES_REDIS_OPS_DECLARATION_RECORD_VERSION
        == "postgres_redis_ops_declaration_record.v1"
    )


def test_postgres_redis_ops_env_patch_renderer_imports_cleanly():
    module = importlib.import_module("scripts.render_postgres_redis_ops_env_patch")
    assert hasattr(module, "build_postgres_redis_ops_env_patch_report")
    assert hasattr(module, "build_postgres_redis_ops_env_patch_markdown")
    assert module.POSTGRES_REDIS_OPS_ENV_PATCH_VERSION == "postgres_redis_ops_env_patch.v1"


def test_postgres_redis_ops_owner_questionnaire_renderer_imports_cleanly():
    module = importlib.import_module("scripts.render_postgres_redis_ops_owner_questionnaire")
    assert hasattr(module, "build_postgres_redis_ops_owner_questionnaire")
    assert hasattr(module, "build_postgres_redis_ops_owner_questionnaire_markdown")
    assert (
        module.POSTGRES_REDIS_OPS_OWNER_QUESTIONNAIRE_VERSION
        == "postgres_redis_ops_owner_questionnaire.v1"
    )


def test_postgres_redis_backup_declaration_candidates_renderer_imports_cleanly():
    module = importlib.import_module("scripts.render_postgres_redis_backup_declaration_candidates")
    assert hasattr(module, "build_postgres_redis_backup_declaration_candidates")
    assert hasattr(module, "build_postgres_redis_backup_declaration_candidates_markdown")
    assert (
        module.POSTGRES_REDIS_BACKUP_DECLARATION_CANDIDATES_VERSION
        == "postgres_redis_backup_declaration_candidates.v1"
    )


def test_postgres_restore_drill_live_probe_script_imports_cleanly():
    module = importlib.import_module("scripts.collect_postgres_restore_drill_live_probe")
    assert hasattr(module, "build_postgres_restore_drill_live_probe_report")
    assert hasattr(module, "build_postgres_restore_drill_live_probe_markdown")
    assert (
        module.POSTGRES_RESTORE_DRILL_LIVE_PROBE_VERSION
        == "postgres_restore_drill_live_probe.v1"
    )


def test_live_concurrency_probe_script_imports_cleanly():
    module = importlib.import_module("scripts.collect_live_concurrency_probe")
    assert hasattr(module, "build_live_concurrency_probe_report")
    assert hasattr(module, "build_live_concurrency_probe_markdown")
    assert module.LIVE_CONCURRENCY_PROBE_VERSION == "live_concurrency_probe.v1"


def test_concurrency_rate_limit_evidence_record_script_imports_cleanly():
    module = importlib.import_module("scripts.check_concurrency_rate_limit_evidence_record")
    assert hasattr(module, "build_concurrency_rate_limit_evidence_record_report")
    assert (
        module.CONCURRENCY_RATE_LIMIT_EVIDENCE_RECORD_VERSION
        == "concurrency_rate_limit_evidence_record.v1"
    )


def test_live_chat_probe_script_imports_cleanly():
    module = importlib.import_module("scripts.collect_live_chat_probe")
    assert hasattr(module, "build_live_chat_probe_report")
    assert hasattr(module, "build_live_chat_probe_markdown")
    assert module.LIVE_CHAT_PROBE_VERSION == "live_chat_probe.v1"


def test_live_chat_probe_execution_approval_script_imports_cleanly():
    module = importlib.import_module("scripts.check_live_chat_probe_execution_approval")
    assert hasattr(module, "build_live_chat_probe_execution_approval_report")
    assert hasattr(module, "build_live_chat_probe_execution_approval_markdown")
    assert module.LIVE_CHAT_PROBE_EXECUTION_APPROVAL_VERSION == "live_chat_probe_execution_approval.v1"


def test_probe_auth_readiness_script_imports_cleanly():
    module = importlib.import_module("scripts.check_probe_auth_readiness")
    assert hasattr(module, "build_probe_auth_readiness_report")
    assert hasattr(module, "build_probe_auth_readiness_markdown")
    assert module.PROBE_AUTH_READINESS_VERSION == "probe_auth_readiness.v1"


def test_server_capacity_snapshot_script_imports_cleanly():
    module = importlib.import_module("scripts.collect_server_capacity_snapshot")
    assert hasattr(module, "build_server_capacity_snapshot_report")
    assert hasattr(module, "build_server_capacity_snapshot_markdown")
    assert module.SERVER_CAPACITY_SNAPSHOT_VERSION == "server_capacity_snapshot.v1"


def test_rate_limit_live_probe_script_imports_cleanly():
    module = importlib.import_module("scripts.collect_rate_limit_live_probe")
    assert hasattr(module, "build_rate_limit_live_probe_report")
    assert hasattr(module, "build_rate_limit_live_probe_markdown")
    assert module.RATE_LIMIT_LIVE_PROBE_VERSION == "rate_limit_live_probe.v1"


def test_rate_limit_release_scope_script_imports_cleanly():
    module = importlib.import_module("scripts.check_rate_limit_release_scope")
    assert hasattr(module, "build_rate_limit_release_scope_report")
    assert hasattr(module, "build_rate_limit_release_scope_markdown")
    assert module.RATE_LIMIT_RELEASE_SCOPE_VERSION == "rate_limit_release_scope.v1"


def test_backup_schedule_live_probe_script_imports_cleanly():
    module = importlib.import_module("scripts.collect_backup_schedule_live_probe")
    assert hasattr(module, "build_backup_schedule_live_probe_report")
    assert hasattr(module, "build_backup_schedule_live_probe_markdown")
    assert module.BACKUP_SCHEDULE_LIVE_PROBE_VERSION == "backup_schedule_live_probe.v1"


def test_docker_disk_cleanup_plan_script_imports_cleanly():
    module = importlib.import_module("scripts.collect_docker_disk_cleanup_plan")
    assert hasattr(module, "build_docker_disk_cleanup_plan_report")
    assert hasattr(module, "build_docker_disk_cleanup_plan_markdown")
    assert module.DOCKER_DISK_CLEANUP_PLAN_VERSION == "docker_disk_cleanup_plan.v1"


def test_docker_disk_cleanup_execution_script_imports_cleanly():
    module = importlib.import_module("scripts.execute_docker_disk_cleanup")
    assert hasattr(module, "build_docker_disk_cleanup_execution_report")
    assert hasattr(module, "build_docker_disk_cleanup_execution_markdown")
    assert module.DOCKER_DISK_CLEANUP_EXECUTION_VERSION == "docker_disk_cleanup_execution.v1"


def test_docker_build_cache_cleanup_plan_script_imports_cleanly():
    module = importlib.import_module("scripts.collect_docker_build_cache_cleanup_plan")
    assert hasattr(module, "build_docker_build_cache_cleanup_plan_report")
    assert hasattr(module, "build_docker_build_cache_cleanup_plan_markdown")
    assert module.DOCKER_BUILD_CACHE_CLEANUP_PLAN_VERSION == "docker_build_cache_cleanup_plan.v1"


def test_docker_build_cache_cleanup_execution_script_imports_cleanly():
    module = importlib.import_module("scripts.execute_docker_build_cache_cleanup")
    assert hasattr(module, "build_docker_build_cache_cleanup_execution_report")
    assert hasattr(module, "build_docker_build_cache_cleanup_execution_markdown")
    assert module.DOCKER_BUILD_CACHE_CLEANUP_EXECUTION_VERSION == "docker_build_cache_cleanup_execution.v1"


def test_docker_build_cache_cleanup_approval_script_imports_cleanly():
    module = importlib.import_module("scripts.check_docker_build_cache_cleanup_approval")
    assert hasattr(module, "build_docker_build_cache_cleanup_approval_report")
    assert hasattr(module, "build_docker_build_cache_cleanup_approval_markdown")
    assert module.DOCKER_BUILD_CACHE_CLEANUP_APPROVAL_VERSION == "docker_build_cache_cleanup_approval.v1"


def test_docker_build_cache_post_cleanup_script_imports_cleanly():
    module = importlib.import_module("scripts.check_docker_build_cache_post_cleanup")
    assert hasattr(module, "build_docker_build_cache_post_cleanup_report")
    assert hasattr(module, "build_docker_build_cache_post_cleanup_markdown")
    assert module.DOCKER_BUILD_CACHE_POST_CLEANUP_VERSION == "docker_build_cache_post_cleanup.v1"


def test_docker_build_cache_approval_request_renderer_imports_cleanly():
    module = importlib.import_module("scripts.render_docker_build_cache_cleanup_approval_request")
    assert hasattr(module, "build_docker_build_cache_cleanup_approval_request")
    assert hasattr(module, "render_docker_build_cache_cleanup_approval_request_markdown")
    assert module.DOCKER_BUILD_CACHE_CLEANUP_APPROVAL_REQUEST_VERSION == "docker_build_cache_cleanup_approval_request.v1"


def test_backup_restore_drill_evidence_collector_imports_cleanly():
    module = importlib.import_module("scripts.collect_backup_restore_drill_evidence")
    assert hasattr(module, "build_backup_restore_drill_evidence_report")
    assert hasattr(module, "build_backup_restore_drill_evidence_markdown")
    assert module.BACKUP_RESTORE_DRILL_EVIDENCE_VERSION == "backup_restore_drill_evidence.v1"


def test_external_api_readiness_script_imports_cleanly():
    module = importlib.import_module("scripts.check_external_api_readiness")
    assert hasattr(module, "build_external_api_readiness_report")
    assert module.EXTERNAL_API_READINESS_VERSION == "external_api_readiness.v1"


def test_external_dependency_resilience_record_script_imports_cleanly():
    module = importlib.import_module("scripts.check_external_dependency_resilience_record")
    assert hasattr(module, "build_external_dependency_resilience_record_report")
    assert (
        module.EXTERNAL_DEPENDENCY_RESILIENCE_RECORD_VERSION
        == "external_dependency_resilience_record.v1"
    )


def test_monitoring_alerting_readiness_script_imports_cleanly():
    module = importlib.import_module("scripts.check_monitoring_alerting_readiness")
    assert hasattr(module, "build_monitoring_alerting_readiness_report")
    assert module.MONITORING_ALERTING_READINESS_VERSION == "monitoring_alerting_readiness.v1"


def test_monitoring_alerting_evidence_collector_imports_cleanly():
    module = importlib.import_module("scripts.collect_monitoring_alerting_evidence")
    assert hasattr(module, "build_monitoring_alerting_evidence_report")
    assert hasattr(module, "build_monitoring_alerting_evidence_markdown")
    assert module.MONITORING_ALERTING_EVIDENCE_VERSION == "monitoring_alerting_evidence.v1"


def test_security_release_readiness_script_imports_cleanly():
    module = importlib.import_module("scripts.check_security_release_readiness")
    assert hasattr(module, "build_security_release_readiness_report")
    assert module.SECURITY_RELEASE_READINESS_VERSION == "security_release_readiness.v1"


def test_server_preflight_readiness_script_imports_cleanly():
    module = importlib.import_module("scripts.check_server_preflight_readiness")
    assert hasattr(module, "build_server_preflight_readiness_report")
    assert module.SERVER_PREFLIGHT_READINESS_VERSION == "server_preflight_readiness.v1"


def test_m1_acceptance_record_renderer_imports_cleanly():
    module = importlib.import_module("scripts.render_m1_acceptance_record")
    assert hasattr(module, "build_m1_acceptance_record_markdown")
    assert module.M1_ACCEPTANCE_RECORD_VERSION == "m1_acceptance_record.v1"


def test_m1_live_evidence_summary_renderer_imports_cleanly():
    module = importlib.import_module("scripts.render_m1_live_evidence_summary")
    assert hasattr(module, "build_m1_live_evidence_summary_markdown")
    assert module.M1_LIVE_EVIDENCE_SUMMARY_VERSION == "m1_live_evidence_summary.v1"


def test_m1_deployment_evidence_matrix_renderer_imports_cleanly():
    module = importlib.import_module("scripts.render_m1_deployment_evidence_matrix")
    assert hasattr(module, "build_m1_deployment_evidence_matrix_report")
    assert hasattr(module, "build_m1_deployment_evidence_matrix_markdown")
    assert (
        module.M1_DEPLOYMENT_EVIDENCE_MATRIX_VERSION
        == "m1_deployment_evidence_matrix.v1"
    )


def test_m1_evidence_bundle_builder_imports_cleanly():
    module = importlib.import_module("scripts.build_m1_evidence_bundle")
    assert hasattr(module, "build_m1_evidence_bundle_report")
    assert module.M1_EVIDENCE_BUNDLE_VERSION == "m1_evidence_bundle.v1"


def test_m1_private_live_evidence_workflow_imports_cleanly():
    module = importlib.import_module("scripts.run_m1_private_live_evidence_workflow")
    assert hasattr(module, "build_m1_private_live_evidence_workflow_report")
    assert hasattr(module, "build_m1_private_live_evidence_workflow_markdown")
    assert (
        module.M1_PRIVATE_LIVE_EVIDENCE_WORKFLOW_VERSION
        == "m1_private_live_evidence_workflow.v1"
    )


def test_m1_private_evidence_signoff_imports_cleanly():
    module = importlib.import_module("scripts.check_m1_private_evidence_signoff")
    assert hasattr(module, "build_m1_private_evidence_signoff_report")
    assert hasattr(module, "build_m1_private_evidence_signoff_markdown")
    assert module.M1_PRIVATE_EVIDENCE_SIGNOFF_VERSION == "m1_private_evidence_signoff.v1"


def test_travel_data_source_readiness_script_imports_cleanly():
    module = importlib.import_module("scripts.check_travel_data_sources")
    assert hasattr(module, "build_travel_data_source_readiness_report")
    assert module.TRAVEL_DATA_SOURCE_READINESS_VERSION == "travel_data_source_readiness.v1"


def test_public_travel_data_candidates_collector_imports_cleanly():
    module = importlib.import_module("scripts.collect_public_travel_data_candidates")
    assert hasattr(module, "build_public_travel_data_candidates_report")
    assert module.PUBLIC_TRAVEL_DATA_CANDIDATES_VERSION == "public_travel_data_candidates.v1"


def test_public_travel_candidate_review_imports_cleanly():
    module = importlib.import_module("scripts.review_public_travel_data_candidates")
    assert hasattr(module, "build_public_travel_candidate_review_report")
    assert module.PUBLIC_TRAVEL_CANDIDATE_REVIEW_VERSION == "public_travel_candidate_review.v1"


def test_m1_smoke_evidence_collector_imports_cleanly():
    module = importlib.import_module("scripts.collect_m1_smoke_evidence")
    assert hasattr(module, "build_m1_smoke_evidence_report")
    assert hasattr(module, "build_m1_smoke_evidence_markdown")
    assert module.M1_SMOKE_EVIDENCE_VERSION == "m1_smoke_evidence.v1"


def test_m1_go_no_go_evidence_collector_imports_cleanly():
    module = importlib.import_module("scripts.collect_m1_go_no_go_evidence")
    assert hasattr(module, "build_m1_go_no_go_report")
    assert hasattr(module, "build_m1_go_no_go_markdown")
    assert module.M1_GO_NO_GO_EVIDENCE_VERSION == "m1_go_no_go_evidence.v1"


def test_incident_rollback_evidence_collector_imports_cleanly():
    module = importlib.import_module("scripts.collect_incident_rollback_evidence")
    assert hasattr(module, "build_incident_rollback_evidence_report")
    assert hasattr(module, "build_incident_rollback_evidence_markdown")
    assert module.INCIDENT_ROLLBACK_EVIDENCE_VERSION == "incident_rollback_evidence.v1"


def test_rollback_execution_record_script_imports_cleanly():
    module = importlib.import_module("scripts.check_rollback_execution_record")
    assert hasattr(module, "build_rollback_execution_record_report")
    assert module.ROLLBACK_EXECUTION_RECORD_VERSION == "rollback_execution_record.v1"


def test_init_db_script_exposes_migration_modes_without_running_database():
    module = importlib.import_module("scripts.init_db")
    assert hasattr(module, "run_business_migrations")
    assert hasattr(module, "build_alembic_config")
    source = Path(module.__file__).read_text(encoding="utf-8")

    assert "--mode" in source
    assert "--legacy-create-all" in source
    assert "_BOOTSTRAP_IMPORT_ERROR" in source
    assert "Docker Desktop 是否正在运行" in source
    assert "staging/production 不允许使用 legacy create_all" in source


def test_init_db_unreachable_postgres_failure_is_actionable(monkeypatch):
    module = importlib.import_module("scripts.init_db")

    async def fail_probe():
        raise RuntimeError("PostgreSQL TCP 连接不可用：localhost:6543 在 0.1s 内未连通。")

    monkeypatch.setattr(module, "_ensure_runtime_imports", lambda: None)
    monkeypatch.setattr(module, "_probe_postgres_tcp", fail_probe)
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            database_url="postgresql://travel_user:secret@localhost:6543/travel_planner_db",
            postgres_host="localhost",
            postgres_port=6543,
            postgres_db="travel_planner_db",
        ),
    )

    with pytest.raises(RuntimeError, match="PostgreSQL TCP 连接不可用"):
        asyncio.run(module.init_database())

    guidance = module._actionable_database_error(RuntimeError("connection refused"))
    assert "docker compose up -d postgres" in guidance
    assert "POSTGRES_HOST/PORT/DB/USER/PASSWORD" in guidance


def test_init_db_bootstrap_sequence_runs_when_dependencies_are_reachable(monkeypatch):
    module = importlib.import_module("scripts.init_db")
    events = []

    async def ok_probe():
        events.append("probe")

    def run_migrations(revision="head"):
        events.append(("migrate", revision))

    async def init_langgraph(db_url):
        events.append(("langgraph", db_url))

    async def enable_pgvector(db_url):
        events.append(("pgvector", db_url))

    monkeypatch.setattr(module, "_ensure_runtime_imports", lambda: None)
    monkeypatch.setattr(module, "_probe_postgres_tcp", ok_probe)
    monkeypatch.setattr(module, "run_business_migrations", run_migrations)
    monkeypatch.setattr(module, "_init_langgraph_tables", init_langgraph)
    monkeypatch.setattr(module, "_enable_pgvector", enable_pgvector)
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            database_url="postgresql://travel_user:secret@localhost:5432/travel_planner_db",
            postgres_host="localhost",
            postgres_port=5432,
            postgres_db="travel_planner_db",
        ),
    )

    asyncio.run(module.init_database(revision="head"))

    assert events == [
        "probe",
        ("migrate", "head"),
        ("langgraph", "postgresql://travel_user:secret@localhost:5432/travel_planner_db"),
        ("pgvector", "postgresql://travel_user:secret@localhost:5432/travel_planner_db"),
    ]


def test_init_rag_script_exposes_actionable_failure_guidance():
    module = importlib.import_module("scripts.init_rag")
    source = Path(module.__file__).read_text(encoding="utf-8")

    assert "_RAG_IMPORT_ERROR" in source
    assert "RAG_INTERNAL_VECTORSTORE_PATH" in source
    assert "validate_rag_knowledge.py --json" in source
    assert "DASHSCOPE_API_KEY" in source
    assert "sentence-transformers" in source


def test_alembic_business_migration_covers_owned_tables_only():
    revision = Path("alembic/versions/20260511_0001_initial_business_schema.py").read_text(
        encoding="utf-8"
    )
    env = Path("alembic/env.py").read_text(encoding="utf-8")

    for table_name in [
        "user",
        "conversation",
        "message",
        "approval_request",
        "approval_event",
        "tool_audit_event",
    ]:
        assert f'"{table_name}"' in revision

    for langgraph_table in [
        "checkpoint_migrations",
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
        "store_migrations",
        "store_vectors",
    ]:
        assert langgraph_table not in revision

    assert "settings.database_url" in env
    assert "Base.metadata" in env
    assert "postgresql+psycopg" in env


def test_evaluation_runner_exposes_preflight_only_entrypoint():
    module = importlib.import_module("scripts.run_evaluation_scenarios")
    assert hasattr(module, "main")
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "--scenario" in source
    assert "--scenario-timeout" in source
    assert "--global-timeout" in source
    assert "--preflight-only" in source
    assert "partial_reason" in source
    assert "run_acceptance_preflight" in source


def test_acceptance_comparison_script_imports_cleanly():
    module = importlib.import_module("scripts.compare_acceptance_runs")
    assert hasattr(module, "main")
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "compare_acceptance_summaries" in source
    assert "--fail-on-regression" in source


def test_ci_workflow_has_default_gate_and_staging_smoke_dispatch():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    staging_smoke = Path(".github/workflows/staging-smoke.yml").read_text(encoding="utf-8")

    assert "python -m compileall app tests scripts" in workflow
    assert "python scripts/validate_rag_knowledge.py" in workflow
    assert "python -m pytest --collect-only -q" in workflow
    assert "python -m pytest tests/test_ci_workflows.py -q" in workflow
    assert "python -m pytest -q" in workflow
    assert "node scripts/verify_frontend_report_renderer.js" in workflow
    assert "scripts/check_runtime_readiness.py --target development --json" in workflow
    assert "workflow_dispatch" in workflow
    assert "workflow_dispatch" in staging_smoke
    assert "--acceptance-smoke" in staging_smoke
    assert "actions/upload-artifact@v4" in staging_smoke


def test_ci_default_gate_uses_only_non_real_placeholder_values():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "DASHSCOPE_API_KEY: test-key-dashscope" in workflow
    assert "LANGSMITH_API_KEY: test-key-langsmith" in workflow
    assert "JWT_SECRET_KEY: dev-only-ci-jwt-secret-change-me" in workflow
    assert "your-" not in workflow


def test_docker_compose_exposes_runtime_readiness_contract():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    for env_name in [
        "DASHSCOPE_API_KEY",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST_PORT",
        "REDIS_HOST",
        "REDIS_PORT",
        "REDIS_HOST_PORT",
        "RAG_VECTORSTORE_PATH",
        "RAG_COLLECTION_NAME",
        "RAG_INTERNAL_VECTORSTORE_PATH",
        "RAG_INTERNAL_COLLECTION_NAME",
        "AMAP_API_KEY",
        "VARIFLIGHT_API_KEY",
        "AIGOHOTEL_API_KEY",
        "JWT_SECRET_KEY",
        "LANGGRAPH_RECURSION_LIMIT",
        "ZHIXING_M1_AUDIENCE",
        "ZHIXING_REAL_PAYMENT_ORDER_DISABLED",
        "ZHIXING_BACKUP_TARGET",
        "ZHIXING_POSTGRES_BACKUP_STATUS",
        "ZHIXING_POSTGRES_RESTORE_DRILL_STATUS",
        "ZHIXING_RAG_RESTORE_DRILL_STATUS",
        "ZHIXING_RESTORE_DRILL_OWNER",
        "ZHIXING_ACCEPTABLE_DATA_LOSS",
        "ZHIXING_DEPLOY_DIR",
        "ZHIXING_DOCKER_STATUS",
        "ZHIXING_SERVER_PORTS_STATUS",
        "ZHIXING_TLS_STATUS",
        "ZHIXING_REVERSE_PROXY_STATUS",
        "ZHIXING_HEALTH_ALERT_DELIVERY_STATUS",
        "ZHIXING_READINESS_ALERT_DELIVERY_STATUS",
        "ZHIXING_ALERT_DRILL_OWNER",
        "ZHIXING_ALERT_DRILL_WINDOW",
        "ZHIXING_ERROR_RATE_MONITOR_STATUS",
        "ZHIXING_P95_LATENCY_MONITOR_STATUS",
        "ZHIXING_TOOL_FAILURE_MONITOR_STATUS",
        "ZHIXING_COST_ALERT_STATUS",
        "ZHIXING_BACKUP_ALERT_STATUS",
        "ZHIXING_LOG_REDACTION_SAMPLE_STATUS",
        "ZHIXING_SHARED_DATA_DIR",
        "ZHIXING_SHARED_LOG_DIR",
        "ZHIXING_SHARED_BACKUP_DIR",
        "ZHIXING_DAILY_COST_BUDGET",
        "ZHIXING_EXTERNAL_API_QUOTA_BUDGET",
        "ZHIXING_PROVIDER_CONSOLE_OWNER",
        "ZHIXING_PROVIDER_SUPPORT_CHANNEL",
        "ZHIXING_EXTERNAL_API_DEGRADATION_POLICY",
        "ZHIXING_EXTERNAL_API_TIMEOUT_RETRY_POLICY",
        "ZHIXING_TAVILY_SERVICE_STATUS",
        "ZHIXING_VARIFLIGHT_SERVICE_STATUS",
        "ZHIXING_AIGOHOTEL_SERVICE_STATUS",
        "ZHIXING_12306_MCP_STATUS",
        "ZHIXING_ROLLBACK_OWNER",
        "ZHIXING_INCIDENT_OWNER",
        "ZHIXING_ROLLBACK_DRILL_STATUS",
        "ZHIXING_ROLLBACK_TARGET_STATUS",
        "ZHIXING_POST_ROLLBACK_HEALTH_STATUS",
        "ZHIXING_POST_ROLLBACK_SMOKE_STATUS",
        "ZHIXING_ROLLBACK_DATA_SAFETY_STATUS",
        "ZHIXING_INCIDENT_RESPONSE_STATUS",
        "ZHIXING_INCIDENT_REVIEW_STATUS",
        "ZHIXING_INCIDENT_SEVERITY_POLICY_STATUS",
        "ZHIXING_INCIDENT_COMMUNICATION_STATUS",
        "ZHIXING_LEAK_RESPONSE_OWNER",
        "ZHIXING_JWT_SECRET_STATUS",
        "ZHIXING_PROVIDER_KEY_STATUS",
        "ZHIXING_DATABASE_SECRET_STATUS",
        "ZHIXING_REDIS_SECRET_STATUS",
        "ZHIXING_ALLOWED_ORIGINS_STATUS",
    ]:
        assert env_name in compose

    assert "/health/ready" in compose
    assert "SESSION_LOCK_BACKEND" in compose
    assert "SESSION_LOCK_REDIS_FALLBACK_TO_LOCAL" in compose
    assert "API_RATE_LIMIT_ENABLED" in compose
    assert "API_RATE_LIMIT_BACKEND" in compose
    assert "API_RATE_LIMIT_REQUESTS_PER_WINDOW" in compose
    assert "API_RATE_LIMIT_WINDOW_SECONDS" in compose
    assert "API_RATE_LIMIT_LOCAL_FALLBACK" in compose
    assert "service_healthy" in compose
    assert "${ZHIXING_SHARED_DATA_DIR:-./data}:/app/data" in compose
    assert "${ZHIXING_SHARED_LOG_DIR:-./logs}:/app/logs" in compose
    assert "${ZHIXING_SHARED_BACKUP_DIR:-./backups}:/app/backups" in compose
    assert '"${POSTGRES_HOST_PORT:-5432}:5432"' in compose
    assert '"${REDIS_HOST_PORT:-6379}:6379"' in compose


def test_container_files_keep_liveness_and_proxy_configurable():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    runtime_dockerfile = Path("deploy/Dockerfile.runtime").read_text(encoding="utf-8")
    caddyfile = Path("deploy/Caddyfile").read_text(encoding="utf-8")
    first_deploy = Path("deploy/first-deploy.sh").read_text(encoding="utf-8")
    update_runtime = Path("deploy/update-runtime-image.sh").read_text(encoding="utf-8")

    for content in [dockerfile, runtime_dockerfile]:
        assert "APP_ENV=production" in content
        assert "/health/live" in content
        assert "python\", \"-m\", \"app.run" in content

    assert "{$ZHIXING_SITE_ADDRESS::80}" in caddyfile
    assert "/health/*" in caddyfile
    assert "reverse_proxy backend:8000" in caddyfile
    assert "--execute" in first_deploy
    assert "data/vectorstore" in first_deploy
    assert "docker compose --env-file" in first_deploy
    assert "ZHIXING_SHARED_DATA_DIR" in update_runtime
    assert "ZHIXING_DEPLOY_DIR/shared/data" in update_runtime
    assert "ZHIXING_DISK_GUARD_ENABLED" in update_runtime
    assert "ZHIXING_MIN_FREE_DISK_MB" in update_runtime
    assert "ZHIXING_DISK_WARN_USED_PERCENT" in update_runtime
    assert "ZHIXING_DISK_FAIL_USED_PERCENT" in update_runtime
    assert "df -Pm" in update_runtime
    assert "disk_guard_available_mb" in update_runtime
    assert "disk_guard_status=warning" in update_runtime
    assert "disk_guard_status=blocked" in update_runtime


def test_readiness_docs_cover_ci_staging_and_production_layers():
    deployment = Path("docs/部署与运行/deployment-readiness.md").read_text(encoding="utf-8")
    runtime = Path("docs/部署与运行/runtime-environment.md").read_text(encoding="utf-8")
    evaluation = Path("docs/评估与验收/evaluation-system.md").read_text(encoding="utf-8")
    db_migration = Path("docs/部署与运行/db-migration-readiness.md").read_text(encoding="utf-8")

    for content in [deployment, runtime, evaluation]:
        assert "CI" in content
        assert "workflow_dispatch" in content
        assert "preflight" in content

    assert "--target development --json" in deployment
    assert "--target local --json" in deployment
    assert "--target production --json" in deployment
    assert "component_readiness" in deployment
    assert "repair_suggestions" in deployment
    assert "alembic upgrade head" in deployment
    assert "默认不连接真实 PostgreSQL" in db_migration
    assert "AsyncPostgresSaver.setup()" in db_migration
    assert "tool_audit_event" in db_migration
    assert "staging-smoke.yml" in evaluation
    assert "acceptance-smoke" in evaluation
    assert "blocked（环境阻塞）" in runtime
    assert "Docker" in deployment
