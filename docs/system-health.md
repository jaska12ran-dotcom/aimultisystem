# CodeTwin system health report

**Audit date:** 2026-10-11  
**Overall status:** **NOT PRODUCTION READY**  
**Scope:** Existing backend, frontend, AI-related code, persistence, ingestion, execution, security, Git analysis, tests, and deployment files. This audit documents and does not rewrite the application.

## Executive assessment

The repository is a functioning prototype with a substantial FastAPI/SQLAlchemy backend, repository ingestion and twin indexing, graph/retrieval/change-impact/Git services, several agent-style workflows, and a Next.js dashboard. Backend/API integration tests and frontend production build pass in this environment. The main execution boundary is not safe: generated tests execute directly on the backend host whenever Docker is unavailable. API routes are unauthenticated, ingestion upload handling has a filename/path and resource-limit problem, and the frontend GitHub/ZIP upload clients call routes the backend does not provide. Several advertised AI agents are documentation-only claims, not implemented agents. Docker runtime and full security scans could not be verified.

## Component status

| Area | Status | Evidence-based assessment |
|---|---|---|
| FastAPI | Implemented; tests pass | Route table imports and registers; API/integration suite passes |
| Database | Partial | Async SQLAlchemy, SQLite tests, PostgreSQL URL support; no migrations, native vector column, or PostgreSQL run |
| Authentication | Missing | No auth/ownership dependencies found; repository endpoints are publicly callable if network-reachable |
| Repository ingestion | Implemented with gaps | Local/ZIP/Git flows; upload filename, collision, byte-limit, and local-path policy issues |
| AST/parsing | Partial | Python AST with fallback; JS/TS and other languages rely substantially on regex recognizers |
| Graph | Implemented | NetworkX graph derived from database records |
| RAG | Implemented in deterministic/basic form | SQL-backed retrieval/token hashing and evidence records; no verified semantic vector backend |
| AI agents | Partial | Documentation, QA, test and security classes; no Supervisor, standalone Explorer/Architecture/Code Review agents |
| Sandbox | Unsafe fallback | Docker path is constrained; Docker-missing path executes generated tests on host |
| Git analysis | Implemented | Clone metadata, commits, history analysis and why endpoint; Git clone host allowlist present |
| Frontend dashboard | Implemented, limited | Dashboard, repository selection, file viewing, docs, tests, security, architecture/graph, impact, Git sections |
| Frontend ingestion | Broken for two sources | GitHub and ZIP UI URLs differ from backend routes |
| Frontend automated tests | Not configured | No npm test script or UI/browser test framework |
| Docker deployment | Unverified | YAML parses; Docker CLI unavailable; unsafe defaults need hardening |

## Priority findings

1. **Critical — host code execution:** generated test code can reach `subprocess.run` on the backend host on the no-Docker branch. Enforce an isolation runtime and fail closed.
2. **Critical when remotely reachable — no auth:** local path ingestion, file reads, generated code execution, and repository deletion are unauthenticated.
3. **High — upload path/resource handling:** raw multipart filename is used to create a temp file before validation; same-name uploads collide, and size validation occurs after copy.
4. **High — frontend contract break:** frontend calls `/repositories/github` and `/repositories/upload-zip`; backend exposes `/repositories/clone` and `/repositories/upload`.
5. **High — AI trust:** repository text is untrusted prompt context; free-form LLM claims are not checked claim-by-claim against citations.
6. **Medium — validator defect:** protected local path rejection is inside a broad exception handler that suppresses the raised policy error; containment uses string prefix matching.
7. **Medium — deployment configuration:** Compose has predictable development DB credentials and exposes PostgreSQL; authentication, migrations, and runtime isolation are absent.
8. **Low — health check can mask a dependency failure:** `/health` always returns `status: healthy` even when its database query fails; only the separate `database` field reports the failure.

## Verification results

- Backend unit, integration, and API tests: **74 passed**, 8 warnings (rerun with workspace-scoped pytest temp directory).
- Frontend lint: **0 errors**, 5 warnings.
- Frontend production build: **passed**, including TypeScript and static page generation.
- Python `compileall`: **passed**.
- FastAPI app import and route enumeration: **passed**.
- Compose YAML syntax parse: **passed**.
- Docker validation, image builds, and live services: **unverified** (Docker is not installed).
- Frontend tests: **not available** (no test script/framework configured).
- Dedicated Bandit, Semgrep, Gitleaks, Trivy, pip-audit, Ruff, and mypy runs: **not performed** (tools absent/not configured).
- PostgreSQL runtime, full benchmark evaluation, prompt-injection red-team checks, and live browser/API integration: **unverified**.

The initial pytest attempt had 28 fixture setup errors because Windows denied the default temp location; 46 other tests passed. The rerun used `--basetemp=.pytest-tmp -p no:cacheprovider` inside the workspace and passed all 74 tests. Full command details are in [evaluation.md](evaluation.md).

## Status update (2026-10-19)

Changes since the audit; the original findings above are kept as the audit record.

- **Priority 1 (host code execution) — mitigated, not eliminated.** The no-Docker path is now
  governed by `SANDBOX_HOST_FALLBACK`: `screened` (default) statically blocks
  subprocess/network/process/file-destruction/`eval` constructs before host execution, and
  `disabled` fails closed; unrecognized values fail closed. Regression tests:
  `backend/tests/test_generated_test_safety.py`. Docker remains the only true isolation and is
  still recommended for untrusted repositories.
- **Priority 4 (frontend contract break) — resolved.** `frontend/services/api.ts` now calls
  `/repositories/clone` and `/repositories/upload`, and
  `backend/tests/test_frontend_api_contract.py` compares every frontend service URL against the
  live FastAPI route table.
- **AI agents row — Supervisor now exists.** `agents/orchestrator.py::OrchestratorAgent` routes
  queries to specialist services and is exposed at `POST /repositories/{repo_id}/ask/orchestrate`
  (keyword-based intent routing; no learned planner).
- **Verification results now:** `python -m pytest backend/tests -q` → **110 passed**;
  `python -m pytest tests -q` → **16 passed**; frontend production build → **passed** with routes
  `/` (landing) and `/app` (dashboard); frontend typecheck (`npx tsc --noEmit`) → **clean**.
- Priorities 2, 3, 5, 6, 7, and 8 remain open as described above (authentication, upload temp-file
  handling, AI trust, local-path validator, deployment defaults, `/health` masking).

## Decision

Do not represent the current system as production-ready. Production use should wait until the execution fallback is removed, API access is authenticated and authorized, upload/path handling is fixed, frontend routes are aligned, and deployment plus security validation runs in a Docker-enabled CI environment. The findings and runtime limits are detailed in [security.md](security.md), [deployment.md](deployment.md), and [api.md](api.md).
