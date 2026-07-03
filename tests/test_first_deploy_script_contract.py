from pathlib import Path


SCRIPT = Path("deploy/first-deploy.sh")


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_first_deploy_script_defaults_to_safe_dry_run():
    source = _source()

    assert 'MODE="dry_run"' in source
    assert "--execute" in source
    assert 'if [ "$MODE" != "execute" ]' in source
    assert "dry_run=true" in source
    assert "would_create=" in source
    assert "would_link_current=" in source
    assert "archive_sha256_check=" in source


def test_first_deploy_script_scans_archive_for_forbidden_runtime_paths():
    source = _source()

    assert "tar -tf" in source
    for forbidden in [
        ".env",
        ".runtime",
        ".venv",
        "data/vectorstore",
        "data/vectorstore_internal",
        "__pycache__",
        "*.pyc",
        "*.log",
    ]:
        assert forbidden in source
    assert ".env.example" in source


def test_first_deploy_script_can_verify_archive_sha256_before_extracting():
    source = _source()

    assert "--archive-sha256" in source
    assert 'ARCHIVE_SHA256="${ZHIXING_RELEASE_SHA256:-}"' in source
    assert "is_sha256_hex" in source
    assert "compute_archive_sha256" in source
    assert "release archive sha256 mismatch" in source
    assert "archive sha256 must be a 64-character hexadecimal value" in source
    assert "sha256sum" in source or "openssl dgst -sha256" in source


def test_first_deploy_script_keeps_runtime_state_in_shared_paths():
    source = _source()

    assert 'SHARED_DATA_DIR="$SHARED_DIR/data"' in source
    assert 'SHARED_LOG_DIR="$SHARED_DIR/logs"' in source
    assert 'SHARED_BACKUP_DIR="$SHARED_DIR/backups"' in source
    assert 'mkdir -p "$SHARED_DATA_DIR/vectorstore" "$SHARED_DATA_DIR/vectorstore_internal"' in source
    assert 'cd "$RELEASE_DIR/data"' in source
    assert "--exclude='./vectorstore'" in source
    assert 'ZHIXING_SHARED_DATA_DIR="$SHARED_DATA_DIR"' in source
    assert 'ZHIXING_SHARED_LOG_DIR="$SHARED_LOG_DIR"' in source
    assert 'ZHIXING_SHARED_BACKUP_DIR="$SHARED_BACKUP_DIR"' in source


def test_first_deploy_script_migrates_legacy_rag_vectorstores_only_when_missing():
    source = _source()

    assert "migrate_legacy_vectorstore_if_missing" in source
    assert '"$DEPLOY_DIR/data/vectorstore"' in source
    assert '"$DEPLOY_DIR/data/vectorstore_internal"' in source
    assert '"$SHARED_DATA_DIR/vectorstore"' in source
    assert '"$SHARED_DATA_DIR/vectorstore_internal"' in source
    assert "already_present" in source
    assert "blocked_partial_target" in source
    assert "copied_from_legacy" in source
    assert 'cp -R -p "$source_dir"/. "$target_dir"/' in source


def test_first_deploy_script_requires_explicit_service_start_and_compose_env_file():
    source = _source()

    assert 'START_SERVICES="${ZHIXING_START_SERVICES:-0}"' in source
    assert "--start-services" in source
    assert 'docker compose --env-file "$RUNTIME_ENV_FILE" config --quiet' in source
    assert 'docker compose --env-file "$RUNTIME_ENV_FILE" up -d --build $COMPOSE_SERVICES' in source
    assert "runtime env file is required for compose validation or service start" in source


def test_first_deploy_script_pins_compose_project_name_to_existing_project():
    source = _source()

    assert 'COMPOSE_PROJECT_NAME="${ZHIXING_COMPOSE_PROJECT_NAME:-langgraph-travel-planner}"' in source
    assert "safe_compose_project_name" in source
    assert "compose_project=$COMPOSE_PROJECT_NAME" in source
    assert 'COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" \\' in source
    assert "compose project name may only contain lowercase letters" in source
