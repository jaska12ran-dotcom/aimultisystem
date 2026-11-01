# Hook scripts

`.agents/hooks.json` wires these scripts into Antigravity:

- `safety_gate.py` runs before `run_command` and returns `ask` for commands
  matching common destructive-operation patterns. Review and approve only when
  the exact target and effect are understood. This is a guardrail, not a
  complete shell parser; inspect commands before execution regardless.
- `validate_diff.py` runs at session stop and blocks completion when the
  workspace's tracked Git diff has whitespace errors. Without a `HEAD`, it
  checks staged/unstaged tracked diffs and warns that untracked files are not
  covered. It does not claim tests have passed. Agents must still run and
  report relevant tests, lint, format, and security checks before completion.

Both scripts use only the Python standard library and expect Antigravity to run
the configured commands from the workspace root.
