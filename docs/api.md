# API reference (audited)

Base path: `/api/v1`. FastAPI OpenAPI is exposed at `/api/v1/openapi.json`; Swagger UI is `/api/v1/docs`. The routes below are mounted by `backend/app/api/v1/router.py` and the endpoint modules. Request/response details are defined in `backend/app/schemas/`.

## Health

| Method | Path | Behavior |
|---|---|---|
| GET | `/health` | Returns process and database health data; response `status` remains `healthy` even when the database probe fails (inspect `database`) |
| GET | `/` | Basic service status and docs path |

## Repository lifecycle

| Method | Path | Behavior |
|---|---|---|
| GET | `/repositories` | List repositories |
| GET | `/repositories/{repo_id}` | Read repository metadata |
| POST | `/repositories/local` | Ingest a local server-side directory; JSON `path`, optional `name` |
| POST | `/repositories/clone` | Clone an allowlisted Git host; JSON `url`, optional `branch`, `name` |
| POST | `/repositories/upload` | Upload a multipart ZIP field named `file` |
| DELETE | `/repositories/{repo_id}` | Delete repository record and managed workspace |
| POST | `/repositories/{repo_id}/analyze` | Run repository analysis |

Local-path ingestion is a server-side filesystem capability and must not be exposed to untrusted callers. There is no authentication or repository-level authorization in the audited routes.

## Twin, graph, retrieval, Git, and impact

| Method | Path | Behavior |
|---|---|---|
| GET | `/repositories/{repo_id}/tree` | Directory tree |
| GET | `/repositories/{repo_id}/summary` | Twin counts and language/symbol/commit summary |
| GET | `/repositories/{repo_id}/files` | File metadata and optional filters |
| GET | `/repositories/{repo_id}/folders` | Folder metadata |
| GET | `/repositories/{repo_id}/symbols` | Extracted symbols |
| GET | `/repositories/{repo_id}/dependencies` | Manifest dependencies |
| GET | `/repositories/{repo_id}/commits` | Indexed commits |
| GET | `/repositories/{repo_id}/relationships` | Stored code relationships |
| GET | `/repositories/{repo_id}/graph` | Graph nodes and relationships |
| GET | `/repositories/{repo_id}/file-content?path=...` | Read file from repository workspace |
| POST | `/repositories/{repo_id}/index` | Index repository for retrieval |
| POST | `/repositories/{repo_id}/search` | Search indexed repository context |
| POST | `/repositories/{repo_id}/ask` | Repository retrieval question endpoint |
| POST | `/repositories/{repo_id}/impact-analysis` | Analyze change impact for a symbol |
| GET | `/repositories/{repo_id}/history-analysis` | Git history analysis |
| POST | `/repositories/{repo_id}/history/why` | Evidence-backed Git rationale query |
| GET | `/repositories/{repo_id}/symbols/{symbol}/callers` | Callers of a symbol |
| GET | `/repositories/{repo_id}/symbols/{symbol}/dependents` | Dependents of a symbol |
| GET | `/repositories/{repo_id}/symbols/{symbol}/relationships` | Related graph edges |

## Agents and quality endpoints

| Method | Path | Behavior |
|---|---|---|
| POST | `/repositories/{repo_id}/chat` | Codebase QA chat |
| POST / GET | `/repositories/{repo_id}/docs/generate`, `/docs` | Generate and list generated docs; `doc_type` accepts `architecture`, `api`, `models`, `module`, `readme`, `diagram` (deterministic Mermaid), or `custom` |
| GET | `/repositories/{repo_id}/docs/{doc_id}` | Read generated doc |
| POST | `/repositories/{repo_id}/docs/verify` | Verify supplied or generated sections |
| POST | `/repositories/{repo_id}/docs/drift` | Detect documentation drift |
| POST | `/repositories/{repo_id}/tests/plan` | Plan tests for a target file/symbol |
| POST | `/repositories/{repo_id}/tests/generate` | Generate and optionally execute a suite |
| POST | `/repositories/{repo_id}/tests/pipeline` | Run test-generation pipeline |
| POST | `/repositories/{repo_id}/tests/{test_id}/execute` | Execute stored suite |
| GET | `/repositories/{repo_id}/tests` | List generated suites |
| GET | `/repositories/{repo_id}/tests/strength` | Test gap and strength analysis from indexed evidence |
| POST | `/repositories/{repo_id}/tests/select` | Select regression tests for a change |
| POST | `/repositories/{repo_id}/tests/heal` | Self-healing repair of failing generated tests |
| POST | `/repositories/{repo_id}/tests/explain-failures` | Deterministic explanation of pytest/unittest output (no execution) |
| POST | `/repositories/{repo_id}/security/analyze` | Run configured security checks; always includes the built-in regex scanner |
| GET | `/repositories/{repo_id}/security/dashboard` | Return a security summary (currently reruns analysis) |
| GET | `/repositories/{repo_id}/security/data-flow` | Sensitive data flow analysis |
| GET | `/repositories/{repo_id}/security/dependencies` | Offline dependency vulnerability scan against a bundled advisory database |
| POST | `/repositories/{repo_id}/ask/orchestrate` | Intent-routed multi-agent dispatch (single entry point) |
| GET | `/repositories/{repo_id}/technical-debt` | Deterministic technical debt (dead code, cycles, duplicate functions, complexity) |
| GET | `/repositories/{repo_id}/readiness` | Production readiness score and grade |
| GET | `/repositories/{repo_id}/code-health` | Deterministic 6-dimension code health score |
| GET | `/repositories/{repo_id}/onboarding` | Onboarding guide |
| GET | `/repositories/{repo_id}/business-rules` | Extracted business rules |
| GET | `/repositories/{repo_id}/code-memory?target=...` | Evidence-backed "why does this exist" for a target |
| GET | `/repositories/{repo_id}/index-status` | Incremental indexing status |
| POST | `/repositories/{repo_id}/reindex` | Incrementally re-index changed files |
| POST | `/repositories/{repo_id}/history/why` | Evidence-backed Git rationale query |
| POST | `/repositories/{repo_id}/pr/describe` | PR description generation |
| POST | `/repositories/{repo_id}/breaking-changes` | API breaking-change detection |
| POST | `/repositories/{repo_id}/bugs/investigate` | Bug investigation with minimal reproduction sketch |
| POST | `/repositories/{repo_id}/whatif/simulate` | What-if change simulation |

## Frontend/backend contract

`frontend/services/api.ts` previously called `POST /repositories/github` (real route: `/repositories/clone`) and `POST /repositories/upload-zip` (real route: `/repositories/upload`), so both UI ingestion paths returned 404. Both call sites now target the implemented routes, and `backend/tests/test_frontend_api_contract.py` statically compares every URL literal in `frontend/services/*.ts` against the live FastAPI route table so this class of mismatch cannot silently return.

## Operational notes

- API routes are unauthenticated; do not expose them to untrusted networks.
- Error responses are not uniformly normalized; some handlers return raw exception text.
- `file-content` performs path checks, but that does not compensate for the missing request authorization boundary.
- Docker deployment settings and actual API behavior must be checked together; the default frontend API URL is `http://localhost:8000/api/v1`.
- The endpoint list was compared to a live FastAPI route table (61 application routes) generated from the imported app on 2026-10-19. Route schemas remain the source of truth for field-level details.
