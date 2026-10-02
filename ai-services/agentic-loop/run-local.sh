#!/usr/bin/env bash
# Set up and run the agentic loop locally, end to end:
#   venv + deps -> Ollama models -> Compose (services + AI-Mode) -> MCP -> RAG
#   -> the loop's menu (Services / MCP / RAG / CI).
#
#   bash ai-services/agentic-loop/run-local.sh
#
# Safe to re-run: anything already up is reused. MCP, RAG and Ollama started
# here are stopped when the loop exits; Compose keeps running (stop it with
# `docker compose down`). Logs go to ai-services/agentic-loop/reports/logs/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOOP="$ROOT/ai-services/agentic-loop"
LOGS="$LOOP/reports/logs"
mkdir -p "$LOGS"
cd "$ROOT"

started=()
cleanup() {
  for pid in "${started[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT

wait_for() { # name url attempts
  printf 'Waiting for %s' "$1"
  for _ in $(seq 1 "$3"); do
    if curl -fsS "$2" >/dev/null 2>&1; then echo " ok"; return 0; fi
    printf '.'; sleep 2
  done
  echo " not ready ($2) -- see $LOGS"; return 1
}

echo "== Python environment"
if [ ! -x .venv/bin/python ]; then
  command -v python3.11 >/dev/null || { echo "python3.11 is required"; exit 1; }
  python3.11 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r ai-services/agentic-loop/requirements.txt pytest \
  -e ai-services/mcp-server -e ai-services/rag-server

echo "== Ollama"
command -v ollama >/dev/null || { echo "Install Ollama first: https://ollama.com"; exit 1; }
if ! curl -fsS http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  ollama serve >"$LOGS/ollama.log" 2>&1 &
  started+=($!)
  wait_for Ollama http://127.0.0.1:11434/api/version 15
fi
ollama pull nomic-embed-text
ollama pull qwen2.5:0.5b

echo "== Compose: every service plus AI-Mode"
AI_MODE_DEFAULT_MODEL=qwen2.5:0.5b docker compose \
  -f docker-compose.yml -f ai-services/agentic-loop/docker-compose.agentic.yml \
  up -d --build

# Student 3 is published on 8003 by the overlay, not the MCP default of 18003.
export MCP_STUDENT_3_URL=http://127.0.0.1:8003

echo "== MCP server"
if ! curl -fsS http://127.0.0.1:8012/ready >/dev/null 2>&1; then
  python -m tripgenie_mcp serve >"$LOGS/mcp.log" 2>&1 &
  started+=($!)
  wait_for MCP http://127.0.0.1:8012/ready 20
fi

# RAG generation goes through AI-Mode's /generate, which needs MCP (above) and
# the models (pulled above).
echo "== RAG server"
wait_for AI-Mode http://127.0.0.1:8006/ready 60
if ! curl -fsS http://127.0.0.1:8011/ready >/dev/null 2>&1; then
  python -m rag_service ingest --rebuild >"$LOGS/rag-ingest.log"
  python -m rag_service serve >"$LOGS/rag.log" 2>&1 &
  started+=($!)
  wait_for RAG http://127.0.0.1:8011/ready 20
fi

[ -n "${ANTHROPIC_API_KEY:-}" ] || echo "Note: no ANTHROPIC_API_KEY -- the agent sections will print 'unavailable'; the checks still run."

echo "== Agentic loop (Ctrl-C or 0 to exit; MCP and RAG stop with it)"
cd "$LOOP"
export SERVICES="shared student-1 student-2 student-3 student-4 student-5"
while true; do
  python agentic_loop.py || true
  read -r -p "Run another mode? [y/N] " again
  [[ "$again" =~ ^[Yy] ]] || break
done
