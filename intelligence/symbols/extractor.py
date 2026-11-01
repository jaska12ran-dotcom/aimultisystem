from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from intelligence.language_detection import detect_language
from intelligence.models import (
    ApiEndpoint,
    CodeClass,
    CodeComment,
    CodeDocstring,
    CodeFile,
    CodeFunction,
    CodeImport,
    CodeMethod,
    CodeDependency,
    DatabaseModel,
)


_RULE_LANGUAGE_KEYS = {
    "python": {"import", "from", "class", "def", "@"},
    "javascript": {"import ", "export ", "class ", "function ", "const ", "let ", "var "},
    "typescript": {"interface ", "enum ", "export ", "class ", "function ", "const "},
    "java": {"import ", "class ", "interface ", "enum ", "public ", "private "},
    "c": {"#include", "struct ", "enum ", "int ", "char ", "void "},
    "cpp": {"#include", "class ", "struct ", "enum ", "namespace "},
    "go": {"package ", "import ", "func ", "type ", "interface{}", "struct {"},
}


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_name(name: str) -> str:
    return name.strip().replace("\n", " ").strip("` ")


def _extract_python_symbols(file_path: str, content: str, repo_id: str) -> Tuple[List[Any], List[Any], List[Any], List[Any], List[Any], List[Any], List[Any], List[Any]]:
    start_line = 1
    lines = content.splitlines()
    symbols: List[Any] = []
    imports: List[Any] = []
    comments: List[Any] = []
    docstrings: List[Any] = []
    dependencies: List[Any] = []
    api_endpoints: List[Any] = []
    db_models: List[Any] = []
    variables: List[Any] = []
    tree = ast.parse(content)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported = alias.asname or alias.name.split(".")[-1]
                imports.append(
                    CodeImport(
                        repository_id=repo_id,
                        file_path=file_path,
                        symbol_name=alias.name,
                        symbol_type="import",
                        start_line=getattr(node, "lineno", 1),
                        end_line=getattr(node, "end_lineno", 1),
                        source_hash=_sha256(content),
                        metadata={},
                        module_name=alias.name,
                        imported_names=[imported],
                        is_standard_library=alias.name.split(".")[0] in {"os", "sys", "pathlib", "json", "re", "typing", "asyncio", "datetime", "logging"},
                        is_third_party=not alias.name.split(".")[0] in {"os", "sys", "pathlib", "json", "re", "typing", "asyncio", "datetime", "logging"},
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            names = [alias.name for alias in node.names]
            imports.append(
                CodeImport(
                    repository_id=repo_id,
                    file_path=file_path,
                    symbol_name=node.module or "",
                    symbol_type="import",
                    start_line=getattr(node, "lineno", 1),
                    end_line=getattr(node, "end_lineno", 1),
                    source_hash=_sha256(content),
                    metadata={},
                    module_name=node.module or "",
                    imported_names=names,
                    is_standard_library=(node.module or "").split(".")[0] in {"os", "sys", "pathlib", "json", "re", "typing", "asyncio", "datetime", "logging"},
                    is_third_party=(node.module or "").split(".")[0] not in {"os", "sys", "pathlib", "json", "re", "typing", "asyncio", "datetime", "logging"},
                )
            )
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if isinstance(node, ast.ClassDef):
                bases = [getattr(base, "id", getattr(base, "attr", "")) for base in node.bases]
                item = CodeClass(
                    repository_id=repo_id,
                    file_path=file_path,
                    symbol_name=node.name,
                    symbol_type="db_model" if any(base in {"Base", "Model", "DeclarativeBase", "BaseModel"} for base in bases) else "class",
                    start_line=getattr(node, "lineno", 1),
                    end_line=getattr(node, "end_lineno", 1),
                    source_hash=_sha256(content),
                    metadata={},
                    is_abstract=any(isinstance(dec, ast.Name) and dec.id == "ABC" for dec in node.decorator_list),
                    bases=bases,
                    docstring=ast.get_docstring(node),
                )
                symbols.append(item)
                if item.symbol_type == "db_model":
                    db_models.append(DatabaseModel(repository_id=repo_id, file_path=file_path, symbol_name=node.name, symbol_type="db_model", start_line=item.start_line, end_line=item.end_line, source_hash=item.source_hash, metadata={"table_name": node.name, "base_class": bases[0] if bases else None}, table_name=node.name, base_class=bases[0] if bases else None))
                if any(isinstance(dec, ast.Attribute) and dec.attr.lower() in {"get", "post", "put", "delete", "patch"} or isinstance(dec, ast.Name) and dec.id.lower() in {"route", "get", "post", "put", "delete", "patch"} for dec in node.decorator_list):
                    pass
            else:
                node_name = node.name
                is_async = isinstance(node, ast.AsyncFunctionDef)
                decorators = []
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call):
                        dec_name = getattr(dec.func, "attr", None) or getattr(dec.func, "id", None) or ""
                    elif isinstance(dec, ast.Attribute):
                        dec_name = dec.attr
                    else:
                        dec_name = getattr(dec, "id", None) or ""
                    decorators.append(dec_name)
                    if dec_name.lower() in {"get", "post", "put", "delete", "patch", "route"}:
                        method = dec_name.lower().upper() if dec_name.lower() not in {"route"} else "GET"
                        path = ""
                        if isinstance(dec, ast.Call) and dec.args:
                            path = ast.literal_eval(dec.args[0]) if isinstance(dec.args[0], ast.Constant) else str(dec.args[0])
                        api_endpoints.append(ApiEndpoint(repository_id=repo_id, file_path=file_path, symbol_name=node_name, symbol_type="api_route", start_line=getattr(node, "lineno", 1), end_line=getattr(node, "end_lineno", 1), source_hash=_sha256(content), metadata={}, method=method, path=path, handler=node_name))

                item = CodeFunction(
                    repository_id=repo_id,
                    file_path=file_path,
                    symbol_name=node_name,
                    symbol_type="method" if any(isinstance(parent, ast.ClassDef) for parent in ast.walk(tree) if parent is node) else "function",
                    start_line=getattr(node, "lineno", 1),
                    end_line=getattr(node, "end_lineno", 1),
                    source_hash=_sha256(content),
                    metadata={},
                    signature=ast.unparse(node),
                    parameters=[arg.arg for arg in node.args.args],
                    return_type=None,
                    decorators=decorators,
                    docstring=ast.get_docstring(node),
                )
                symbols.append(item)
                if item.symbol_type == "function" and item.metadata.get("kind") is None:
                    pass

    # variable extraction for Python
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    variables.append(
                        CodeFunction(
                            repository_id=repo_id,
                            file_path=file_path,
                            symbol_name=target.id,
                            symbol_type="variable",
                            start_line=getattr(node, "lineno", 1),
                            end_line=getattr(node, "end_lineno", 1),
                            source_hash=_sha256(content),
                            metadata={"value": ast.unparse(node.value)},
                            signature=f"{target.id} = {ast.unparse(node.value)}",
                            parameters=[],
                            return_type=None,
                            decorators=[],
                            docstring=None,
                        )
                    )

    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            if doc:
                docstrings.append(CodeDocstring(repository_id=repo_id, file_path=file_path, symbol_name=node.name, symbol_type="docstring", start_line=getattr(node, "lineno", 1), end_line=getattr(node, "end_lineno", 1), source_hash=_sha256(content), metadata={"value": doc}, value=doc))

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            comments.append(CodeComment(repository_id=repo_id, file_path=file_path, symbol_name=f"comment_{lineno}", symbol_type="comment", start_line=lineno, end_line=lineno, source_hash=_sha256(content), metadata={}, comment_text=stripped.lstrip("#").strip()))

    return symbols, imports, comments, docstrings, dependencies, api_endpoints, db_models, variables


def _extract_regex_symbols(file_path: str, content: str, repo_id: str, language: str) -> Tuple[List[Any], List[Any], List[Any], List[Any], List[Any], List[Any], List[Any], List[Any]]:
    symbols: List[Any] = []
    imports: List[Any] = []
    comments: List[Any] = []
    docstrings: List[Any] = []
    dependencies: List[Any] = []
    api_endpoints: List[Any] = []
    db_models: List[Any] = []
    variables: List[Any] = []
    lines = content.splitlines()
    file_hash = _sha256(content)

    if language in {"javascript", "typescript"}:
        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("//"):
                comments.append(CodeComment(repository_id=repo_id, file_path=file_path, symbol_name=f"comment_{i}", symbol_type="comment", start_line=i, end_line=i, source_hash=file_hash, metadata={}, comment_text=stripped[2:].strip()))
            if re.match(r"(export\s+)?(class|interface|enum)\s+([A-Za-z0-9_]+)", stripped):
                name = re.search(r"(?:class|interface|enum)\s+([A-Za-z0-9_]+)", stripped).group(1)
                symbol_type = "interface" if "interface" in stripped else "enum" if "enum" in stripped else "class"
                symbols.append(CodeClass(repository_id=repo_id, file_path=file_path, symbol_name=name, symbol_type=symbol_type, start_line=i, end_line=i, source_hash=file_hash, metadata={}, is_abstract=False, bases=[], docstring=None))
            if re.match(r"(export\s+)?(async\s+)?function\s+([A-Za-z0-9_]+)", stripped):
                name = re.search(r"function\s+([A-Za-z0-9_]+)", stripped).group(1)
                symbols.append(CodeFunction(repository_id=repo_id, file_path=file_path, symbol_name=name, symbol_type="function", start_line=i, end_line=i, source_hash=file_hash, metadata={}, signature=stripped, parameters=[], return_type=None, decorators=[], docstring=None))
            if re.match(r"(const|let|var)\s+([A-Za-z0-9_]+)", stripped):
                name = re.search(r"(?:const|let|var)\s+([A-Za-z0-9_]+)", stripped).group(1)
                variables.append(CodeFunction(repository_id=repo_id, file_path=file_path, symbol_name=name, symbol_type="variable", start_line=i, end_line=i, source_hash=file_hash, metadata={}, signature=stripped, parameters=[], return_type=None, decorators=[], docstring=None))
            if re.match(r"import\s+(.*?)(from\s+['\"]|['\"])", stripped):
                imports.append(CodeImport(repository_id=repo_id, file_path=file_path, symbol_name="import", symbol_type="import", start_line=i, end_line=i, source_hash=file_hash, metadata={}, module_name=stripped, imported_names=[stripped], is_standard_library=False, is_third_party=True))
            if re.search(r"(app\.|router\.|router)\.(get|post|put|delete|patch)\s*\((['\"][^\"]+['\"])", stripped):
                method, path = re.search(r"\.(get|post|put|delete|patch)\s*\((['\"][^\"]+['\"])", stripped, re.IGNORECASE).groups()
                api_endpoints.append(ApiEndpoint(repository_id=repo_id, file_path=file_path, symbol_name=f"{method.lower()}_{path}", symbol_type="api_route", start_line=i, end_line=i, source_hash=file_hash, metadata={}, method=method.upper(), path=path.strip("'\""), handler=None))
    elif language in {"java"}:
        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("//"):
                comments.append(CodeComment(repository_id=repo_id, file_path=file_path, symbol_name=f"comment_{i}", symbol_type="comment", start_line=i, end_line=i, source_hash=file_hash, metadata={}, comment_text=stripped[2:].strip()))
            if re.match(r"(public|private|protected)?\s*(class|interface|enum)\s+([A-Za-z0-9_]+)", stripped):
                name = re.search(r"(?:class|interface|enum)\s+([A-Za-z0-9_]+)", stripped).group(1)
                kind = "interface" if "interface" in stripped else "enum" if "enum" in stripped else "class"
                symbols.append(CodeClass(repository_id=repo_id, file_path=file_path, symbol_name=name, symbol_type=kind, start_line=i, end_line=i, source_hash=file_hash, metadata={}, is_abstract=False, bases=[], docstring=None))
            if re.match(r"(public|private|protected)\s+.*\s+([A-Za-z0-9_]+)\s*\(.*\)\s*\{", stripped):
                name = re.search(r"([A-Za-z0-9_]+)\s*\(.*\)", stripped).group(1)
                symbols.append(CodeFunction(repository_id=repo_id, file_path=file_path, symbol_name=name, symbol_type="method", start_line=i, end_line=i, source_hash=file_hash, metadata={}, signature=stripped, parameters=[], return_type=None, decorators=[], docstring=None))
            if re.match(r"import\s+[A-Za-z0-9_\.]+;", stripped):
                imports.append(CodeImport(repository_id=repo_id, file_path=file_path, symbol_name="import", symbol_type="import", start_line=i, end_line=i, source_hash=file_hash, metadata={}, module_name=stripped.replace("import ", "").replace(";", ""), imported_names=[stripped], is_standard_library=False, is_third_party=True))
    elif language in {"c", "cpp"}:
        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("//"):
                comments.append(CodeComment(repository_id=repo_id, file_path=file_path, symbol_name=f"comment_{i}", symbol_type="comment", start_line=i, end_line=i, source_hash=file_hash, metadata={}, comment_text=stripped[2:].strip()))
            if re.match(r"(?:struct|class|enum)\s+([A-Za-z0-9_]+)", stripped):
                name = re.search(r"(?:struct|class|enum)\s+([A-Za-z0-9_]+)", stripped).group(1)
                kind = "enum" if "enum" in stripped else "class"
                symbols.append(CodeClass(repository_id=repo_id, file_path=file_path, symbol_name=name, symbol_type=kind, start_line=i, end_line=i, source_hash=file_hash, metadata={}, is_abstract=False, bases=[], docstring=None))
            if re.search(r"[A-Za-z0-9_]+\s+[A-Za-z0-9_]+\s*\([^)]*\)\s*\{", stripped):
                m = re.search(r"([A-Za-z0-9_]+)\s*\([^)]*\)", stripped)
                if m:
                    symbols.append(CodeFunction(repository_id=repo_id, file_path=file_path, symbol_name=m.group(1), symbol_type="function", start_line=i, end_line=i, source_hash=file_hash, metadata={}, signature=stripped, parameters=[], return_type=None, decorators=[], docstring=None))
            if re.match(r"#include\s*[<\"].+[>\"]", stripped):
                imports.append(CodeImport(repository_id=repo_id, file_path=file_path, symbol_name=stripped, symbol_type="import", start_line=i, end_line=i, source_hash=file_hash, metadata={}, module_name=stripped, imported_names=[stripped], is_standard_library=False, is_third_party=True))
    elif language == "go":
        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("//"):
                comments.append(CodeComment(repository_id=repo_id, file_path=file_path, symbol_name=f"comment_{i}", symbol_type="comment", start_line=i, end_line=i, source_hash=file_hash, metadata={}, comment_text=stripped[2:].strip()))
            if re.match(r"func\s+\([A-Za-z0-9_\s]+\)\s*([A-Za-z0-9_]+)\s*\(.*\)", stripped):
                name = re.search(r"func\s+(?:\([^)]*\)\s*)?([A-Za-z0-9_]+)\s*\(", stripped).group(1)
                symbols.append(CodeFunction(repository_id=repo_id, file_path=file_path, symbol_name=name, symbol_type="method", start_line=i, end_line=i, source_hash=file_hash, metadata={}, signature=stripped, parameters=[], return_type=None, decorators=[], docstring=None))
            elif re.match(r"func\s+([A-Za-z0-9_]+)\s*\(.*\)", stripped):
                name = re.search(r"func\s+([A-Za-z0-9_]+)\s*\(", stripped).group(1)
                symbols.append(CodeFunction(repository_id=repo_id, file_path=file_path, symbol_name=name, symbol_type="function", start_line=i, end_line=i, source_hash=file_hash, metadata={}, signature=stripped, parameters=[], return_type=None, decorators=[], docstring=None))
            if re.match(r"import\s+\((.*)\)", stripped):
                imports.append(CodeImport(repository_id=repo_id, file_path=file_path, symbol_name="import", symbol_type="import", start_line=i, end_line=i, source_hash=file_hash, metadata={}, module_name=stripped, imported_names=[stripped], is_standard_library=False, is_third_party=True))
    return symbols, imports, comments, docstrings, dependencies, api_endpoints, db_models, variables


def extract_symbols(file_path: str, repository_id: str, content: str, language: str | None = None) -> Dict[str, List[Any]]:
    language = language or detect_language(file_path)
    if language == "python":
        symbols, imports, comments, docstrings, dependencies, api_endpoints, db_models, variables = _extract_python_symbols(file_path, content, repository_id)
    else:
        symbols, imports, comments, docstrings, dependencies, api_endpoints, db_models, variables = _extract_regex_symbols(file_path, content, repository_id, language)

    file_hash = _sha256(content)
    file_obj = CodeFile(
        repository_id=repository_id,
        file_path=file_path,
        symbol_name=Path(file_path).name,
        symbol_type="file",
        start_line=1,
        end_line=max(1, len(content.splitlines())),
        source_hash=file_hash,
        metadata={"language": language},
        language=language,
        size_bytes=len(content.encode("utf-8")),
        is_test="test" in Path(file_path).name.lower(),
        is_config=Path(file_path).name.lower() in {"package.json", "requirements.txt", "pom.xml", "go.mod", "Cargo.toml"},
        is_documentation=file_path.lower().endswith((".md", ".rst")),
    )

    return {
        "file": file_obj,
        "classes": [s for s in symbols if isinstance(s, CodeClass)],
        "functions": [s for s in symbols if isinstance(s, CodeFunction) and s.symbol_type == "function"],
        "methods": [s for s in symbols if isinstance(s, CodeFunction) and s.symbol_type == "method"],
        "variables": variables,
        "imports": imports,
        "dependencies": dependencies,
        "api_endpoints": api_endpoints,
        "database_models": db_models,
        "comments": comments,
        "docstrings": docstrings,
    }
