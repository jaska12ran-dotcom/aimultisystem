# CodeTwin Execution Sandbox

Critical Rule: **Never execute untrusted repository code directly on the host machine.**

The Sandbox layer provides containerized, isolated test execution environments:
- **Docker Sandbox**: Spawns ephemeral, resource-limited Docker containers for running test commands (`pytest`, `npm test`, `vitest`, `mvn test`).
- **Resource Constraints**: Strict memory limits (512MB-2GB), CPU quotas, and execution timeouts (default 120s).
- **Network Isolation**: Disabled network egress during code execution to prevent exfiltration.
- **Local Fallback Mode**: When Docker is unavailable, processes execute inside disposable sub-processes with restricted environment variables and timeouts.
