# Student 1 Release 0 Compose Smoke Guide

This guide documents the Release 0 Student 1/shared AI Compose smoke flow added
for issue #14.

## 1. What the routine smoke proves

Routine CI now runs two deterministic phases against a unique Compose project:

1. **Degraded host-Ollama phase**
   - starts only `shared-ui`, `student-1-frontend`, `student-1-backend`,
     `student-1-database`, and `ai-mode`
   - forces `ai-mode` to observe an unavailable host provider
   - proves Student 1 CRUD startup still works while shared AI is degraded
2. **Fake host Ollama transport-contract phase**
   - starts a tiny host-side Ollama-compatible HTTP process on port `11434`
   - verifies shared `ai-mode` `/health` and `/ready`
   - verifies a minimal Student 1 suggestion path without downloading a real
     model

The fake host phase is **transport-contract CI only**. It does **not** prove
real Ollama quality, model availability outside the fake process, or live model
behaviour.

## 2. Local prerequisites

- Docker with `docker compose`
- Python 3.11+ for the helper scripts
- Host ports `8080`, `8081`, and optionally `11434` available

For **manual live host Ollama evidence**, also ensure:

```bash
ollama serve
ollama pull qwen2.5:0.5b
curl http://localhost:11434/api/tags
```

Release 0 keeps Ollama on the **host machine only**. Do not add an Ollama
container for this workflow.

## 3. Routine local smoke command

Use the same sequence as CI:

```bash
docker compose -p tripgenie14-local --env-file shared/configuration/.env.example config --format json > compose-config.json
python scripts/test/validate_compose_config.py compose-config.json
docker compose -p tripgenie14-local --env-file shared/configuration/.env.example build shared-ui student-1-frontend student-1-backend student-1-database ai-mode
python scripts/test/run_student1_compose_smoke.py --project-name tripgenie14-local
```

The smoke script generates per-phase env overrides, uses a unique Compose
project for isolation, and always tears down only that project plus its named
volume in `finally`, even after failures.

## 4. Manual live host Ollama evidence

If you already have real host Ollama bound on `11434`, run only the live phase:

```bash
python scripts/test/run_student1_compose_smoke.py --phase live-host-ollama
```

This avoids the fake transport phase trying to bind the same port.

## 5. Expected evidence

The smoke flow should verify:

- shared portal `http://localhost:8080` returns `200` and keeps the Student 1
  `http://localhost:8081` route
- Student 1 frontend `http://localhost:8081` returns `200`
- seeded trip and itinerary content flows through frontend -> backend -> database
- Student 1 database internal health returns `200`
- Student 1 backend `/ready` stays database-only and returns `200` while CRUD is
  available
- backend/database/ai-mode remain internal-only and do not publish host ports
- representative Student 1 CRUD works through frontend form endpoints and is
  verified again via backend API responses
- unavailable host-Ollama behaviour is explicit while CRUD still works
- fake transport success returns draft AI suggestions without persisting them

On smoke failure, the script prints a concise `docker compose ps` plus logs for
only the smoke services.

## 6. Current limitations

- Routine CI does **not** download or run a real Ollama model.
- The fake host process proves the HTTP transport contract only; it is not live
  Ollama evidence.
- The smoke path intentionally starts only shared UI, Student 1, and shared
  `ai-mode`; Student 2-5 definitions stay in Compose but are not started.
- GitHub-hosted runners are suitable for the routine degraded/fake phases; live
  host-Ollama evidence generally needs a manual or self-hosted environment where
  host Ollama is already installed and reachable.
