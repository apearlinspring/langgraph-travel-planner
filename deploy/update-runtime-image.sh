#!/usr/bin/env sh
set -eu

APP_IMAGE="${APP_IMAGE:-langgraph-travel-planner-backend:latest}"
BASE_IMAGE="${BASE_IMAGE:-zhixing-backend-base:$(date +%Y%m%d%H%M%S)}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"
PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST:-pypi.org}"
AIGOHOTEL_MCP_VERSION="${AIGOHOTEL_MCP_VERSION:-0.3.1}"
COMPOSE_PROJECT_NAME="${ZHIXING_COMPOSE_PROJECT_NAME:-langgraph-travel-planner}"
ZHIXING_DISK_GUARD_ENABLED="${ZHIXING_DISK_GUARD_ENABLED:-1}"
ZHIXING_DISK_GUARD_PATH="${ZHIXING_DISK_GUARD_PATH:-.}"
ZHIXING_MIN_FREE_DISK_MB="${ZHIXING_MIN_FREE_DISK_MB:-2048}"
ZHIXING_DISK_WARN_USED_PERCENT="${ZHIXING_DISK_WARN_USED_PERCENT:-90}"
ZHIXING_DISK_FAIL_USED_PERCENT="${ZHIXING_DISK_FAIL_USED_PERCENT:-98}"

if [ -n "${ZHIXING_DEPLOY_DIR:-}" ]; then
    ZHIXING_SHARED_DATA_DIR="${ZHIXING_SHARED_DATA_DIR:-$ZHIXING_DEPLOY_DIR/shared/data}"
    ZHIXING_SHARED_LOG_DIR="${ZHIXING_SHARED_LOG_DIR:-$ZHIXING_DEPLOY_DIR/shared/logs}"
    ZHIXING_SHARED_BACKUP_DIR="${ZHIXING_SHARED_BACKUP_DIR:-$ZHIXING_DEPLOY_DIR/shared/backups}"
    export ZHIXING_SHARED_DATA_DIR ZHIXING_SHARED_LOG_DIR ZHIXING_SHARED_BACKUP_DIR
fi

is_non_negative_integer() {
    case "$1" in
        ""|*[!0-9]*)
            return 1
            ;;
        *)
            return 0
            ;;
    esac
}

safe_compose_project_name() {
    case "$1" in
        ""|*[!a-z0-9_-]*|[-_]*)
            return 1
            ;;
        *)
            return 0
            ;;
    esac
}

block_disk_guard() {
    echo "disk_guard_status=blocked"
    echo "disk_guard_error=$1" >&2
    echo "disk_guard_action=free approved Docker image space, move backups, or expand disk before refreshing the runtime image" >&2
    exit 1
}

check_disk_guard() {
    if [ "$ZHIXING_DISK_GUARD_ENABLED" = "0" ]; then
        echo "disk_guard_status=disabled"
        return 0
    fi

    is_non_negative_integer "$ZHIXING_MIN_FREE_DISK_MB" || block_disk_guard "invalid_min_free_disk_mb"
    is_non_negative_integer "$ZHIXING_DISK_WARN_USED_PERCENT" || block_disk_guard "invalid_warn_used_percent"
    is_non_negative_integer "$ZHIXING_DISK_FAIL_USED_PERCENT" || block_disk_guard "invalid_fail_used_percent"

    disk_line="$(df -Pm "$ZHIXING_DISK_GUARD_PATH" 2>/dev/null | awk 'NR==2 {gsub("%", "", $5); print $4 "|" $5}')"
    if [ -z "$disk_line" ]; then
        block_disk_guard "df_unavailable"
    fi

    available_mb="${disk_line%%|*}"
    used_percent="${disk_line#*|}"
    is_non_negative_integer "$available_mb" || block_disk_guard "invalid_df_available_mb"
    is_non_negative_integer "$used_percent" || block_disk_guard "invalid_df_used_percent"

    echo "disk_guard_enabled=1"
    echo "disk_guard_available_mb=$available_mb"
    echo "disk_guard_used_percent=$used_percent"
    echo "disk_guard_min_free_mb=$ZHIXING_MIN_FREE_DISK_MB"
    echo "disk_guard_warn_used_percent=$ZHIXING_DISK_WARN_USED_PERCENT"
    echo "disk_guard_fail_used_percent=$ZHIXING_DISK_FAIL_USED_PERCENT"

    if [ "$available_mb" -lt "$ZHIXING_MIN_FREE_DISK_MB" ]; then
        block_disk_guard "available_disk_below_minimum"
    fi

    if [ "$used_percent" -ge "$ZHIXING_DISK_FAIL_USED_PERCENT" ]; then
        block_disk_guard "disk_used_percent_at_or_above_fail_threshold"
    fi

    if [ "$used_percent" -ge "$ZHIXING_DISK_WARN_USED_PERCENT" ]; then
        echo "disk_guard_status=warning"
        echo "disk_guard_action=runtime build may continue, but M1 go/no-go should require a separate disk cleanup or capacity plan"
        return 0
    fi

    echo "disk_guard_status=passed"
}

if ! safe_compose_project_name "$COMPOSE_PROJECT_NAME"; then
    echo "compose_project_status=blocked" >&2
    echo "compose_project_error=invalid_compose_project_name" >&2
    exit 1
fi
export COMPOSE_PROJECT_NAME
echo "compose_project=$COMPOSE_PROJECT_NAME"

check_disk_guard

if ! docker image inspect "$APP_IMAGE" >/dev/null 2>&1; then
    echo "Base app image $APP_IMAGE does not exist. Run a full Dockerfile build first." >&2
    exit 1
fi

docker tag "$APP_IMAGE" "$BASE_IMAGE"

DOCKER_BUILDKIT="${DOCKER_BUILDKIT:-0}" docker build \
    -f deploy/Dockerfile.runtime \
    -t "$APP_IMAGE" \
    --build-arg BASE_IMAGE="$BASE_IMAGE" \
    --build-arg PIP_INDEX_URL="$PIP_INDEX_URL" \
    --build-arg PIP_TRUSTED_HOST="$PIP_TRUSTED_HOST" \
    --build-arg AIGOHOTEL_MCP_VERSION="$AIGOHOTEL_MCP_VERSION" \
    .

docker compose up -d --no-build backend caddy
docker compose ps
