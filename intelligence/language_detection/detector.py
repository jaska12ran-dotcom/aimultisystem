from __future__ import annotations

import re
from pathlib import Path

EXTENSION_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".go": "go",
}


def detect_language(path: str | Path) -> str:
    name = Path(str(path)).name.lower()
    if name == "package.json":
        return "javascript"
    if name in {"requirements.txt", "pyproject.toml", "setup.py", "poetry.lock"}:
        return "python"
    if name in {"go.mod", "go.sum"}:
        return "go"
    suffix = Path(str(path)).suffix.lower()
    if suffix in EXTENSION_MAP:
        return EXTENSION_MAP[suffix]
    if name.endswith(".d.ts"):
        return "typescript"
    return "unknown"


def detect_language_from_content(path: str | Path, content: str) -> str:
    lang = detect_language(path)
    if lang != "unknown":
        return lang
    if "import" in content and "from" in content:
        return "javascript"
    if "package " in content and "func " in content:
        return "go"
    if "class " in content and "public static void" in content:
        return "java"
    if re.search(r"#include\s*[<\"]", content):
        return "c"
    return "unknown"
