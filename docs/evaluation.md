# Evaluation and verification

## Existing evaluation code

`evaluations/metrics/core.py` computes task-level exact-match/token-F1, evidence precision/recall, change-impact and security counts, test pass rate, coverage delta, mutation score, unsupported-claim rate, and task success rate. The runner and benchmark catalog live in `evaluations/runners/` and `evaluations/benchmarks/catalog.json`. These are metric/reporting utilities; no benchmark was run during this audit, and their existence is not evidence of product quality.

## Existing test coverage

- Backend tests cover API health/ingestion, archive/path validation, AST parsing, graph, retrieval, impact, Git history, documentation, security normalization, agents, and test pipeline behavior.
- Root tests cover system structure and sandbox command policy/result parsing.
- There is no frontend `test` script and no configured frontend unit, component, or browser test framework in `frontend/package.json`.
- Integration/API tests use SQLite fixtures; PostgreSQL/pgvector behavior is not covered by the executed suite.
- Host-executed generated code is now statically screened (`GeneratedTestSafetyScreen` in `sandbox/policies.py`) and can be refused entirely with `SANDBOX_HOST_FALLBACK=disabled`; see [security.md](security.md). The screen is heuristic and does not replace Docker isolation.
- `backend/tests/test_frontend_api_contract.py` statically compares frontend service URLs with the live FastAPI route table (this covers the previously recommended endpoint-contract checks for `apiService`/`intelligenceApi`).

## Audit commands and results (2026-10-11)

| Check | Command | Result |
|---|---|---|
| Backend unit/integration/API suite | `python -m pytest backend/tests tests -q --basetemp=.pytest-tmp -p no:cacheprovider` | **PASS**: 74 passed, 8 warnings, 48.31s |
| Initial pytest attempt | `python -m pytest backend/tests tests -q` | Environment-limited: 46 passed, 28 setup errors due to denied Windows temp path; successful rerun used workspace temp |
| Frontend lint | `npm run lint` in `frontend/` | **PASS with warnings**: 0 errors, 5 warnings |
| Frontend production build | `npm run build` in `frontend/` | **PASS**: compile, TypeScript, and static page generation completed |
| Python syntax compilation | `python -m compileall -q backend/app agents intelligence sandbox evaluations` | **PASS** |
| App import and route registration | Import `app.main`, enumerate FastAPI routes | **PASS**: import succeeded and route table generated |
| Docker Compose parse | `yaml.safe_load(docker-compose.yml)` | **PASS**: YAML parses and defines backend/db/frontend |
| Docker Compose validation/build/runtime | `docker compose config` and image/runtime checks | **UNVERIFIED**: Docker CLI is not installed |
| Frontend tests | No configured test script/framework | **NOT AVAILABLE** |
| Ruff, mypy, Bandit, pip-audit | Availability checked | **NOT RUN**: tools are absent/not configured |
| Full security scanner run | Semgrep/Bandit/Gitleaks/Trivy or equivalent | **NOT RUN**: no full repository scan was performed |
| PostgreSQL integration | Runtime against Compose DB | **UNVERIFIED** |
| Evaluation benchmark | `evaluations/` runner | **NOT RUN** |

Warnings from pytest include `datetime.utcnow()` deprecations and collection of `TestGenerationPipeline` as a non-test class; they did not fail the suite. Frontend lint warnings are unused imports/value and one React hook dependency warning in `RepositoryDashboard.tsx`.

## Verification update (2026-10-19)

| Check | Command | Result |
|---|---|---|
| Backend suite | `python -m pytest backend/tests -q` | **PASS**: 110 passed (~75s) |
| Root suite | `python -m pytest tests -q` | **PASS**: 16 passed |
| Frontend typecheck | `npx tsc --noEmit` in `frontend/` | **PASS**: clean |
| Frontend production build | `npm run build` in `frontend/` | **PASS**: routes `/`, `/app` prerendered |
| API contract scan | part of backend suite | **PASS**: all frontend service URLs resolve to registered routes |
| Generated-test safety | `backend/tests/test_generated_test_safety.py` | **PASS**: dangerous constructs blocked on host fallback; `disabled` policy fails closed |
| Security scan performance | live measurement against an ingested 119-file repo | **PASS**: security/dashboard 2.3s (was ~56s); code-health 2.0s |

The safety-screen tests intentionally exercise the no-Docker host path by monkeypatching Docker detection. PostgreSQL/pgvector integration, Docker sandbox runtime, and benchmark evaluation remain unverified in this environment.

## Recommended evaluation additions

- Add frontend tests for each `intelligenceApi`/`apiService` endpoint contract; include upload and Git clone paths.
- Run PostgreSQL integration and migration tests.
- Add adversarial tests for upload filename traversal/collision, streaming-size enforcement, path policy, unauthenticated access, concurrent test execution, and prompt injection.
- Score each generated claim against exact repository evidence; distinguish citation presence from claim support.
- Run held-out evaluation benchmarks with recorded dataset version, model/provider, prompt version, and reproducible outputs.
- Run dependency and source scanners in CI and retain machine-readable reports.
