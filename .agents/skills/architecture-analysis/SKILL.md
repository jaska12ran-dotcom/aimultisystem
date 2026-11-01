---
name: architecture-analysis
description: "Analyze CodeTwin architecture, component boundaries, dependencies, data flow, and change impact from actual code and tests."
---
# Architecture analysis

1. Start from project manifests and verified top-level structure.
2. Identify executable entry points and trace actual imports, API handlers,
   services, persistence, background agents, and frontend consumers.
3. Verify each dependency edge in code/configuration. Distinguish direct
   dependencies from inferred or intended ones.
4. Use tests and runtime configuration to validate critical flows; inspect
   deployment/container definitions where relevant.
5. For impact analysis, trace callers, shared types/contracts, tests,
   configuration, and documentation affected by the proposed change.
6. Present a concise component/data-flow map with evidence, assumptions, and
   unverified boundaries.

Do not present the README's intended architecture as proof of running behavior.
