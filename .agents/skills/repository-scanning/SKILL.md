---
name: repository-scanning
description: "Scan a repository to find source, tests, configuration, entry points, and exact evidence; use before CodeTwin repository questions or changes."
---
# Repository scanning

Use this workflow when locating relevant files or establishing repository
facts. Prefer a narrow scan over generated files, virtual environments, build
outputs, and vendored dependencies.

1. Confirm the workspace root and working-tree status; preserve changes that
   were already present.
2. Identify project manifests and top-level source/test/docs directories.
3. Search for the named API, symbols, routes, callers, configuration keys, or
   tests. Follow actual imports/call sites instead of inferring from names.
4. Read the relevant implementation and tests. Record exact paths and
   line-level evidence for conclusions.
5. Distinguish confirmed facts from likely relationships and missing context.
6. Report concise evidence and suggest the next file/test to inspect.

For CodeTwin, likely areas include `backend/app/`, `backend/tests/`,
`frontend/`, `agents/`, `intelligence/`, `sandbox/`, `training/`, and
`evaluations/`. Check manifests first; do not assume every listed component is
implemented or active.
