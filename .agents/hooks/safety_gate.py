"""Ask for confirmation before common destructive shell commands."""

from __future__ import annotations

import json
import re
import sys
from typing import Any


RISK_PATTERNS = (
    re.compile(r"\b(?:rm|rmdir|remove-item)\b", re.IGNORECASE),
    re.compile(r"\bdel\b[^\r\n]*/(?:s|q)\b", re.IGNORECASE),
    re.compile(r"\brd\b[^\r\n]*/(?:s|q)\b", re.IGNORECASE),
    re.compile(r"\bformat(?:\.com)?\s+[a-z]:", re.IGNORECASE),
    re.compile(r"\bgit\s+clean\b[^\r\n]*-[^\r\n]*f", re.IGNORECASE),
    re.compile(r"\bgit\s+reset\b[^\r\n]*--hard\b", re.IGNORECASE),
    re.compile(r"\bgit\s+(?:checkout\s+--|restore\b)", re.IGNORECASE),
    re.compile(r"\bgit\s+branch\b[^\r\n]*\s-D\b", re.IGNORECASE),
    re.compile(r"\bgit\s+push\b[^\r\n]*(?:--force(?:-with-lease)?|-f)\b", re.IGNORECASE),
    re.compile(r"\b(?:truncate|drop\s+database)\b", re.IGNORECASE),
)


def main() -> int:
    try:
        payload: Any = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        print(json.dumps({"decision": "ask", "reason": "Could not inspect command safely."}))
        return 0

    tool_call = payload.get("toolCall", {}) if isinstance(payload, dict) else {}
    args = tool_call.get("args", {}) if isinstance(tool_call, dict) else {}
    command = args.get("CommandLine", "") if isinstance(args, dict) else ""
    if not isinstance(command, str):
        command = ""

    matched = any(pattern.search(command) for pattern in RISK_PATTERNS)
    if matched:
        result = {
            "decision": "ask",
            "reason": (
                "This command resembles a destructive operation. Inspect its exact "
                "target and impact; do not proceed without explicit user approval."
            ),
        }
    else:
        result = {"decision": "allow"}
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
