# Security review

Review scope: backend API, repository ingestion, archive handling, Git clone, file serving, LLM prompts/output, security analyzer, and generated-test execution. Findings are based on static code tracing plus existing tests; this was not a penetration test or an exhaustive dynamic scanner run.

## Findings

### Was critical, now mitigated: generated tests could execute on the API host

`sandbox/runner.py` executes generated pytest code with Docker isolation when Docker is present; previously it silently fell back to running tests on the backend host with no isolation. **Mitigation applied:** the no-Docker path is now governed by `SANDBOX_HOST_FALLBACK` (`sandbox/policies.py`):

- `disabled` — host execution is refused entirely (fail closed).
- `screened` (default) — generated code is statically screened by `GeneratedTestSafetyScreen` (subprocess, network, process exit, file deletion, `eval`/`exec`, unbounded loops, ctypes, pip installs) and refuses to run on the host when any blocked construct is present. Unrecognized values fail closed.

**Residual risk:** the screen is a fixed-pattern heuristic and can be evaded by obfuscation; it reduces but does not eliminate host-execution risk. For untrusted repositories, deploy with Docker or set `SANDBOX_HOST_FALLBACK=disabled`. The Docker path itself uses network isolation, resource limits, dropped capabilities, read-only root, and a writable repository mount. Regression tests: `backend/tests/test_generated_test_safety.py`. `DOCKER_SANDBOX_ENABLED` in Compose remains unused by the runner and should be treated as documentation of intent, not enforcement.

### Critical when network exposed: no authentication or authorization

No authentication dependency or ownership model was found on repository routes. Any reachable caller can list/read repositories, ingest a server-side local path, request analysis, generate/execute tests, and delete repositories. Local ingestion is a filesystem-reading API. **Remediation:** add authentication and per-repository authorization before network exposure; disable local-path ingestion in hosted deployments.

### High: upload filename influences temporary filesystem path

`backend/app/api/v1/endpoints/repositories.py:74-81` constructs `UPLOADS_DIR / f"tmp_{file.filename}"` and opens it before `IngestionService` validates/sanitizes the filename. Traversal components in a multipart filename can escape the uploads directory or collide with another request's temporary file. Concurrent uploads with the same name can overwrite/read/remove each other's temp archive. The byte limit is checked after the full request body is copied, so it does not cap incoming disk consumption. **Remediation:** use an exclusive random temp file under the upload directory; validate the resolved parent and enforce size during streaming.

### High: tests execute concurrently without per-suite claim/lock

The execute route writes `running`, commits, then executes; concurrent requests can execute the same stored suite and race to update the final status/output. `execute_python_test` does synchronous copying/subprocess work inside an async function. This can block the event loop and amplify resource exhaustion. **Remediation:** use durable job/lease state, worker isolation, and bounded concurrency.

### High: repository prompt injection and unverified model claims

Repository content and retrieved symbol data are placed in LLM prompts (`agents/qa_agent.py` and related agents), while repository files are attacker-controlled. There is no explicit untrusted-context instruction boundary or output claim/citation verifier. QA returns free-form model output and separately assembled citations; model claims can exceed the evidence. **Remediation:** isolate repository text as quoted data, validate citations against retrieved records, label unsupported claims, and test hostile repository instructions.

### Medium: local path validator does not reliably reject protected roots

`backend/app/services/ingestion/validator.py` raises `ValidationError` inside a `try` that is followed by `except Exception: pass`, which catches and suppresses its own rejection. The prefix check also uses string `startswith`, not path ancestry. As a result, its documented system-path guard is not reliable. The endpoint remains unauthenticated, making local path ingest especially sensitive. **Remediation:** separate resolution errors from policy checks and compare canonical path ancestry with `Path.relative_to`.

### Medium: deployment defaults are unsafe for public operation

`docker-compose.yml` supplies a predictable database password fallback, exposes PostgreSQL on the host, and configures no application auth/TLS/rate limits. The API binds on the container interface. These are development defaults and are not suitable for public deployment.

## Controls observed

- Git remote URLs are constrained to exact allowlisted host/path patterns before cloning. GitPython is used; no `shell=True` was found in the ingestion path.
- ZIP extraction validates member ancestry, size, compression ratio, count, and symlink metadata before extraction (`backend/app/services/ingestion/archive.py`).
- File-content lookup uses a resolved-path containment check in `backend/app/api/v1/endpoints/twin.py`.
- Docker sandbox command construction uses an argument list and applies `--network none`, CPU/memory/PID caps, dropped capabilities, `no-new-privileges`, read-only root, and tmpfs settings.
- Generated-test host fallback (no Docker) is statically screened by `GeneratedTestSafetyScreen` and can be disabled outright with `SANDBOX_HOST_FALLBACK=disabled`; misconfigured values fail closed.
- No hardcoded external API key was found in inspected application configuration; secrets are environment-driven.

## Scan and verification limits

`bandit`, `pip-audit`, `ruff`, and `mypy` are not installed/configured in the current environment. The repository's security endpoint tests passed as part of the backend suite, but no full Bandit/Semgrep/Gitleaks/Trivy dependency or repository scan was run. Docker is unavailable here, so the container isolation path could not be executed. See [system-health.md](system-health.md) for exact outcomes.
