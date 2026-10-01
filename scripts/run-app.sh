#!/usr/bin/env bash
# Run the whole Release 1 application locally:
#   Compose (every feature's frontend, backend, database)
#   + on the host: Ollama -> AI-Mode :8006 -> MCP :8012 -> RAG :8011
#
#   bash scripts/run-app.sh                      # llama3.1:8b (the demo model)
#   AI_MODEL=qwen2.5:0.5b bash scripts/run-app.sh   # small and quick, weak answers
#
# AI-Mode, MCP and RAG must not be containers (Release 1 rule), so this script
# runs them as host processes; the Compose backends reach them through
# host.docker.internal. Ctrl-C stops the host services; the containers keep
# running (`docker compose down` stops them). Follows
# docs/reports/release-1/local-host-services-runbook.md for macOS/Docker
# Desktop, where 127.0.0.1 bindings are reachable from containers.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="${TMPDIR:-/tmp}/tripgenie-logs"
AI_MODEL="${AI_MODEL:-llama3.1:8b}"
ENV_FILE="shared/configuration/.env.example"
mkdir -p "$LOGS"
cd "$ROOT"

started=()
cleanup() {
  echo
  echo "Stopping host services (containers keep running)."
  for pid in "${started[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT

up() { curl -fsS -m 3 "$1" >/dev/null 2>&1; }

wait_for() { # name url attempts
  printf 'Waiting for %s' "$1"
  for _ in $(seq 1 "$3"); do
    if up "$2"; then echo " ok"; return 0; fi
    printf '.'; sleep 2
  done
  echo " not ready ($2) -- see $LOGS"; exit 1
}

echo "== Python environment (.venv)"
if [ ! -x .venv/bin/python ]; then
  command -v python3.11 >/dev/null || { echo "python3.11 is required"; exit 1; }
  python3.11 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -e ai-services/ai-mode -e ai-services/mcp-server -e ai-services/rag-server

echo "== Ollama ($AI_MODEL + nomic-embed-text)"
command -v ollama >/dev/null || { echo "Install Ollama first: https://ollama.com"; exit 1; }
if ! up http://127.0.0.1:11434/api/version; then
  ollama serve >"$LOGS/ollama.log" 2>&1 &
  started+=($!)
  wait_for Ollama http://127.0.0.1:11434/api/version 15
fi
ollama pull nomic-embed-text
ollama pull "$AI_MODEL"

# First, so --remove-orphans clears an AI-Mode container left by an older
# Compose file before the host AI-Mode needs its port.
echo "== Compose: all feature services"
docker compose --env-file "$ENV_FILE" up --build -d --remove-orphans

echo "== AI-Mode :8006"
if up http://127.0.0.1:8006/health; then
  # Something already serves 8006. Reuse it only if it is the current AI-Mode.
  curl -fsS http://127.0.0.1:8006/openapi.json | grep -q generate-plain || {
    echo "Port 8006 is held by an old AI-Mode (no /generate-plain). Stop it, e.g.:"
    echo "  docker ps --filter publish=8006"
    exit 1
  }
else
  AI_MODE_DEFAULT_MODEL="$AI_MODEL" \
  AI_MODE_ALLOWED_MODELS="qwen2.5:0.5b,llama3.1:8b" \
  AI_MODE_DEFAULT_EMBEDDING_MODEL=nomic-embed-text \
  AI_MODE_TIMEOUT_SECONDS=90 \
  AI_MODE_MCP_URL=http://127.0.0.1:8012/mcp \
    python -m uvicorn ai_mode_service.app:app --host 127.0.0.1 --port 8006 \
    >"$LOGS/ai-mode.log" 2>&1 &
  started+=($!)
  wait_for AI-Mode http://127.0.0.1:8006/health 30
fi

echo "== MCP :8012"
if ! up http://127.0.0.1:8012/ready; then
  # The host ports Compose publishes each feature backend on (Student 2's
  # default, 127.0.0.1:9000, already matches).
  MCP_STUDENT_1_URL=http://127.0.0.1:18001 \
  MCP_STUDENT_3_URL=http://127.0.0.1:18003 \
  MCP_STUDENT_4_URL=http://127.0.0.1:18008 \
  MCP_STUDENT_5_URL=http://127.0.0.1:18005 \
    python -m tripgenie_mcp serve >"$LOGS/mcp.log" 2>&1 &
  started+=($!)
  wait_for MCP http://127.0.0.1:8012/ready 20
fi

echo "== RAG :8011 (index rebuild reuses unchanged chunks)"
if ! up http://127.0.0.1:8011/ready; then
  (cd ai-services/rag-server && python -m rag_service ingest --rebuild) >"$LOGS/rag-ingest.log"
  (cd ai-services/rag-server && exec python -m rag_service serve) >"$LOGS/rag.log" 2>&1 &
  started+=($!)
  wait_for RAG http://127.0.0.1:8011/ready 20
fi

cat <<EOF

TripGenie is running. Logs: $LOGS

  Landing page             http://localhost:8080
  Student 1 trips          http://localhost:8081
  Student 2 accommodation  http://localhost:9003
  Student 3 transport      http://localhost:8093
  Student 4 activities     http://localhost:8084
  Student 5 budgets        http://localhost:8085

  AI-Mode http://127.0.0.1:8006 · MCP http://127.0.0.1:8012/mcp · RAG http://127.0.0.1:8011

Ctrl-C stops AI-Mode, MCP and RAG. Stop the containers with: docker compose down
EOF
wait
