# AI and analysis agents (audited)

The product README describes eleven specialized agents. Inspection of `agents/` and the FastAPI wiring found the following active classes and flows; labels describe code behavior, not an independent autonomous agent topology.

| Requested role | Finding | Evidence / current behavior |
|---|---|---|
| Supervisor | Implemented as deterministic intent router | `agents/orchestrator.py::OrchestratorAgent` classifies the query (`_classify_intent`) and dispatches to specialist services (security, docs, tests, healing, impact, readiness, code health, dependency security); exposed at `POST /repositories/{repo_id}/ask/orchestrate`. Routing is keyword-weighted, not learned |
| Explorer | Not implemented as an agent | Repository browsing is implemented by deterministic API/service endpoints |
| Documentation | Implemented | `DocumentationAgent`, drift detector, verification and generate/list/read API; `readme` and `diagram` (deterministic Mermaid) doc types added |
| Test Planner | Implemented | `TestAgent.plan_tests`; API accepts target file/framework |
| Test Generator | Implemented | `TestAgent.generate_tests`; LLM output can be parsed from a code fence, with deterministic fallback paths |
| Test Verifier | Implemented | `TestVerifierAgent` (`agents/test_pipeline.py`) reports the `GeneratedTestSafetyScreen` result and executes through the sandbox runner; without Docker, host fallback is statically screened or refused (`SANDBOX_HOST_FALLBACK`) |
| Security | Implemented with conditional tooling | `SecurityAgent` normalizes/merges findings, invokes supported scanners when available, and always runs a built-in regex scanner so results never depend solely on external tools |
| Architecture | Partial/deterministic | Graph, repository analysis, and dashboard architecture data exist; no standalone architecture agent was found |
| Change Impact | Implemented as service | `ChangeImpactService` uses indexed relations and evidence; no separate agent class |
| Git History | Implemented as service | `GitHistoryService` and history rationale endpoint; no separate agent class |
| Code Review | Not implemented | No code review agent or review endpoint found |

## LLM behavior and evidence limits

`intelligence/llm_client.py` supports OpenAI-compatible and Ollama calls plus empty-string fallback. The default provider is `mock`; a missing/failed provider response leads to deterministic fallback behavior in calling agents. The QA agent allows Ollama calls without an API key; OpenAI/HuggingFace calls require a configured key. `QAAgent` retrieves repository symbols and supplies that context to a model, but returns model text without validating every claim or citation against the retrieved evidence. Citations are assembled from retrieved symbols separately from the model response. Repository-controlled source and documentation enter prompts as data with an untrusted-evidence boundary instruction, but there is no claim-level output verifier.

Generated docs and tests are stored as plain text/code. Pydantic validates request/response shapes, but generated content is not independently proven correct. Treat AI output and security findings as review material.

## Known limits

- Supervisor routing is keyword-based intent classification, not learned or planner-based; ambiguous phrasing can route to the wrong specialist.
- No held-out evaluation run or measured hallucination benchmark was performed for this audit.
- The security endpoint's “tools considered” field does not establish that every listed scanner executed successfully; inspect per-environment availability and results. The built-in regex scanner always runs, so a scan never returns empty solely due to missing external tools.
- Prompt injection and citation integrity have no dedicated red-team tests in the current suite; generated-test host execution is statically screened (`backend/tests/test_generated_test_safety.py`) but the screen is pattern-based, not a proof.
