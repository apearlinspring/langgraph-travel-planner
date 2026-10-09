#!/usr/bin/env sh
set -eu

VERSION="m1_first_deploy_script.v1"
MODE="dry_run"
START_SERVICES="${ZHIXING_START_SERVICES:-0}"
RUN_COMPOSE_CONFIG="${ZHIXING_RUN_COMPOSE_CONFIG:-1}"
COMPOSE_SERVICES="${ZHIXING_COMPOSE_SERVICES:-backend postgres redis caddy}"
COMPOSE_PROJECT_NAME="${ZHIXING_COMPOSE_PROJECT_NAME:-langgraph-travel-planner}"
DEPLOY_DIR="${ZHIXING_DEPLOY_DIR:-}"
ARCHIVE="${ZHIXING_RELEASE_ARCHIVE:-}"
ARCHIVE_SHA256="${ZHIXING_RELEASE_SHA256:-}"
RUNTIME_ENV_FILE="${ZHIXING_RUNTIME_ENV_FILE:-}"
RELEASE_ID="${ZHIXING_RELEASE_ID:-}"

usage() {
    cat <<'EOF'
Usage:
  sh deploy/first-deploy.sh --archive /tmp/zhixing-release.tar --archive-sha256 <sha256> --deploy-dir /opt/zhixing
  sh deploy/first-deploy.sh --execute --start-services --archive /tmp/zhixing-release.tar --archive-sha256 <sha256> --deploy-dir /opt/zhixing

Options:
  --archive PATH       Uploaded git archive on the target server.
  --archive-sha256 HEX Expected sha256 from release manifest.
  --deploy-dir PATH    Absolute deployment root on the target server.
  --env-file PATH      Runtime env file. Defaults to <deploy-dir>/shared/.env.
  --release-id VALUE   Release directory name. Defaults to archive name or timestamp.
  --execute            Apply the release. Default is dry-run only.
  --start-services     Run docker compose up after config validation.
  --skip-compose-check Skip docker compose config validation.
  ZHIXING_COMPOSE_PROJECT_NAME may override the default Compose project name.
  --help               Show this message.

This script does not print .env contents. In dry-run mode it does not create
directories, extract archives, switch releases, or start services.
EOF
}

die() {
    echo "error: $*" >&2
    exit 1
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

is_abs_path() {
    case "$1" in
        /*) return 0 ;;
        *) return 1 ;;
    esac
}

safe_release_id() {
    case "$1" in
        ""|*[!A-Za-z0-9._-]*) return 1 ;;
        *) return 0 ;;
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

is_sha256_hex() {
    case "$1" in
        *[!0123456789abcdefABCDEF]*|"") return 1 ;;
        *) [ "${#1}" -eq 64 ] ;;
    esac
}

compute_archive_sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$ARCHIVE" | awk '{print $1}'
        return 0
    fi
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$ARCHIVE" | awk '{print $1}'
        return 0
    fi
    if command -v openssl >/dev/null 2>&1; then
        openssl dgst -sha256 "$ARCHIVE" | awk '{print $NF}'
        return 0
    fi
    if command -v python3 >/dev/null 2>&1; then
        python3 - "$ARCHIVE" <<'PY'
import hashlib
import sys

digest = hashlib.sha256()
with open(sys.argv[1], "rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
PY
        return 0
    fi
    return 1
}

display_path() {
    value="$1"
    case "$value" in
        "$DEPLOY_DIR"/*) printf '<deploy-dir>%s' "${value#"$DEPLOY_DIR"}" ;;
        "$DEPLOY_DIR") printf '<deploy-dir>' ;;
        "$ARCHIVE") printf '<release-archive>' ;;
        "$RUNTIME_ENV_FILE") printf '<runtime-env-file>' ;;
        *) printf '<path>' ;;
    esac
}

is_forbidden_archive_entry() {
    entry="${1#./}"
    case "$entry" in
        .env.example|*/.env.example)
            return 1
            ;;
        .env|*/.env|.env.*|*/.env.*|\
        .runtime|.runtime/*|*/.runtime|*/.runtime/*|\
        .venv|.venv/*|*/.venv|*/.venv/*|\
        data/vectorstore|data/vectorstore/*|*/data/vectorstore|*/data/vectorstore/*|\
        data/vectorstore_internal|data/vectorstore_internal/*|*/data/vectorstore_internal|*/data/vectorstore_internal/*|\
        logs|logs/*|*/logs|*/logs/*|\
        __pycache__|__pycache__/*|*/__pycache__|*/__pycache__/*|\
        *.pyc|*.pyo|*.log)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

scan_archive_boundary() {
    forbidden_file="${TMPDIR:-/tmp}/zhixing-forbidden-entries-$$.txt"
    entries_file="${TMPDIR:-/tmp}/zhixing-archive-entries-$$.txt"
    : > "$forbidden_file"
    if ! tar -tf "$ARCHIVE" > "$entries_file"; then
        rm -f "$forbidden_file" "$entries_file"
        die "cannot list release archive"
    fi
    while IFS= read -r entry; do
        if is_forbidden_archive_entry "$entry"; then
            printf '%s\n' "${entry#./}" >> "$forbidden_file"
        fi
    done < "$entries_file"
    if [ -s "$forbidden_file" ]; then
        echo "error: release archive contains forbidden runtime or secret paths:" >&2
        sed -n '1,20p' "$forbidden_file" >&2
        rm -f "$forbidden_file" "$entries_file"
        exit 1
    fi
    rm -f "$forbidden_file" "$entries_file"
}

migrate_legacy_vectorstore_if_missing() {
    label="$1"
    source_dir="$2"
    target_dir="$3"
    status_key="$4"

    if [ -f "$target_dir/chroma.sqlite3" ]; then
        echo "$status_key=already_present"
        return 0
    fi
    if [ ! -f "$source_dir/chroma.sqlite3" ]; then
        echo "$status_key=missing_source"
        return 0
    fi
    if find "$target_dir" -mindepth 1 -maxdepth 1 -print -quit | grep . >/dev/null 2>&1; then
        echo "$status_key=blocked_partial_target"
        die "$label shared vector store is missing chroma.sqlite3 but target directory is not empty"
    fi

    cp -R -p "$source_dir"/. "$target_dir"/
    echo "$status_key=copied_from_legacy"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --archive)
            [ "$#" -ge 2 ] || die "--archive requires a value"
            ARCHIVE="$2"
            shift 2
            ;;
        --archive-sha256)
            [ "$#" -ge 2 ] || die "--archive-sha256 requires a value"
            ARCHIVE_SHA256="$2"
            shift 2
            ;;
        --deploy-dir)
            [ "$#" -ge 2 ] || die "--deploy-dir requires a value"
            DEPLOY_DIR="$2"
            shift 2
            ;;
        --env-file)
            [ "$#" -ge 2 ] || die "--env-file requires a value"
            RUNTIME_ENV_FILE="$2"
            shift 2
            ;;
        --release-id)
            [ "$#" -ge 2 ] || die "--release-id requires a value"
            RELEASE_ID="$2"
            shift 2
            ;;
        --execute)
            MODE="execute"
            shift
            ;;
        --start-services)
            START_SERVICES="1"
            shift
            ;;
        --skip-compose-check)
            RUN_COMPOSE_CONFIG="0"
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            die "unknown argument: $1"
            ;;
    esac
done

[ -n "$DEPLOY_DIR" ] || die "ZHIXING_DEPLOY_DIR or --deploy-dir is required"
[ -n "$ARCHIVE" ] || die "ZHIXING_RELEASE_ARCHIVE or --archive is required"
is_abs_path "$DEPLOY_DIR" || die "deploy dir must be an absolute Linux path"
is_abs_path "$ARCHIVE" || die "archive must be an absolute Linux path"
if [ -n "$ARCHIVE_SHA256" ] && ! is_sha256_hex "$ARCHIVE_SHA256"; then
    die "archive sha256 must be a 64-character hexadecimal value"
fi

case "$DEPLOY_DIR" in
    /|/opt|/var|/tmp|/home)
        die "deploy dir is too broad"
        ;;
esac

if [ -z "$RUNTIME_ENV_FILE" ]; then
    RUNTIME_ENV_FILE="$DEPLOY_DIR/shared/.env"
fi
is_abs_path "$RUNTIME_ENV_FILE" || die "runtime env file must be an absolute Linux path"

[ -f "$ARCHIVE" ] || die "release archive does not exist"
SHA256_STATUS="not_requested"
if [ -n "$ARCHIVE_SHA256" ]; then
    actual_sha256="$(compute_archive_sha256)" || die "cannot compute release archive sha256"
    if [ "$actual_sha256" != "$ARCHIVE_SHA256" ]; then
        die "release archive sha256 mismatch"
    fi
    SHA256_STATUS="passed"
fi
if [ "$RUN_COMPOSE_CONFIG" = "1" ] || [ "$START_SERVICES" = "1" ]; then
    [ -f "$RUNTIME_ENV_FILE" ] || die "runtime env file is required for compose validation or service start"
fi

if [ -z "$RELEASE_ID" ]; then
    archive_name="$(basename "$ARCHIVE")"
    RELEASE_ID="${archive_name%.tar.gz}"
    RELEASE_ID="${RELEASE_ID%.tgz}"
    RELEASE_ID="${RELEASE_ID%.tar}"
    case "$RELEASE_ID" in
        ""|"$archive_name")
            RELEASE_ID="release-$(date +%Y%m%d%H%M%S)"
            ;;
    esac
fi
safe_release_id "$RELEASE_ID" || die "release id may only contain letters, digits, dot, underscore and dash"
safe_compose_project_name "$COMPOSE_PROJECT_NAME" || die "compose project name may only contain lowercase letters, digits, underscore and dash, and must start with a lowercase letter or digit"

need_cmd tar
scan_archive_boundary
if [ "$RUN_COMPOSE_CONFIG" = "1" ] || [ "$START_SERVICES" = "1" ]; then
    need_cmd docker
fi

RELEASES_DIR="$DEPLOY_DIR/releases"
SHARED_DIR="$DEPLOY_DIR/shared"
BACKUPS_DIR="$DEPLOY_DIR/backups"
CURRENT_LINK="$DEPLOY_DIR/current"
RELEASE_DIR="$RELEASES_DIR/$RELEASE_ID"
SHARED_DATA_DIR="$SHARED_DIR/data"
SHARED_LOG_DIR="$SHARED_DIR/logs"
SHARED_BACKUP_DIR="$SHARED_DIR/backups"

echo "version=$VERSION"
echo "mode=$MODE"
echo "archive=$(display_path "$ARCHIVE")"
echo "deploy_dir=$(display_path "$DEPLOY_DIR")"
echo "release_id=$RELEASE_ID"
echo "release_dir=$(display_path "$RELEASE_DIR")"
echo "runtime_env_file=$(display_path "$RUNTIME_ENV_FILE")"
echo "archive_sha256_check=$SHA256_STATUS"
echo "compose_project=$COMPOSE_PROJECT_NAME"
echo "compose_check=$RUN_COMPOSE_CONFIG"
echo "start_services=$START_SERVICES"

if [ "$MODE" != "execute" ]; then
    echo "dry_run=true"
    echo "would_create=$(display_path "$RELEASE_DIR")"
    echo "would_link_current=$(display_path "$CURRENT_LINK")"
    echo "would_keep_runtime_data_in=$(display_path "$SHARED_DIR")"
    echo "execute_with=--execute"
    exit 0
fi

if [ -e "$RELEASE_DIR" ]; then
    die "release directory already exists"
fi
if [ -e "$CURRENT_LINK" ] && [ ! -L "$CURRENT_LINK" ]; then
    die "current path exists and is not a symlink; migrate or back it up manually first"
fi

mkdir -p "$RELEASES_DIR" "$SHARED_DATA_DIR" "$BACKUPS_DIR"
mkdir -p "$SHARED_DATA_DIR/vectorstore" "$SHARED_DATA_DIR/vectorstore_internal" "$SHARED_LOG_DIR" "$SHARED_BACKUP_DIR"

migrate_legacy_vectorstore_if_missing \
    "public RAG" \
    "$DEPLOY_DIR/data/vectorstore" \
    "$SHARED_DATA_DIR/vectorstore" \
    "legacy_public_vectorstore_migration"
migrate_legacy_vectorstore_if_missing \
    "internal RAG" \
    "$DEPLOY_DIR/data/vectorstore_internal" \
    "$SHARED_DATA_DIR/vectorstore_internal" \
    "legacy_internal_vectorstore_migration"

if [ -L "$CURRENT_LINK" ]; then
    current_target="$(readlink "$CURRENT_LINK" || true)"
    if [ -n "$current_target" ] && [ -e "$current_target" ]; then
        backup_archive="$BACKUPS_DIR/pre-${RELEASE_ID}-$(date +%Y%m%d%H%M%S).tar.gz"
        tar -czf "$backup_archive" -C "$(dirname "$current_target")" "$(basename "$current_target")"
        echo "backup_archive=$(display_path "$backup_archive")"
    else
        echo "backup_archive=none"
    fi
else
    echo "backup_archive=none"
fi

mkdir -p "$RELEASE_DIR"
tar -xf "$ARCHIVE" -C "$RELEASE_DIR"

if [ -d "$RELEASE_DIR/data" ]; then
    (
        cd "$RELEASE_DIR/data"
        tar -cf - \
            --exclude='./vectorstore' \
            --exclude='./vectorstore_internal' \
            .
    ) | (
        cd "$SHARED_DATA_DIR"
        tar -xf -
    )
fi

next_link="$DEPLOY_DIR/.current.next"
ln -sfn "$RELEASE_DIR" "$next_link"
if ! mv -Tf "$next_link" "$CURRENT_LINK" 2>/dev/null; then
    rm -f "$CURRENT_LINK"
    mv "$next_link" "$CURRENT_LINK"
fi

cd "$CURRENT_LINK"
if [ -f deploy/update-runtime-image.sh ]; then
    chmod +x deploy/update-runtime-image.sh
fi

if [ "$RUN_COMPOSE_CONFIG" = "1" ]; then
    COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" \
    ZHIXING_SHARED_DATA_DIR="$SHARED_DATA_DIR" \
    ZHIXING_SHARED_LOG_DIR="$SHARED_LOG_DIR" \
    ZHIXING_SHARED_BACKUP_DIR="$SHARED_BACKUP_DIR" \
        docker compose --env-file "$RUNTIME_ENV_FILE" config --quiet
    echo "compose_config=passed"
fi

if [ "$START_SERVICES" = "1" ]; then
    COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" \
    ZHIXING_SHARED_DATA_DIR="$SHARED_DATA_DIR" \
    ZHIXING_SHARED_LOG_DIR="$SHARED_LOG_DIR" \
    ZHIXING_SHARED_BACKUP_DIR="$SHARED_BACKUP_DIR" \
        docker compose --env-file "$RUNTIME_ENV_FILE" up -d --build $COMPOSE_SERVICES
    COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" \
    ZHIXING_SHARED_DATA_DIR="$SHARED_DATA_DIR" \
    ZHIXING_SHARED_LOG_DIR="$SHARED_LOG_DIR" \
    ZHIXING_SHARED_BACKUP_DIR="$SHARED_BACKUP_DIR" \
        docker compose --env-file "$RUNTIME_ENV_FILE" ps
    echo "services_started=true"
else
    echo "services_started=false"
fi

echo "release_applied=true"
