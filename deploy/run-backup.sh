#!/usr/bin/env sh
set -eu

MODE="dry_run"
DEPLOY_DIR="${ZHIXING_DEPLOY_DIR:-}"
RUNTIME_ENV_FILE="${ZHIXING_RUNTIME_ENV_FILE:-}"
BACKUP_ROOT="${ZHIXING_BACKUP_ROOT:-${ZHIXING_SHARED_BACKUP_DIR:-}}"
RETENTION_DAYS="${ZHIXING_BACKUP_RETENTION_DAYS:-7}"
PRUNE_OLD="${ZHIXING_BACKUP_PRUNE_OLD:-0}"
INCLUDE_VECTORSTORE="${ZHIXING_BACKUP_INCLUDE_VECTORSTORE:-1}"

die() {
    echo "error=$1" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage: sh deploy/run-backup.sh [--execute] [--deploy-dir DIR] [--env-file FILE] [--backup-root DIR] [--retention-days N] [--prune-old] [--skip-vectorstore]

Creates a redacted M1 backup artifact set without printing secrets.
Default mode is dry-run. Use --execute for a real backup.
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
        --retention-days)
            shift
            RETENTION_DAYS="${1:-}"
            ;;
        --prune-old)
            PRUNE_OLD="1"
            ;;
        --skip-vectorstore)
            INCLUDE_VECTORSTORE="0"
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
[ -f "$APP_DIR/docker-compose.yml" ] || die "docker-compose.yml is missing"

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
case "$BACKUP_ROOT" in
    /*)
        ;;
    *)
        die "backup root must be an absolute path"
        ;;
esac
case "$BACKUP_ROOT" in
    "/"|"/opt"|"/var"|"/tmp"|"/home")
        die "backup root is too broad"
        ;;
esac

case "$RETENTION_DAYS" in
    ''|*[!0-9]*)
        die "retention days must be a positive integer"
        ;;
esac
[ "$RETENTION_DAYS" -gt 0 ] || die "retention days must be greater than zero"

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

compose_cmd() {
    if [ -n "$RUNTIME_ENV_FILE" ] && [ -f "$RUNTIME_ENV_FILE" ]; then
        docker compose --env-file "$RUNTIME_ENV_FILE" "$@"
    else
        docker compose "$@"
    fi
}

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_id="m1-backup-$stamp"
backup_dir="$BACKUP_ROOT/$backup_id"

echo "version=zhixing_backup_v1"
echo "mode=$MODE"
echo "deploy_dir_echoed=false"
echo "runtime_env_file_echoed=false"
echo "backup_root_echoed=false"
echo "backup_id=$backup_id"
echo "retention_days=$RETENTION_DAYS"
echo "include_vectorstore=$INCLUDE_VECTORSTORE"
echo "prune_old=$PRUNE_OLD"

if [ "$MODE" != "execute" ]; then
    echo "dry_run=true"
    echo "would_create_backup=true"
    echo "would_run_pg_dump=true"
    echo "would_probe_pg_restore_list=true"
    echo "would_trigger_redis_bgsave=true"
    echo "would_copy_rag_artifacts=$INCLUDE_VECTORSTORE"
    echo "execute_with=--execute"
    exit 0
fi

need_cmd docker
need_cmd tar
mkdir -p "$BACKUP_ROOT" "$backup_dir"
chmod 700 "$backup_dir"

(
    cd "$APP_DIR"
    git rev-parse --short HEAD > "$backup_dir/release_commit.txt" 2>/dev/null || true
    compose_cmd ps > "$backup_dir/docker-compose-ps.txt"

    compose_cmd exec -T postgres sh -c \
        'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl' \
        > "$backup_dir/postgres.dump"
    test -s "$backup_dir/postgres.dump" || die "postgres dump is empty"

    compose_cmd exec -T postgres sh -c 'pg_restore --list' \
        < "$backup_dir/postgres.dump" \
        > "$backup_dir/postgres-dump-list.txt"

    compose_cmd exec -T redis sh -c \
        'if [ -n "${REDIS_PASSWORD:-}" ]; then redis-cli -a "$REDIS_PASSWORD" --no-auth-warning BGSAVE >/dev/null; else redis-cli BGSAVE >/dev/null; fi' \
        || true
    docker cp zhixing-redis:/data "$backup_dir/redis-data" >/dev/null 2>&1 || true

    data_dir="${ZHIXING_SHARED_DATA_DIR:-}"
    if [ -z "$data_dir" ]; then
        if [ -d "$DEPLOY_DIR/shared/data" ]; then
            data_dir="$DEPLOY_DIR/shared/data"
        else
            data_dir="$APP_DIR/data"
        fi
    fi
    if [ "$INCLUDE_VECTORSTORE" = "1" ]; then
        if [ -d "$data_dir/vectorstore" ] || [ -d "$data_dir/vectorstore_internal" ]; then
            tar -czf "$backup_dir/rag-vectorstores.tgz" \
                -C "$data_dir" \
                vectorstore vectorstore_internal 2>/dev/null || true
        fi
    fi
    if [ -d "$data_dir/documents" ]; then
        tar -czf "$backup_dir/rag-documents.tgz" -C "$data_dir" documents
    fi
)

postgres_size="$(wc -c < "$backup_dir/postgres.dump" | tr -d ' ')"
rag_vectorstore_present=false
[ -f "$backup_dir/rag-vectorstores.tgz" ] && rag_vectorstore_present=true
rag_documents_present=false
[ -f "$backup_dir/rag-documents.tgz" ] && rag_documents_present=true
redis_backup_present=false
[ -d "$backup_dir/redis-data" ] && redis_backup_present=true

cat > "$backup_dir/backup-summary.json" <<EOF
{
  "version": "zhixing_backup_summary.v1",
  "backup_id": "$backup_id",
  "created_at_utc": "$stamp",
  "path_echoed": false,
  "filename_echoed": false,
  "postgres_backup": {
    "status": "passed",
    "size_bytes": $postgres_size,
    "catalog_probe": "passed"
  },
  "redis_backup": {
    "status": "$redis_backup_present"
  },
  "rag_vectorstore_backup": {
    "status": "$rag_vectorstore_present"
  },
  "rag_documents_backup": {
    "status": "$rag_documents_present"
  }
}
EOF

if [ "$PRUNE_OLD" = "1" ]; then
    find "$BACKUP_ROOT" -maxdepth 1 -type d -name 'm1-backup-*' -mtime +"$RETENTION_DAYS" -exec rm -rf {} \;
fi

echo "backup_created=true"
echo "postgres_backup=passed"
echo "postgres_backup_size_bytes=$postgres_size"
echo "postgres_catalog_probe=passed"
echo "redis_backup=$redis_backup_present"
echo "rag_vectorstore_backup=$rag_vectorstore_present"
echo "rag_documents_backup=$rag_documents_present"
