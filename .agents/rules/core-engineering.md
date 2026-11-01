---
trigger: always_on
description: "Project-wide CodeTwin engineering constraints for evidence, safety, compatibility, and verification."
---
# CodeTwin engineering rules

- Ground repository claims in files, symbols, tests, command output, or other
  observed evidence. Cite exact paths and relevant identifiers when reporting.
  If evidence is missing or inconclusive, say so; never fabricate repository
  facts, APIs, test results, security findings, or benchmark scores.
- Inspect existing implementation and tests before changing behavior. Search
  for existing helpers and follow established project conventions.
- Preserve existing functionality and public interfaces unless the task
  explicitly requires a change. Add or update focused tests for behavior
  changes; do not fix unrelated pre-existing issues.
- Before declaring engineering work complete, run the smallest relevant tests
  and applicable lint, type, format, or security validation. Report exact
  commands and outcomes; distinguish skipped checks from passes.
- Never run generated or otherwise untrusted code directly on the host. Use the
  repository's isolated sandbox or an equivalently restricted disposable
  environment; restrict filesystem, network, credentials, and resources.
- Do not perform destructive actions such as recursive deletion, force reset,
  force push, database destruction, or broad cleanup without explicit user
  approval for the exact target and operation. Preserve unrelated and
  pre-existing worktree changes.
- Avoid secrets in source, logs, prompts, and reports. Do not send repository
  code or credentials to external services without a clear need and user
  authorization.
- Prefer local repository inspection and existing project tools. Use MCP only
  when a specific external service provides a clear, task-relevant benefit.
- Do not use deprecated Antigravity Workflows for new reusable functionality;
  use Skills, persistent rules, and current agent/subagent facilities.
