---
name: verifying-generated-tests
description: "Review and verify AI-generated tests for valid APIs, meaningful assertions, expected failure modes, coverage, and sandbox-only execution."
---
# Verifying generated tests

1. Read the target implementation and existing tests to confirm real names,
   signatures, fixtures, setup, and expected behavior.
2. Review generated tests for hallucinated imports/APIs, wrong paths, weak or
   tautological assertions, nondeterminism, hidden network access, and
   destructive side effects.
3. Check that positive and negative/edge cases are appropriate and assertions
   would fail for the defect they are intended to catch.
4. Do not execute generated code directly on the host. Use the project's
   isolated sandbox or an equally restricted disposable environment with
   bounded CPU, memory, time, filesystem, and network access.
5. Capture whether the tests parse/compile, pass against the target, and fail
   against the intended buggy version when that comparison is available.
6. Report actual commands/results, test files, evidence, and limits. Do not
   label tests execution-verified if they were only reviewed.
