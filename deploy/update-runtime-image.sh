#!/usr/bin/env sh
set -eu

APP_IMAGE="${APP_IMAGE:-langgraph-travel-planner-backend:latest}"
BASE_IMAGE="${BASE_IMAGE:-zhixing-backend-base:$(date +%Y%m%d%H%M%S)}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"
PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST:-pypi.org}"
AIGOHOTEL_MCP_VERSION="${AIGOHOTEL_MCP_VERSION:-0.3.1}"

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
