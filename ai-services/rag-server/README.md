# TripGenie Shared RAG Server

This is the Release 1 shared Retrieval-Augmented Generation service. It runs
directly on the local host, outside Docker Compose, and exposes grounded
project-knowledge queries to feature backends.

The service:

- ingests only allowlisted repository Markdown and plain-text files;
- stores chunks and vectors in a local SQLite index;
- calls AI-Mode for embeddings and grounded generation;
- searches `shared` plus the caller's requested feature;
- resolves citations from indexed metadata;
- calculates confidence from retrieval scores; and
- returns a fixed insufficient-context response without generation when no
  chunk reaches the configured relevance threshold.

It never calls Ollama directly, crawls the repository, reads feature
databases, or persists generated answers.

RAG is optional to every feature. Ordinary feature CRUD and backend readiness
must remain operational when this process is disabled, stopped, or not ready.
Consumer backends own their own enable flag, base URL, timeout, and public
error mapping.

## Prerequisites

- Python 3.11 or later
- `uv`
- host Ollama
- host AI-Mode on `http://127.0.0.1:8006`
- approved chat model, such as `qwen2.5:0.5b` or the configured alternative
- `nomic-embed-text`

Pull the default models:

```powershell
ollama pull qwen2.5:0.5b
ollama pull nomic-embed-text
```

## Install

From `ai-services\rag-server`:

```powershell
uv sync --extra dev
```

Tests use fake AI-Mode transports and do not require Ollama or downloaded
models.

## Start the host services

Start AI-Mode from `ai-services\ai-mode`:

```powershell
uv sync --extra dev
uv run uvicorn ai_mode_service.app:app --host 127.0.0.1 --port 8006
```

Verify it can see both configured models:

```powershell
Invoke-RestMethod http://127.0.0.1:8006/ready
```

Build the RAG index from `ai-services\rag-server`:

```powershell
uv run python -m rag_service ingest --rebuild
```

Start RAG:

```powershell
uv run python -m rag_service serve
```

Verify the service:

```powershell
Invoke-RestMethod http://127.0.0.1:8011/health
Invoke-RestMethod http://127.0.0.1:8011/ready
```

The default loopback binding is appropriate for native host clients. A feature
backend running in Docker requires a host-reachable bind address and
`http://host.docker.internal:8011`; keep the port blocked from untrusted
networks.

## Query

```powershell
$body = @{
    query = 'What are the Student 1 itinerary data rules?'
    feature = 'student-1'
    top_k = 5
    correlation_id = 'student1-rag-demo'
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri http://127.0.0.1:8011/query `
    -ContentType application/json `
    -Body $body
```

The response contains:

- `answer`
- `confidence_category`
- `insufficient_context`
- index-resolved `citations`
- bounded retrieval counts and maximum score

If no result reaches the minimum relevance score, the service does not call
generation and returns:

```text
There is not enough indexed context to answer this question.
```

## Knowledge sources

[`config/sources.json`](./config/sources.json) is the complete source
allowlist. Each entry declares:

- stable `source_id`
- repository-relative `path`
- display `title`
- owning `feature` or `shared`

See [`knowledge/README.md`](./knowledge/README.md) before contributing a
source. There is no remote ingestion endpoint.

Rebuild behavior:

- validates every path before replacing the active index;
- rejects absolute paths, traversal, environment files, databases, logs,
  generated data, and unsupported extensions;
- reuses compatible embeddings when source content is unchanged;
- removes stale sources omitted from the current manifest; and
- replaces the SQLite file atomically only after a successful build.

Changing `RAG_EMBEDDING_MODEL` makes an existing index incompatible. Rebuild
the index after changing the model.

## Confidence calibration

Confidence is deterministic:

- `high`: maximum retrieval score at least `0.75`
- `medium`: maximum retrieval score at least `0.55`
- `low`: maximum retrieval score at least `0.35`
- `insufficient_context`: no retrieved chunk reaches `0.35`

Automated tests cover each exact boundary. The versioned
[`config/calibration-queries.json`](./config/calibration-queries.json) set
defines the relevant and irrelevant questions used for local evidence with
`nomic-embed-text`. Record observed scores before changing a threshold.
Changing the embedding model invalidates both the index and prior calibration
evidence.

## Environment variables

| Variable | Default |
| --- | --- |
| `RAG_SERVICE_NAME` | `rag-server` |
| `RAG_BIND_HOST` | `127.0.0.1` |
| `RAG_PORT` | `8011` |
| `RAG_AI_MODE_BASE_URL` | `http://127.0.0.1:8006` |
| `RAG_AI_MODE_TIMEOUT_SECONDS` | `120` |
| `RAG_EMBEDDING_MODEL` | `nomic-embed-text` |
| `RAG_SOURCE_MANIFEST` | `config/sources.json` |
| `RAG_INDEX_PATH` | `data/rag.sqlite3` |
| `RAG_DEFAULT_TOP_K` | `5` |
| `RAG_MAX_TOP_K` | `10` |
| `RAG_MIN_RELEVANCE_SCORE` | `0.35` |
| `RAG_MEDIUM_RELEVANCE_SCORE` | `0.55` |
| `RAG_HIGH_RELEVANCE_SCORE` | `0.75` |
| `RAG_MAX_QUERY_CHARS` | `2000` |
| `RAG_MAX_CONTEXT_CHARS` | `12000` (complete grounded prompt budget) |
| `RAG_MAX_ANSWER_CHARS` | `4000` |
| `RAG_MAX_SOURCE_CHARS` | `1000000` |
| `RAG_CHUNK_CHARS` | `1200` |
| `RAG_CHUNK_OVERLAP_CHARS` | `150` |
| `RAG_EMBED_BATCH_SIZE` | `16` |
| `RAG_CITATION_EXCERPT_CHARS` | `240` |

Processes do not load `shared\configuration\.env.example` automatically.

## API

- `GET /health`: always reports process and bounded dependency diagnostics.
- `GET /ready`: returns `200` only when AI-Mode is ready and the local index is
  compatible and non-empty.
- `POST /query`: retrieves context and returns a grounded or
  insufficient-context response.

Stable errors include `VALIDATION_ERROR`, `BAD_GATEWAY`,
`DEPENDENCY_UNAVAILABLE`, `DEPENDENCY_TIMEOUT`, and `INDEX_NOT_READY`.

## Validation

From the repository root:

```powershell
uv run --project ai-services\rag-server --extra dev `
    python -m compileall -q `
    ai-services\rag-server\rag_service `
    ai-services\rag-server\tests

uv run --project ai-services\rag-server --extra dev `
    ruff check ai-services\rag-server\rag_service ai-services\rag-server\tests

uv run --project ai-services\rag-server --extra dev `
    ruff format --check `
    ai-services\rag-server\rag_service `
    ai-services\rag-server\tests

uv run --project ai-services\rag-server --extra dev `
    pytest ai-services\rag-server\tests -q
```

The local SQLite index, virtual environment, caches, and model data are not
committed.
