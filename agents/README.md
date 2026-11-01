# CodeTwin Specialized Agents

This directory hosts the autonomous multi-agent system coordinating software repository intelligence:

1. **Supervisor Agent**: Orchestrates task delegation, inter-agent workflows, and evidence synthesis.
2. **Repository Explorer Agent**: Traverses the Digital Twin, navigates symbol call graphs, and extracts AST context.
3. **Documentation Agent**: Generates architecture overviews, API references, and detects documentation-code drift.
4. **Test Planner Agent**: Analyzes code branches, untested edge cases, and designs comprehensive test suites.
5. **Test Generator Agent**: Synthesizes verified unit and integration tests (pytest, Vitest/Jest, JUnit).
6. **Test Verifier Agent**: Executes generated tests inside sandboxed environments and verifies assertions and coverage.
7. **Security Agent**: Coordinates static analysis tools (Semgrep, Bandit, Gitleaks, Trivy) and files evidence-backed vulnerabilities.
8. **Architecture Agent**: Evaluates structural coupling, cohesion, circular dependencies, and component boundaries.
9. **Change Impact Agent**: Computes blast radius and affected downstream components across commits and PRs.
10. **Git History Agent**: Analyzes code churn, hotspots, commit velocity, and author ownership.
11. **Code Review Agent**: Performs deep architectural and idiomatic code reviews grounded in AST evidence.
