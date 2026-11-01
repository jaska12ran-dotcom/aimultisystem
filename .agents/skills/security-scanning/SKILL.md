---
name: security-scanning
description: "Perform evidence-backed CodeTwin security reviews for injection, authorization, secrets, unsafe execution, dependencies, and sandbox boundaries."
---
# Security scanning

1. Scope the review and inspect the changed code plus reachable callers,
   validators, permissions, and tests.
2. Trace untrusted values from source to sensitive sinks. Check authorization,
   path handling, shell/SQL construction, secrets, SSRF/network, file writes,
   deserialization, and dependency/configuration risks as relevant.
3. For code execution, verify the actual sandbox boundary, filesystem/network
   isolation, resource limits, timeout, and cleanup. Never execute payloads
   against a real target or perform destructive proof of concept actions.
4. Use available static-analysis tools when configured; do not install tools
   or send code to external services without clear need and authorization.
5. Report only evidence-backed findings with severity, file/symbol, trigger,
   impact, confidence, and minimal remediation. Separate hardening advice from
   confirmed vulnerabilities.
6. Record tools/commands and their actual outcomes; a clean scan is not proof
   of absence.
