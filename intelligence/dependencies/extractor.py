from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List

from intelligence.language_detection import detect_language
from intelligence.models import CodeDependency


def extract_dependencies(file_path: str, repository_id: str, content: str, language: str | None = None) -> List[CodeDependency]:
    lang = (language or detect_language(file_path) or "unknown").lower()
    items: List[CodeDependency] = []
    lines = content.splitlines()
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if lang == "python":
            match = re.match(r"^(?:from|import)\s+([A-Za-z0-9_\.]+)", stripped)
            if match:
                name = match.group(1)
                items.append(CodeDependency(repository_id=repository_id, file_path=file_path, symbol_name=name, symbol_type="dependency", start_line=lineno, end_line=lineno, source_hash="", metadata={}, package_name=name, version="", ecosystem="pip"))
            else:
                req_match = re.match(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?(?:[<>=!~].+)?$", stripped)
                if req_match and not stripped.startswith("-e "):
                    name = req_match.group(1)
                    items.append(CodeDependency(repository_id=repository_id, file_path=file_path, symbol_name=name, symbol_type="dependency", start_line=lineno, end_line=lineno, source_hash="", metadata={}, package_name=name, version="", ecosystem="pip"))
        elif lang in {"javascript", "typescript"}:
            if file_path.lower().endswith("package.json"):
                package_match = re.search(r'"([A-Za-z0-9_@/\.-]+)"\s*:\s*"([^"]+)"', stripped)
                if package_match:
                    name, version = package_match.groups()
                    items.append(CodeDependency(repository_id=repository_id, file_path=file_path, symbol_name=name, symbol_type="dependency", start_line=lineno, end_line=lineno, source_hash="", metadata={}, package_name=name, version=version, ecosystem="npm"))
            for match in re.finditer(r"(?:import|require)\s+(?:\w+\s+from\s+)?['\"]([A-Za-z0-9_@/\.-]+)['\"]", stripped):
                mod = match.group(1)
                items.append(CodeDependency(repository_id=repository_id, file_path=file_path, symbol_name=mod, symbol_type="dependency", start_line=lineno, end_line=lineno, source_hash="", metadata={}, package_name=mod, version="", ecosystem="npm"))
        elif lang in {"java", "c", "cpp"}:
            match = re.match(r"#include\s*[<\"]([^>\"]+)[>\"]", stripped)
            if match:
                mod = match.group(1)
                items.append(CodeDependency(repository_id=repository_id, file_path=file_path, symbol_name=mod, symbol_type="dependency", start_line=lineno, end_line=lineno, source_hash="", metadata={}, package_name=mod, version="", ecosystem="system" if lang in {"c", "cpp"} else "java"))
        elif lang == "go":
            for match in re.finditer(r'"([A-Za-z0-9_./-]+)"', stripped):
                mod = match.group(1)
                if mod.startswith("."):
                    continue
                items.append(CodeDependency(repository_id=repository_id, file_path=file_path, symbol_name=mod, symbol_type="dependency", start_line=lineno, end_line=lineno, source_hash="", metadata={}, package_name=mod, version="", ecosystem="go"))
    return items


__all__ = ["extract_dependencies"]
