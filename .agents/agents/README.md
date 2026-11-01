# Role profiles

Each Markdown file is a focused system-prompt profile for a named Antigravity
subagent. When using `define_subagent`, provide the profile body as
`system_prompt` and its frontmatter `name` and `description`. These profiles
are deliberately single-role and do not grant broad tool access. The active
Antigravity tool permissions and project rules remain authoritative.
