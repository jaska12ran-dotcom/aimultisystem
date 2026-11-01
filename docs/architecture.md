# CodeTwin architecture (audited)

This document describes the implementation in this repository as inspected on 2026-10-11. It records current behavior rather than the broader product architecture described in older READMEs.

## Runtime components

| Area | Implementation | Current boundary |
|---|---|---|
| HTTP API | FastAPI app in `backend/app/main.py`; routers under `backend/app/api/v1/` | REST only; no WebSocket routes and no authentication dependency found |
| Persistence | SQLAlchemy async models in `backend/app/models/`; SQLite default and PostgreSQL URL support | Startup calls `Base.metadata.create_all`; no migration system or pgvector column is present |
| Ingestion | `IngestionService` coordinates local folder, ZIP, and Git clone ingestion | File scanning, parsing, copying, GitPython and SQL work are called inline from async request handlers |
| Parsing | Python `ast` plus regex/polyglot recognizers and a separate `intelligence/parser` analysis model | Python syntax failures fall back to recognizers; JavaScript/TypeScript parser is regex based, not a full AST parser |
| Twin/graph | Relational file, symbol, import, dependency, commit, and relationship records; NetworkX graph assembled from these | Graph is rebuilt from DB records on query; it is not a separately persisted graph database |
| Retrieval | `backend/app/services/rag/service.py` and `intelligence/retriever.py` | Deterministic token/hash and database retrieval; no production vector database/embedding integration was verified |
| Agents | Documentation, QA, test planning/generation pipeline, and security analysis classes | No supervisor/orchestrator, repository explorer, standalone architecture agent, or code review agent implementation was found |
| Test execution | `sandbox/runner.py` | Docker path has useful container restrictions, but generated tests fall back to host execution when Docker is not on PATH |
| UI | Next.js 16 app with dashboard, ingestion modal, twin modal, repository intelligence sections | Current UI is a single dashboard and modal flow; several ingestion API URLs do not match the backend |

## Main data flow

```text
Next.js dashboard -> FastAPI routes -> async SQLAlchemy session -> repository and artifact tables
                              |-> ingestion: validate -> copy/clone/unpack -> scan -> parse -> persist
                              |-> graph / RAG / Git history / change-impact services
                              |-> documentation, QA, test, and security agent classes
                                           |-> optional LLM provider
                                           |-> generated test runner (Docker when available; host fallback otherwise)
```

The API and model code import and load successfully, and the existing integration tests exercise local SQLite-backed ingestion, retrieval, graph, impact, Git history, documentation, and test workflows. PostgreSQL runtime behavior was not exercised in this audit.

## Persistence and lifecycle

`backend/app/core/config.py` supplies SQLite and storage defaults and creates storage directories at import time. `backend/app/core/database.py` creates an async SQLAlchemy engine, exposes request-scoped sessions, and initializes tables with `create_all`. There are no Alembic migrations or startup schema compatibility checks. Repository files, symbols, imports, dependencies, relationships, Git commits, generated documents, generated suites, and chat messages use SQL tables. Vector chunks store JSON arrays, not a native pgvector column.

Ingestion status fields exist, but the orchestration is request-bound rather than a durable background job queue. Large copies, scanning, archive extraction, subprocess calls, and parts of analysis are synchronous work within async routes and can block the event loop. There is no per-repository execution lock around generated test suite status transitions.

## UI surface

`frontend/components/RepositoryDashboard.tsx` provides the dashboard, repository selection, file view, AI chat, docs, tests, security, architecture/graph, impact, and Git history sections. `TwinViewerModal.tsx` shows overview, detected APIs, models, and commits. These are implemented UI components, but the frontend has no dedicated component-test script or configured browser test runner. GitHub and ZIP ingestion calls currently target paths absent from the FastAPI router; see [api.md](api.md#frontend-contract-discrepancies).

## Import and dependency observations

The app entry point, routers, agent modules, intelligence modules, and sandbox modules imported through the test suite and an explicit `app.main` import. Python `compileall` completed. A dedicated dependency-cycle analyzer is not configured; source imports show the intended direction from API to services/agents and from agents to intelligence/models, with no cycle confirmed by these checks. This is not a formal proof of absence of cycles.

## Evidence map

- FastAPI wiring: `backend/app/main.py`, `backend/app/api/v1/router.py`.
- Database models and session lifecycle: `backend/app/core/database.py`, `backend/app/models/repository.py`, `backend/app/models/agent_artifact.py`.
- Ingestion and twin creation: `backend/app/services/ingestion/ingestion_service.py`, `backend/app/services/twin/twin_builder.py`.
- Parser: `backend/app/services/parser/polyglot_parser.py`, `intelligence/parser/`.
- Retrieval/graph: `backend/app/services/rag/service.py`, `backend/app/services/graph/service.py`, `backend/app/services/change_impact.py`.
- UI: `frontend/components/RepositoryDashboard.tsx`, `frontend/components/IngestModal.tsx`, `frontend/components/TwinViewerModal.tsx`, `frontend/services/`.
