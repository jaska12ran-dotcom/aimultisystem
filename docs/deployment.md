# Deployment notes (audited)

## Current stack

`docker-compose.yml` defines PostgreSQL 16 with pgvector image, FastAPI backend, and Next.js frontend. Backend image installs `backend/requirements.txt`; frontend image is `docker/Dockerfile.frontend`. Local defaults use SQLite, storage under `backend/storage`, API port 8000, frontend port 3000, and `DEFAULT_LLM_PROVIDER=mock` unless overridden. `.env.example` documents optional OpenAI/Ollama values.

The Compose database URL switches to PostgreSQL, but application models persist vector embeddings in JSON fields and do not define a pgvector type. PostgreSQL compatibility is configured; pgvector-backed similarity search was not verified. Database schema setup uses SQLAlchemy `create_all`, not migrations.

## Required before deployment

1. Add authentication, authorization, and tenant/repository isolation; disable local filesystem ingestion in hosted deployments.
2. For untrusted repositories, set `SANDBOX_HOST_FALLBACK=disabled` or make Docker/another isolation runtime mandatory and validate the sandbox image. Without Docker the default `screened` mode refuses dangerous constructs but is a pattern-based heuristic, not isolation.
3. Replace default database credentials with managed secrets; remove public DB port exposure unless explicitly required; use TLS/reverse proxy, request limits, and rate limits.
4. Frontend ingestion routes now match the backend (`/clone`, `/upload`); keep them aligned via `backend/tests/test_frontend_api_contract.py`.
5. Add schema migrations, backup/restore procedures, health/readiness checks, and retention controls for uploaded repositories and generated artifacts.
6. Bound uploads while receiving data, use collision-resistant temporary files, and bound CPU/memory/concurrency for synchronous ingest and analysis.
7. Review LLM provider data handling, redact secrets, set timeouts and token limits, and validate output claims before presenting them as verified.
8. Set production `NEXT_PUBLIC_API_URL` to a browser-reachable API origin. The `localhost` default works only when browser and API share the expected host/network.

## Environment variables in use

| Variable | Use | Notes |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy async connection | SQLite default; Compose constructs PostgreSQL URL |
| `STORAGE_DIR`, `REPOS_DIR`, `UPLOADS_DIR` | Persistent and temporary repository storage | Directories are created at config import |
| `DOCKER_SANDBOX_ENABLED` | Declared setting | Not consulted by `sandbox/runner.py`; Docker is auto-detected, and host fallback is governed by `SANDBOX_HOST_FALLBACK` instead |
| `SANDBOX_HOST_FALLBACK` | Host-fallback policy when Docker is unavailable | `screened` (default) runs only statically screened generated tests; `disabled` fails closed; unrecognized values fail closed |
| `EXECUTION_TIMEOUT_SECONDS` | Declared setting | Runner uses `SandboxPolicy` timeout; this setting is not wired into it |
| `OPENAI_API_KEY`, `OPENAI_API_BASE`, `OLLAMA_API_BASE`, `DEFAULT_LLM_PROVIDER`, `LLM_MODEL` | LLM provider selection/config | No provider health/readiness validation; default provider is mock |
| `NEXT_PUBLIC_API_URL` | Browser API base URL | Inlined into frontend at build/runtime according to Next configuration |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Compose database bootstrap | Compose currently has insecure development defaults |

## Validation status

Compose YAML parsed successfully with PyYAML. Docker CLI/engine was absent in the audit environment, so Compose interpolation, image builds, service startup, health checks, sandbox image availability, and runtime isolation remain unverified. Do not treat this repository's Compose file as production validated.
