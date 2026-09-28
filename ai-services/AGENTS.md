# AI Services Guidance

This file supplements the repository-level `AGENTS.md` for `ai-services/`.

## Service boundaries

- `ai-mode/` is the shared model gateway and the only application service that
  talks to host-managed Ollama. Keep provider-specific details behind
  `ai-mode/ai_mode_service/provider.py`; consumers use the documented HTTP
  contract.
- AI responses are advisory. Failures, missing models, malformed model output,
  and timeouts must not break ordinary CRUD or browsing in consumer services.
- Enforce prompt, schema, response-size, model allow-list, and timeout limits in
  the shared gateway. Never log secrets or unbounded user/model content.
- `agentic-loop/` is a CI harness, not a runtime dependency. Its deterministic
  checks remain authoritative when the optional review model is unavailable.
- `rag-server/` is a Release 1 host process. It calls AI-Mode for embeddings
  and generation, owns its local SQLite index, and must not be added to Docker
  Compose or call Ollama directly.
- `mcp-server/` and `multi-agent-server/` do not yet contain an implemented
  service. Define their contract and integration boundary before adding
  runtime code or Compose dependencies.

## AI-Mode checks

Run from `ai-services/ai-mode/`:

```bash
python -m pip install -e ".[dev]"
python -m compileall ai_mode_service tests examples
python -m ruff check ai_mode_service tests examples
python -m pytest tests
```

Build from the repository root:

```bash
docker build -f ai-services/ai-mode/Dockerfile ai-services/ai-mode
docker compose config --quiet
```

Use injected `httpx` transports to test provider responses and failure modes.
Do not require a live Ollama instance for unit tests.

## RAG checks

Run from `ai-services/rag-server/`:

```bash
python -m pip install -e ".[dev]"
python -m compileall rag_service tests
python -m ruff check rag_service tests
python -m ruff format --check rag_service tests
python -m pytest tests
```

Use fake AI-Mode transports and deterministic vectors. Tests and CI must not
require Ollama, downloaded models, or an existing local index. Do not add a
RAG Dockerfile or Compose service.

## Agentic-loop checks

Run from `ai-services/agentic-loop/`:

```bash
python -m pip install -r requirements.txt pytest
pytest -q
```

When adding a service check, update `services.json`, add or amend the matching
`checks/*.json`, and preserve the PLAN -> ACT -> OBSERVE -> AGENTS -> HUMAN ->
ADAPT reporting sequence. Keep CI summaries useful even when an optional API
key is absent or a target service fails to start.
