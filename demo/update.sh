#!/usr/bin/env bash
# Обновить демо до тега выпуска (или до main): сборка образа и перезапуск.
#   ~/dentpilot-demo/src/demo/update.sh v1.36.0
# Образ собирается на сервере из публичного репозитория — токенов не нужно.
set -euo pipefail
ref="${1:-main}"
cd "$(dirname "$0")/.."
git fetch --tags origin
git checkout --quiet --detach "$ref"
echo "== $(git describe --tags --always) =="
cd demo
profile=()
if grep -q '^TUNNEL_TOKEN=.\+' .env 2>/dev/null; then profile=(--profile tunnel); fi
docker compose "${profile[@]}" up -d --build
docker image prune -f >/dev/null
docker compose ps
