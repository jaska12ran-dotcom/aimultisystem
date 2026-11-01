"""
Directory scanner & metadata detector
--------------------------------------
Responsibilities:
- Recursively walk repository directory
- Detect file language by extension
- Compute SHA-256 fingerprints
- Count lines, measure sizes
- Flag test / config / documentation files
- Generate directory-tree JSON
- Parse dependency manifests (multi-ecosystem)

SECURITY NOTE: No subprocess/shell invocation here. Pure Python only.
"""
from __future__ import annotations

import json
import os
import re
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# ──────────────────────────────────────────────────────────────
# Language map
# ──────────────────────────────────────────────────────────────
EXTENSION_LANGUAGE_MAP: Dict[str, str] = {
    # Python
    ".py": "python", ".pyx": "python", ".pxd": "python",
    # JavaScript / TypeScript
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript",
    # Web
    ".html": "html", ".htm": "html", ".css": "css", ".scss": "scss", ".less": "css",
    ".vue": "vue", ".svelte": "svelte",
    # Systems
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hxx": "cpp",
    ".rs": "rust", ".go": "go", ".cs": "csharp",
    # JVM
    ".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".scala": "scala",
    ".groovy": "groovy", ".clj": "clojure",
    # Scripting
    ".rb": "ruby", ".php": "php", ".pl": "perl", ".lua": "lua",
    ".r": "r", ".R": "r", ".m": "matlab",
    # Shell / config
    ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".fish": "shell",
    ".bat": "batch", ".cmd": "batch", ".ps1": "powershell",
    ".dockerfile": "dockerfile",
    # Data / config
    ".json": "json", ".jsonc": "json", ".json5": "json",
    ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".ini": "ini", ".cfg": "ini", ".conf": "ini",
    ".xml": "xml", ".xsd": "xml", ".xsl": "xml",
    ".sql": "sql", ".graphql": "graphql", ".proto": "protobuf",
    # Docs
    ".md": "markdown", ".mdx": "markdown", ".rst": "rst", ".tex": "latex",
    ".txt": "text", ".adoc": "asciidoc",
}

IGNORE_DIRS: Set[str] = {
    ".git", ".svn", ".hg", ".bzr",
    "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "venv", ".venv", "env", ".env",
    ".next", "out", "dist", "build", "target", "bin", "obj",
    ".idea", ".vscode", ".eclipse",
    "coverage", "htmlcov", ".turbo", ".cache",
}

IGNORE_EXTENSIONS: Set[str] = {
    ".pyc", ".pyo", ".pyd", ".class", ".o", ".obj", ".a", ".lib",
    ".dll", ".exe", ".so", ".dylib",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".svg", ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp4", ".mp3", ".wav", ".avi", ".mov", ".webm",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt",
    ".lock",   # package lock files – huge and low signal
}

# Files classified as configuration
CONFIG_FILENAMES: Set[str] = {
    ".env", ".env.example", ".env.local",
    "dockerfile", "docker-compose.yml", "docker-compose.yaml",
    ".gitignore", ".gitattributes", ".editorconfig",
    "makefile", "rakefile", "gemfile", "justfile",
    "pyproject.toml", "setup.cfg", "setup.py",
    "tsconfig.json", "jsconfig.json", "eslint.config.mjs", ".eslintrc.json",
    "next.config.ts", "next.config.js", "vite.config.ts",
    "webpack.config.js", "babel.config.js",
    ".prettierrc", ".stylelintrc", "renovate.json",
    "cargo.toml", "go.mod", "go.sum", "pom.xml", "build.gradle",
}

# Files classified as documentation
DOC_FILENAMES_RE = re.compile(
    r"^(readme|changelog|contributing|license|authors|notice|security|code_of_conduct)(\.[a-z]+)?$",
    re.IGNORECASE,
)

IMPORTANT_FILES: Set[str] = {
    "readme.md", "readme.txt", "readme.rst", "readme",
    "license", "license.md", "license.txt",
    "contributing.md", "changelog.md", "security.md",
    "requirements.txt", "requirements-dev.txt", "requirements-test.txt",
    "package.json", "pyproject.toml", "cargo.toml", "go.mod",
    "pom.xml", "build.gradle", "gemfile",
    "dockerfile", "docker-compose.yml", "docker-compose.yaml",
    ".env.example", "makefile",
}


# ──────────────────────────────────────────────────────────────
# File helpers
# ──────────────────────────────────────────────────────────────

def is_binary_file(file_path: Path) -> bool:
    try:
        with open(file_path, "rb") as f:
            return b"\0" in f.read(8192)
    except Exception:
        return True


def compute_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
    except Exception:
        pass
    return h.hexdigest()


def is_test_file(rel_path: str, file_name: str) -> bool:
    lp = rel_path.lower()
    ln = file_name.lower()
    return (
        "test" in lp or "spec" in lp or "__tests__" in lp
        or ln.startswith("test_") or ln.endswith("_test.py")
        or ln.endswith((".test.ts", ".test.tsx", ".test.js", ".test.jsx"))
        or ln.endswith((".spec.ts", ".spec.tsx", ".spec.js", ".spec.jsx"))
    )


def is_config_file(file_name: str) -> bool:
    return file_name.lower() in CONFIG_FILENAMES


def is_documentation_file(file_name: str) -> bool:
    return bool(DOC_FILENAMES_RE.match(file_name))


# ──────────────────────────────────────────────────────────────
# Scanner
# ──────────────────────────────────────────────────────────────

def scan_directory(root_dir: str | Path) -> Dict[str, Any]:
    """
    Recursively scans repository directory.

    Returns dict with keys:
      files, folders, languages, language_details, total_files, total_lines,
      total_size_bytes, important_files, directory_tree
    """
    root_path = Path(root_dir).resolve()
    if not root_path.exists() or not root_path.is_dir():
        raise ValueError(f"Directory does not exist: {root_path}")

    files_data: List[Dict[str, Any]] = []
    folders_data: Dict[str, Dict[str, Any]] = {}
    language_lines: Dict[str, int] = {}
    language_files: Dict[str, int] = {}
    language_bytes: Dict[str, int] = {}
    total_lines = 0
    total_size = 0
    important_files: List[str] = []

    for current_dir, dirs, filenames in os.walk(root_path):
        # Prune ignored dirs in-place (modifies os.walk traversal)
        dirs[:] = sorted(
            d for d in dirs
            if d not in IGNORE_DIRS and not d.startswith(".")
        )

        current_path = Path(current_dir)
        rel_dir = os.path.relpath(current_dir, root_path).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""

        # ── Register folder ────────────────────────────────────
        if rel_dir:
            depth = rel_dir.count("/") + 1
            parent = "/".join(rel_dir.split("/")[:-1])
            folders_data.setdefault(rel_dir, {
                "relative_path": rel_dir,
                "folder_name": os.path.basename(rel_dir),
                "parent_path": parent,
                "depth": depth,
                "file_count": 0,
                "total_size_bytes": 0,
            })

        # ── Process files ──────────────────────────────────────
        for filename in filenames:
            file_path = current_path / filename
            ext = file_path.suffix.lower()

            # Normalize no-extension Dockerfile
            if not ext and filename.lower() == "dockerfile":
                ext = ".dockerfile"

            if ext in IGNORE_EXTENSIONS:
                continue

            rel_file_path = os.path.relpath(file_path, root_path).replace("\\", "/")
            language = EXTENSION_LANGUAGE_MAP.get(ext, "unknown")
            is_bin = is_binary_file(file_path)

            line_count = 0
            file_size = 0
            sha256 = None

            try:
                stat = file_path.stat()
                file_size = stat.st_size
                total_size += file_size

                if not is_bin:
                    sha256 = compute_sha256(file_path)
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
                        line_count = sum(1 for _ in fh)
                    total_lines += line_count

            except Exception:
                pass

            # Per-language aggregation
            if language != "unknown" and not is_bin:
                language_lines[language] = language_lines.get(language, 0) + line_count
                language_files[language] = language_files.get(language, 0) + 1
                language_bytes[language] = language_bytes.get(language, 0) + file_size

            # Update parent folder counters
            if rel_dir in folders_data:
                folders_data[rel_dir]["file_count"] += 1
                folders_data[rel_dir]["total_size_bytes"] += file_size

            # Track important files
            if filename.lower() in IMPORTANT_FILES:
                important_files.append(rel_file_path)

            files_data.append({
                "relative_path": rel_file_path,
                "file_name": filename,
                "file_extension": ext,
                "language": language,
                "size_bytes": file_size,
                "line_count": line_count,
                "is_binary": is_bin,
                "is_test": is_test_file(rel_file_path, filename),
                "is_config": is_config_file(filename),
                "is_documentation": is_documentation_file(filename),
                "sha256_hash": sha256,
                "absolute_path": str(file_path),
            })

    # ── Language percentage breakdown ──────────────────────────
    lang_total_lines = sum(language_lines.values()) or 1
    languages_breakdown: Dict[str, float] = {
        lang: round((lines / lang_total_lines) * 100, 1)
        for lang, lines in sorted(language_lines.items(), key=lambda x: x[1], reverse=True)
    }

    language_details: List[Dict[str, Any]] = [
        {
            "language": lang,
            "file_count": language_files.get(lang, 0),
            "line_count": language_lines.get(lang, 0),
            "size_bytes": language_bytes.get(lang, 0),
            "percentage": languages_breakdown.get(lang, 0.0),
        }
        for lang in languages_breakdown
    ]

    # ── Directory tree ─────────────────────────────────────────
    directory_tree = _build_directory_tree(root_path, files_data, list(folders_data.values()))

    return {
        "files": files_data,
        "folders": list(folders_data.values()),
        "languages": languages_breakdown,
        "language_details": language_details,
        "total_files": len(files_data),
        "total_lines": total_lines,
        "total_size_bytes": total_size,
        "important_files": important_files,
        "directory_tree": directory_tree,
    }


# ──────────────────────────────────────────────────────────────
# Directory tree builder
# ──────────────────────────────────────────────────────────────

def _build_directory_tree(
    root: Path,
    files_data: List[Dict[str, Any]],
    folders_data: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Builds a nested tree structure suitable for frontend file-explorer rendering."""
    # Build a fast lookup of files by parent directory
    dir_files: Dict[str, List[Dict[str, Any]]] = {}
    for f in files_data:
        parent = "/".join(f["relative_path"].split("/")[:-1])
        dir_files.setdefault(parent, []).append({
            "name": f["file_name"],
            "path": f["relative_path"],
            "type": "file",
            "language": f["language"],
            "size_bytes": f["size_bytes"],
            "line_count": f["line_count"],
            "is_test": f["is_test"],
            "is_config": f["is_config"],
            "is_documentation": f["is_documentation"],
        })

    def _node(rel_path: str, name: str) -> Dict[str, Any]:
        children_dirs = sorted(
            [fd for fd in folders_data if fd["parent_path"] == rel_path],
            key=lambda x: x["folder_name"],
        )
        children_files = sorted(dir_files.get(rel_path, []), key=lambda x: x["name"])
        return {
            "name": name or root.name,
            "path": rel_path or ".",
            "type": "directory",
            "children": [_node(cd["relative_path"], cd["folder_name"]) for cd in children_dirs]
            + children_files,
        }

    return _node("", root.name)


# ──────────────────────────────────────────────────────────────
# Dependency parsers (multi-ecosystem)
# ──────────────────────────────────────────────────────────────

def parse_project_dependencies(root_dir: str | Path) -> List[Dict[str, Any]]:
    """Parses dependency manifests from multiple ecosystems. Pure text parsing only."""
    root_path = Path(root_dir)
    deps: List[Dict[str, Any]] = []
    deps.extend(_parse_requirements_txt(root_path))
    deps.extend(_parse_package_json(root_path))
    deps.extend(_parse_pyproject_toml(root_path))
    deps.extend(_parse_go_mod(root_path))
    deps.extend(_parse_gemfile(root_path))
    return deps


def _parse_requirements_txt(root: Path) -> List[Dict[str, Any]]:
    deps: List[Dict[str, Any]] = []
    for manifest in root.glob("requirements*.txt"):
        rel = str(manifest.relative_to(root))
        try:
            for line in manifest.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "-r", "-c", "--")):
                    continue
                pkg, ver = _split_req_line(line)
                deps.append({
                    "package_name": pkg,
                    "version_spec": ver,
                    "ecosystem": "pip",
                    "is_dev": "dev" in rel.lower() or "test" in rel.lower(),
                    "manifest_file": rel,
                })
        except Exception:
            pass
    return deps


def _split_req_line(line: str):
    """Split 'package>=1.0' into ('package', '>=1.0')."""
    for sep in ("==", ">=", "<=", "!=", "~=", ">", "<", " @ "):
        if sep in line:
            parts = line.split(sep, 1)
            return parts[0].strip().split("[")[0], f"{sep}{parts[1].strip()}"
    return line.split()[0].split("[")[0], None


def _parse_package_json(root: Path) -> List[Dict[str, Any]]:
    deps: List[Dict[str, Any]] = []
    pkg_file = root / "package.json"
    if not pkg_file.exists():
        return deps
    try:
        data = json.loads(pkg_file.read_text(encoding="utf-8", errors="ignore"))
        for pkg, ver in data.get("dependencies", {}).items():
            deps.append({"package_name": pkg, "version_spec": str(ver), "ecosystem": "npm",
                         "is_dev": False, "manifest_file": "package.json"})
        for pkg, ver in data.get("devDependencies", {}).items():
            deps.append({"package_name": pkg, "version_spec": str(ver), "ecosystem": "npm",
                         "is_dev": True, "manifest_file": "package.json"})
    except Exception:
        pass
    return deps


def _parse_pyproject_toml(root: Path) -> List[Dict[str, Any]]:
    deps: List[Dict[str, Any]] = []
    ppt = root / "pyproject.toml"
    if not ppt.exists():
        return deps
    try:
        # Minimal TOML parsing without external library
        text = ppt.read_text(encoding="utf-8", errors="ignore")
        in_deps = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped in ('[tool.poetry.dependencies]', '[project]', '[project.dependencies]'):
                in_deps = True
                continue
            if stripped.startswith("[") and in_deps:
                in_deps = False
            if in_deps and "=" in stripped and not stripped.startswith("#"):
                pkg = stripped.split("=")[0].strip().strip('"').strip("'")
                if pkg and pkg.lower() not in ("python", "name", "version", "description"):
                    deps.append({
                        "package_name": pkg,
                        "version_spec": None,
                        "ecosystem": "pip",
                        "is_dev": False,
                        "manifest_file": "pyproject.toml",
                    })
    except Exception:
        pass
    return deps


def _parse_go_mod(root: Path) -> List[Dict[str, Any]]:
    deps: List[Dict[str, Any]] = []
    go_mod = root / "go.mod"
    if not go_mod.exists():
        return deps
    try:
        in_require = False
        for line in go_mod.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if stripped == "require (":
                in_require = True
                continue
            if stripped == ")":
                in_require = False
                continue
            if in_require or stripped.startswith("require "):
                parts = stripped.replace("require ", "").split()
                if len(parts) >= 2:
                    deps.append({
                        "package_name": parts[0],
                        "version_spec": parts[1],
                        "ecosystem": "go",
                        "is_dev": "// indirect" in stripped,
                        "manifest_file": "go.mod",
                    })
    except Exception:
        pass
    return deps


def _parse_gemfile(root: Path) -> List[Dict[str, Any]]:
    deps: List[Dict[str, Any]] = []
    gemfile = root / "Gemfile"
    if not gemfile.exists():
        return deps
    try:
        gem_re = re.compile(r"""gem\s+['"]([^'"]+)['"]\s*(?:,\s*['"]([^'"]+)['"])?""")
        for line in gemfile.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = gem_re.search(line)
            if m:
                deps.append({
                    "package_name": m.group(1),
                    "version_spec": m.group(2),
                    "ecosystem": "gem",
                    "is_dev": "group :development" in line or "group :test" in line,
                    "manifest_file": "Gemfile",
                })
    except Exception:
        pass
    return deps
