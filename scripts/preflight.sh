#!/usr/bin/env bash
set -Eeuo pipefail

red()   { printf "\033[31m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
yellow(){ printf "\033[33m%s\033[0m\n" "$*"; }

trap 'red "[preflight] failed at line $LINENO"' ERR

echo "[preflight] checking docker..."
command -v docker >/dev/null || { red "docker not found"; exit 1; }
docker --version

echo "[preflight] checking docker compose..."
docker compose version >/dev/null || { red "docker compose v2 required"; exit 1; }

echo "[preflight] checking repo files..."
test -f infra/docker-compose.yml || { red "infra/docker-compose.yml missing"; exit 1; }
test -f api/alembic.ini || { red "api/alembic.ini missing"; exit 1; }

echo "[preflight] checking env..."
if [[ ! -f .env ]]; then
  yellow ".env missing, run: scripts/bootstrap_env.sh"
  exit 1
fi

echo "[preflight] checking ports..."
check_port() {
  local p="$1"
  if command -v lsof >/dev/null; then
    lsof -iTCP -sTCP:LISTEN -P 2>/dev/null | awk '{print $9}' | grep -q ":$p" && { red "port $p in use"; exit 1; } || true
  elif command -v ss >/dev/null; then
    ss -ltn 2>/dev/null | awk '{print $4}' | grep -q ":$p$" && { red "port $p in use"; exit 1; } || true
  else
    netstat -ltn 2>/dev/null | awk '{print $4}' | grep -q ":$p$" && { red "port $p in use"; exit 1; } || true
  fi
}
for p in 8000 5432 6379; do check_port "$p"; done

# optional arch warning
arch="$(uname -m || true)"
if [[ "$arch" == "arm64" || "$arch" == "aarch64" ]]; then
  yellow "[preflight] running on ARM64; ensure images are multi-arch or set DOCKER_DEFAULT_PLATFORM"
fi

green "[preflight] ok"