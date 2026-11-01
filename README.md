# CodeTwin — AI Software Repository Intelligence & Verification Platform

> Production-structured multi-agent platform for deep codebase comprehension, AST-verified software digital twinning, autonomous documentation, and sandboxed test generation.

---

## Architecture Overview

```
codetwin/
├── backend/          # FastAPI async backend, AST parsers & Digital Twin builder
├── frontend/         # Next.js 14, React, TypeScript, Tailwind CSS, Monaco Editor
├── agents/           # Multi-agent coordination system (Supervisor, Docs, Tests, Security)
├── intelligence/     # AST-aware chunking, vector embeddings, and Graph RAG
├── sandbox/          # Isolated Docker execution environments for verified testing
├── training/         # Fine-tuning pipelines and synthetic verification benchmarks
├── evaluations/      # Precision, recall, and hallucination metrics
├── tests/            # System and end-to-end integration tests
├── .agents/          # Workspace Antigravity customizations
├── docker/           # Production container recipes (backend, frontend, sandbox)
├── docs/             # Technical architecture and API specifications
├── scripts/          # Development and test automation scripts
├── .env.example      # Environment variables template
├── docker-compose.yml# Multi-container stack (Postgres+pgvector, API, UI)
└── README.md
```

---

## Quickstart

### 1. Prerequisites
- **Python**: 3.10+ (tested on Python 3.14)
- **Node.js**: 18+ (tested on Node v24)
- **Docker** *(optional for sandbox containerization)*

### 2. Backend Setup
```bash
cd backend
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
- API Documentation (Swagger): [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs)
- Health Check: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

### 3. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
- Dashboard: [http://localhost:3000](http://localhost:3000)

### 4. Running with Docker Compose
```bash
docker-compose up --build
```

---

## Verification & Testing
```bash
# Backend unit & integration tests
.\backend\.venv\Scripts\pytest backend/tests tests -v

# Frontend build verification
cd frontend && npm run build
```

---

## Feature Highlights

### Repository Intelligence
| Feature | Endpoint |
|---|---|
| Repository ingestion (GitHub / ZIP / local) | `POST /api/v1/repositories/{github,upload-zip,local}` |
| Digital twin summary, files, symbols, graph | `GET /api/v1/repositories/{id}/{summary,files,symbols,graph}` |
| Incremental re-indexing | `POST /api/v1/repositories/{id}/reindex` |
| Natural-language codebase Q&A (AST-cited) | `POST /api/v1/repositories/{id}/chat` |
| Onboarding guide & business rules | `GET /api/v1/repositories/{id}/{onboarding,business-rules}` |
| Code memory ("why does this exist?") | `GET /api/v1/repositories/{id}/code-memory` |

### Documentation
| Feature | Endpoint |
|---|---|
| Architecture / API / models / module docs | `POST /api/v1/repositories/{id}/docs/generate` |
| README generator (deterministic) | `POST .../docs/generate` with `doc_type: "readme"` |
| Mermaid architecture diagram (deterministic) | `POST .../docs/generate` with `doc_type: "diagram"` |
| Documentation drift detection | `POST /api/v1/repositories/{id}/docs/drift` |
| Section evidence verification | `POST /api/v1/repositories/{id}/docs/verify` |

### Testing & QA
| Feature | Endpoint |
|---|---|
| Test planning & generation (LLM-assisted) | `POST /api/v1/repositories/{id}/tests/{plan,generate}` |
| Full test-generation pipeline (plan→generate→verify→score) | `POST /api/v1/repositories/{id}/tests/pipeline` |
| Test gap / strength analysis | `GET /api/v1/repositories/{id}/tests/strength` |
| Regression test selection | `POST /api/v1/repositories/{id}/tests/select` |
| Sandboxed test execution | `POST /api/v1/repositories/{id}/tests/{test_id}/execute` |
| Self-healing test repair | `POST /api/v1/repositories/{id}/tests/heal` |
| Test failure explainer (deterministic) | `POST /api/v1/repositories/{id}/tests/explain-failures` |

### Security & Risk
| Feature | Endpoint |
|---|---|
| Static security scan (semgrep/bandit/gitleaks/trivy/pip-audit + **built-in regex scanner**) | `POST /api/v1/repositories/{id}/security/analyze` |
| Security dashboard (severity counts) | `GET /api/v1/repositories/{id}/security/dashboard` |
| Sensitive data flow (taint analysis) | `GET /api/v1/repositories/{id}/security/data-flow` |
| Dependency security scan (offline CVE advisory database) | `GET /api/v1/repositories/{id}/security/dependencies` |

### Impact & Prediction
| Feature | Endpoint |
|---|---|
| Change impact analysis | `POST /api/v1/repositories/{id}/impact-analysis` |
| API breaking-change detection | `POST /api/v1/repositories/{id}/breaking-changes` |
| What-if change simulation | `POST /api/v1/repositories/{id}/whatif/simulate` |
| Bug investigation with MRE sketch | `POST /api/v1/repositories/{id}/bugs/investigate` |

### Health & Reporting
| Feature | Endpoint |
|---|---|
| Production readiness score (release gating) | `GET /api/v1/repositories/{id}/readiness` |
| Code health score (maintenance-focused, 6 dimensions) | `GET /api/v1/repositories/{id}/code-health` |
| Technical debt analysis | `GET /api/v1/repositories/{id}/technical-debt` |
| Git history & hotspots | `GET /api/v1/repositories/{id}/history-analysis` |
| PR description generation | `POST /api/v1/repositories/{id}/pr/describe` |

### Multi-Agent Orchestration
| Feature | Endpoint |
|---|---|
| Intent-routed dispatch to specialist agents | `POST /api/v1/repositories/{id}/ask/orchestrate` |

---

## Reliability Design Notes

- **No external-tool dependency for baseline results.** The security analyzer ships a
  built-in regex scanner (`builtin` tool tag) so scans always return a signal, even
  when semgrep/bandit/gitleaks/trivy/pip-audit are not installed.
- **Deterministic services.** Code health, dependency security, Mermaid diagrams, and
  README generation are LLM-free: identical inputs produce identical outputs.
- **Offline advisory database.** Dependency scanning requires no network access and
  never silently fails open.
- **Screened test execution without Docker.** Generated tests are untrusted model
  output. When Docker is unavailable, `GeneratedTestSafetyScreen`
  (`sandbox/policies.py`) blocks subprocess/network/process/file-destruction/`eval`
  constructs before any host execution; `SANDBOX_HOST_FALLBACK=disabled` refuses
  host execution entirely and misconfigured values fail closed.
- **Frontend↔backend contract test.** `backend/tests/test_frontend_api_contract.py`
  statically compares every URL in `frontend/services/*.ts` with the live FastAPI
  route table, so route renames cannot silently break the UI with 404s.
- **Explicit limitations.** Every analysis response carries a `limitations` field so
  consumers know what the analysis cannot prove.

