from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List

from intelligence.dependencies.extractor import extract_dependencies
from intelligence.language_detection import detect_language, detect_language_from_content
from intelligence.models import BaseEntity, CodeComment, CodeDependency, CodeFile, CodeImport, DatabaseModel, ApiEndpoint
from intelligence.symbols.extractor import extract_symbols


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def analyze_file(repo_id: str, file_path: str, content: str | None = None) -> Dict[str, Any]:
    rel_path = file_path.replace("\\", "/").lstrip("/")
    source = content if content is not None else Path(file_path).read_text(encoding="utf-8", errors="ignore")
    language = detect_language_from_content(rel_path, source)
    extracted = extract_symbols(rel_path, repo_id, source, language)
    deps = extract_dependencies(rel_path, repo_id, source, language)
    result = {
        "repository_id": repo_id,
        "file_path": rel_path,
        "language": language,
        "file": extracted["file"].to_dict(),
        "classes": [item.to_dict() for item in extracted["classes"]],
        "functions": [item.to_dict() for item in extracted["functions"]],
        "methods": [item.to_dict() for item in extracted["methods"]],
        "variables": [item.to_dict() for item in extracted["variables"]],
        "imports": [item.to_dict() for item in extracted["imports"]],
        "dependencies": [item.to_dict() for item in deps],
        "api_endpoints": [item.to_dict() for item in extracted["api_endpoints"]],
        "database_models": [item.to_dict() for item in extracted["database_models"]],
        "comments": [item.to_dict() for item in extracted["comments"]],
        "docstrings": [item.to_dict() for item in extracted["docstrings"]],
        "source_hash": _sha256(source),
    }
    return result


def analyze_repository(repo_id: str, root_path: str | Path) -> Dict[str, Any]:
    root = Path(root_path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Repository path not found: {root}")

    file_results: List[Dict[str, Any]] = []
    classes: List[Dict[str, Any]] = []
    functions: List[Dict[str, Any]] = []
    methods: List[Dict[str, Any]] = []
    variables: List[Dict[str, Any]] = []
    imports: List[Dict[str, Any]] = []
    dependencies: List[Dict[str, Any]] = []
    api_endpoints: List[Dict[str, Any]] = []
    database_models: List[Dict[str, Any]] = []
    comments: List[Dict[str, Any]] = []
    docstrings: List[Dict[str, Any]] = []
    language_counts: Dict[str, int] = {}
    file_tree: List[str] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith(".") and path.name not in {".env.example"}:
            continue
        ext = path.suffix.lower()
        if ext in {".pyc", ".class", ".o", ".so", ".dll", ".dylib", ".exe", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar", ".gz", ".db"}:
            continue
        rel = path.relative_to(root).as_posix()
        file_tree.append(rel)
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        language = detect_language_from_content(rel, content)
        if language != "unknown":
            language_counts[language] = language_counts.get(language, 0) + 1
        res = analyze_file(repo_id, str(path), content)
        file_results.append(res)
        classes.extend(res["classes"])
        functions.extend(res["functions"])
        methods.extend(res["methods"])
        variables.extend(res["variables"])
        imports.extend(res["imports"])
        dependencies.extend(res["dependencies"])
        api_endpoints.extend(res["api_endpoints"])
        database_models.extend(res["database_models"])
        comments.extend(res["comments"])
        docstrings.extend(res["docstrings"])

    result = {
        "repository_id": repo_id,
        "repository_path": str(root),
        "language_stats": language_counts,
        "language_statistics": language_counts,
        "files": file_results,
        "file_tree": file_tree,
        "classes": classes,
        "functions": functions,
        "methods": methods,
        "variables": variables,
        "imports": imports,
        "dependencies": dependencies,
        "api_endpoints": api_endpoints,
        "apis": api_endpoints,
        "database_models": database_models,
        "comments": comments,
        "docstrings": docstrings,
        "total_files": len(file_results),
        "symbol_count": len(classes) + len(functions) + len(methods) + len(variables),
    }
    return result


__all__ = ["analyze_repository", "analyze_file"]
