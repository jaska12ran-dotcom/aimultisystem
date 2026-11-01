"""Block stopping when the tracked Git diff has whitespace errors."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def main() -> int:
    try:
        payload: Any = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        print(json.dumps({"decision": "continue", "reason": "Could not validate the diff; inspect Git status and diff manually."}))
        return 0

    paths = payload.get("workspacePaths", []) if isinstance(payload, dict) else []
    workspace = Path(paths[0]) if isinstance(paths, list) and paths and isinstance(paths[0], str) else Path.cwd()
    try:
        repository = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
        workspace_path = workspace.resolve()
        repository_path = Path(repository).resolve()
        pathspec = workspace_path.relative_to(repository_path).as_posix() or "."
        has_head = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        ).returncode == 0
        commands = (
            [["git", "diff", "--check", "HEAD", "--", pathspec]]
            if has_head
            else [
                ["git", "diff", "--check", "--cached", "--", pathspec],
                ["git", "diff", "--check", "--", pathspec],
            ]
        )
        results = [
            subprocess.run(
                command,
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
                timeout=8,
            )
            for command in commands
        ]
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"decision": "continue", "reason": f"Diff validation could not run ({exc}); inspect Git status and diff manually."}))
        return 0

    failures = [result for result in results if result.returncode]
    if failures:
        detail = "\n".join((result.stdout + result.stderr).strip() for result in failures)
        print(json.dumps({
            "decision": "continue",
            "reason": "Fix Git diff whitespace errors before finishing. " + detail[:1500],
        }))
        return 0
    reason = (
        "No Git HEAD exists; staged and unstaged tracked diffs passed, but "
        "untracked files were not checked."
        if not has_head
        else ""
    )
    print(json.dumps({"decision": "allow", "reason": reason}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
