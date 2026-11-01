---
name: documentation-verification
description: "Verify CodeTwin documentation, API references, examples, file paths, and behavior against implementation and tests."
---
# Documentation verification

1. Identify the exact documentation claims being checked.
2. Trace each claim to current source, schema, routes, configuration, tests, or
   command output. Verify names and paths literally.
3. Check edge behavior and defaults in implementation; do not rely on
   docstrings or prior documentation when code disagrees.
4. Classify findings as correct, contradicted, unsupported, stale, or
   unverifiable. Cite the source evidence for each.
5. If updating docs, make the smallest correction and keep examples runnable
   and consistent with existing conventions.
6. Run documentation tests or example commands when available; clearly mark
   claims not execution-verified.

Never fill missing evidence with plausible-sounding behavior.
