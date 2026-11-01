# CodeTwin Antigravity customizations

This folder contains project-scoped Antigravity configuration:

- `rules/`: persistent rules auto-discovered for this workspace.
- `skills/`: on-demand Agent Skills folders with `SKILL.md`.
- `agents/`: role profiles for repository analysis, backend, frontend, tests,
  security, documentation, and evaluation work. Use these as the system prompts
  when registering/invoking named subagents with Antigravity's current
  `define_subagent` / subagent facilities; they are not legacy Workflows.
- `hooks.json`: Antigravity's workspace hook configuration.
- `hooks/`: hook scripts and their maintenance notes.
- `mcp_config.json`: intentionally empty MCP registry. Add a server only when
  a task has a clear need for external structured context or actions.

The persistent rules and skills are plain Markdown intended to be reviewed and
versioned with the project. Hooks are small, auditable scripts: destructive
shell operations require explicit confirmation, and the stop check validates
the Git diff before allowing the agent to finish. Hooks do not replace running
tests, lint, type checks, formatters, or security tools when relevant.

Antigravity discovers project rules and skills from `.agents/`. Workspace hook
configuration is `.agents/hooks.json`; the `hooks/` child directory stores its
scripts.
