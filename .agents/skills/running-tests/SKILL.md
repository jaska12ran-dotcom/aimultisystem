---
name: running-tests
description: "Select and run CodeTwin unit, integration, frontend lint/build, or targeted tests and report actual outcomes."
---
# Running tests

1. Inspect the relevant source, neighboring tests, project manifests, and
   current worktree changes.
2. Choose the smallest existing test command that covers the behavior. Do not
   start with the full suite when a focused test is available.
3. Backend tests: from the repository root, use
   `.\backend\.venv\Scripts\pytest backend\tests tests -v` on Windows when the
   project environment is available; otherwise use the activated project
   environment's `pytest`.
4. Frontend lint: run `npm run lint -- <changed-file>` from `frontend/`.
   Run `npm run build` from `frontend/` when build behavior or types warrant it.
5. Execute generated/untrusted code only in `sandbox/` or an equivalently
   isolated disposable environment. Never run generated tests on the host.
6. Read the full relevant output. Separate new failures from known baseline
   failures; do not claim a pass from a command that timed out or did not run.
7. Report exact commands, scope, pass/fail result, and any omitted validation.

Do not modify dependencies just to make a test command appear successful.
