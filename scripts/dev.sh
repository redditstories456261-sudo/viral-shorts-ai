#!/usr/bin/env bash
# Local development: build and start the full Viral Shorts AI stack with Docker.
#
# Usage:
#   ./scripts/dev.sh            # GPU build (needs NVIDIA GPU + Container Toolkit)
#   CPU_ONLY=1 ./scripts/dev.sh # CPU-only build (no GPU needed, slower transcription)
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: 'docker' is not installed." >&2
  echo "Install Docker Desktop (https://docs.docker.com/get-docker/) or Docker Engine, then re-run." >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: 'docker compose' (v2 plugin) is not available." >&2
  echo "Upgrade Docker to a version that bundles Compose v2, then re-run." >&2
  exit 1
fi

# CPU-only override: compose file defines a 'cpu' profile for the worker that
# skips the NVIDIA runtime. GPU machines simply ignore this flag.
COMPOSE_ARGS=()
if [ "${CPU_ONLY:-0}" = "1" ]; then
  echo "CPU-only mode requested: starting the worker without GPU access."
  echo "(Transcription will be much slower - fine for smoke tests, not for production.)"
  COMPOSE_ARGS+=(--profile cpu)
fi

if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    echo "No .env found - copying .env.example to .env (edit it before production use)."
    cp .env.example .env
  else
    echo "WARNING: no .env or .env.example found; continuing with compose defaults." >&2
  fi
fi

echo "Building and starting services..."
docker compose "${COMPOSE_ARGS[@]}" up --build -d

echo ""
echo "Viral Shorts AI is starting:"
echo "  API:         http://localhost:8000"
echo "  API docs:    http://localhost:8000/docs"
echo "  Health:      http://localhost:8000/api/health"
echo "  Frontend:    http://localhost:3000"
echo ""
echo "Follow logs with:  docker compose logs -f"
echo "Stop everything:   docker compose down"
