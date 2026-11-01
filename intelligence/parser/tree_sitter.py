from __future__ import annotations

from importlib.util import find_spec
from typing import Any, Dict, Iterable, List


def tree_sitter_available() -> bool:
    return find_spec("tree_sitter") is not None


def parse_with_tree_sitter(file_path: str, content: str, language: str) -> Dict[str, Any]:
    if not tree_sitter_available():
        return {"parsed": False, "language": language, "symbols": [], "imports": [], "dependencies": []}

    try:
        import tree_sitter
    except Exception:
        return {"parsed": False, "language": language, "symbols": [], "imports": [], "dependencies": []}

    return {"parsed": True, "language": language, "symbols": [], "imports": [], "dependencies": []}
