#!/usr/bin/env sh
set -eu

MODE="dry_run"
DEPLOY_DIR="${ZHIXING_DEPLOY_DIR:-}"
RUNTIME_ENV_FILE="${ZHIXING_RUNTIME_ENV_FILE:-}"
BACKUP_ROOT="${ZHIXING_BACKUP_ROOT:-${ZHIXING_SHARED_BACKUP_DIR:-}}"
SCHEDULE="${ZHIXING_BACKUP_CRON_SCHEDULE:-17 3 * * *}"
RETENTION_DAYS="${ZHIXING_BACKUP_RETENTION_DAYS:-7}"
CRON_FILE="${ZHIXING_BACKUP_CRON_FILE:-/etc/cron.d/zhixing-backup}"
LOG_FILE="${ZHIXING_BACKUP_CRON_LOG:-}"
PRUNE_OLD="${ZHIXING_BACKUP_PRUNE_OLD:-0}"

die() {
    echo "error=$1" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage: sh deploy/install-backup-cron.sh [--execute] [--deploy-dir DIR] [--env-file FILE] [--backup-root DIR] [--schedule "M H * * *"] [--retention-days N] [--cron-file FILE] [--log-file FILE] [--prune-old]

Installs a cron.d entry that runs deploy/run-backup.sh.
Default mode is dry-run. Use --execute to write the cron file.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --execute)
            MODE="execute"
            ;;
        --deploy-dir)
            shift
            DEPLOY_DIR="${1:-}"
            ;;
        --env-file)
            shift
            RUNTIME_ENV_FILE="${1:-}"
            ;;
        --backup-root)
            shift
            BACKUP_ROOT="${1:-}"
            ;;
        --schedule)
            shift
            SCHEDULE="${1:-}"
            ;;
        --retention-days)
            shift
            RETENTION_DAYS="${1:-}"
            ;;
        --cron-file)
            shift
            CRON_FILE="${1:-}"
            ;;
        --log-file)
            shift
            LOG_FILE="${1:-}"
            ;;
        --prune-old)
            PRUNE_OLD="1"
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            die "unknown argument: $1"
            ;;
    esac
    shift
done

[ -n "$DEPLOY_DIR" ] || DEPLOY_DIR="$(pwd)"
[ -d "$DEPLOY_DIR" ] || die "deploy directory is missing"

if [ -L "$DEPLOY_DIR/current" ] || [ -d "$DEPLOY_DIR/current" ]; then
    APP_DIR="$DEPLOY_DIR/current"
else
    APP_DIR="$DEPLOY_DIR"
fi
RUN_SCRIPT="$APP_DIR/deploy/run-backup.sh"
[ -f "$RUN_SCRIPT" ] || die "deploy/run-backup.sh is missing"

if [ -z "$RUNTIME_ENV_FILE" ]; then
    if [ -f "$DEPLOY_DIR/shared/.env" ]; then
        RUNTIME_ENV_FILE="$DEPLOY_DIR/shared/.env"
    elif [ -f "$APP_DIR/.env" ]; then
        RUNTIME_ENV_FILE="$APP_DIR/.env"
    else
        RUNTIME_ENV_FILE=""
    fi
fi

if [ -z "$BACKUP_ROOT" ]; then
    if [ -d "$DEPLOY_DIR/shared" ]; then
        BACKUP_ROOT="$DEPLOY_DIR/shared/backups"
    else
        BACKUP_ROOT="$APP_DIR/backups"
    fi
fi

if [ -z "$LOG_FILE" ]; then
    if [ -d "$DEPLOY_DIR/shared" ]; then
        LOG_FILE="$DEPLOY_DIR/shared/logs/backup-cron.log"
    else
        LOG_FILE="$APP_DIR/logs/backup-cron.log"
    fi
fi

case "$BACKUP_ROOT" in
    /*)
        ;;
    *)
        die "backup root must be an absolute path"
        ;;
esac
case "$LOG_FILE" in
    /*)
        ;;
    *)
        die "log file must be an absolute path"
        ;;
esac
case "$CRON_FILE" in
    /etc/cron.d/*)
        ;;
    *)
        die "cron file must stay under /etc/cron.d"
        ;;
esac
case "$RETENTION_DAYS" in
    ''|*[!0-9]*)
        die "retention days must be a positive integer"
        ;;
esac
[ "$RETENTION_DAYS" -gt 0 ] || die "retention days must be greater than zero"

field_count="$(printf '%s\n' "$SCHEDULE" | awk '{print NF}')"
[ "$field_count" = "5" ] || die "schedule must contain exactly five cron fields"

quote_sq() {
    printf "%s" "$1" | sed "s/'/'\\\\''/g"
}

prune_arg=""
[ "$PRUNE_OLD" = "1" ] && prune_arg=" --prune-old"
env_arg=""
[ -n "$RUNTIME_ENV_FILE" ] && env_arg=" --env-file '$(quote_sq "$RUNTIME_ENV_FILE")'"

cron_command="ZHIXING_DEPLOY_DIR='$(quote_sq "$DEPLOY_DIR")' ZHIXING_BACKUP_ROOT='$(quote_sq "$BACKUP_ROOT")' sh '$(quote_sq "$RUN_SCRIPT")' --execute$env_arg --backup-root '$(quote_sq "$BACKUP_ROOT")' --retention-days '$RETENTION_DAYS'$prune_arg >> '$(quote_sq "$LOG_FILE")' 2>&1"

echo "version=zhixing_backup_cron_v1"
echo "mode=$MODE"
echo "deploy_dir_echoed=false"
echo "runtime_env_file_echoed=false"
echo "backup_root_echoed=false"
echo "cron_file_echoed=false"
echo "log_file_echoed=false"
echo "schedule=$SCHEDULE"
echo "retention_days=$RETENTION_DAYS"
echo "prune_old=$PRUNE_OLD"

if [ "$MODE" != "execute" ]; then
    echo "dry_run=true"
    echo "would_install_cron=true"
    echo "would_run_backup_script=true"
    echo "execute_with=--execute"
    exit 0
fi

mkdir -p "$(dirname "$LOG_FILE")"
tmp_file="$(mktemp)"
{
    echo "SHELL=/bin/sh"
    echo "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    echo "# ZhiXing backup schedule. Do not place secrets in this file."
    echo "$SCHEDULE root $cron_command"
} > "$tmp_file"
chmod 0644 "$tmp_file"
if command -v crontab >/dev/null 2>&1; then
    :
fi
mv "$tmp_file" "$CRON_FILE"
echo "cron_installed=true"
echo "cron_path_echoed=false"
