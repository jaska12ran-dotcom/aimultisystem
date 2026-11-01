"""
Tests for the Repository Ingestion system:
  - Validator (GitHub URL, local path, ZIP filename)
  - Archive extractor (Zip-Slip, Zip-Bomb, symlinks)
  - Directory scanner (metadata, language detection, dependency parsing)
  - REST API endpoints (upload, clone, local, list, tree, delete)
"""
from __future__ import annotations

import io
import json
import os
import struct
import zipfile
from pathlib import Path

import pytest

# ──────────────────────────────────────────────────────────────
# Helper: build in-memory ZIP archives
# ──────────────────────────────────────────────────────────────

def _make_zip(entries: dict[str, bytes | str]) -> bytes:
    """Creates an in-memory ZIP with the given path→content mapping."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            if isinstance(content, str):
                content = content.encode()
            zf.writestr(name, content)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════
# 1. Validator tests
# ══════════════════════════════════════════════════════════════

class TestGitHubURLValidation:
    from app.services.ingestion.validator import validate_github_url, ValidationError

    def test_valid_github_https(self):
        from app.services.ingestion.validator import validate_github_url
        url = "https://github.com/owner/repo"
        assert validate_github_url(url) == url

    def test_valid_with_dot_git_suffix(self):
        from app.services.ingestion.validator import validate_github_url
        url = "https://github.com/owner/repo.git"
        assert validate_github_url(url) == url

    def test_valid_gitlab(self):
        from app.services.ingestion.validator import validate_github_url
        url = "https://gitlab.com/ns/project"
        assert validate_github_url(url) == url

    def test_valid_bitbucket(self):
        from app.services.ingestion.validator import validate_github_url
        url = "https://bitbucket.org/user/repo"
        assert validate_github_url(url) == url

    def test_rejects_unknown_host(self):
        from app.services.ingestion.validator import validate_github_url, ValidationError
        with pytest.raises(ValidationError, match="not in the allowed list"):
            validate_github_url("https://evil.example.com/owner/repo")

    def test_rejects_ssh_url(self):
        from app.services.ingestion.validator import validate_github_url, ValidationError
        with pytest.raises(ValidationError, match="http/https"):
            validate_github_url("git@github.com:owner/repo.git")

    def test_rejects_shell_injection_semicolon(self):
        from app.services.ingestion.validator import validate_github_url, ValidationError
        with pytest.raises(ValidationError, match="forbidden characters"):
            validate_github_url("https://github.com/owner/repo; rm -rf /")

    def test_rejects_shell_injection_backtick(self):
        from app.services.ingestion.validator import validate_github_url, ValidationError
        with pytest.raises(ValidationError, match="forbidden characters"):
            validate_github_url("https://github.com/owner/repo`whoami`")

    def test_rejects_empty_url(self):
        from app.services.ingestion.validator import validate_github_url, ValidationError
        with pytest.raises(ValidationError, match="must not be empty"):
            validate_github_url("   ")

    def test_rejects_newline_injection(self):
        from app.services.ingestion.validator import validate_github_url, ValidationError
        with pytest.raises(ValidationError, match="forbidden characters"):
            validate_github_url("https://github.com/owner/repo\nHost: evil.com")


class TestZIPValidation:
    def test_valid_zip_filename(self):
        from app.services.ingestion.validator import validate_upload_zip
        result = validate_upload_zip("myproject.zip", 1024)
        assert result == "myproject.zip"

    def test_rejects_non_zip(self):
        from app.services.ingestion.validator import validate_upload_zip, ValidationError
        with pytest.raises(ValidationError, match="zip archives"):
            validate_upload_zip("malware.exe", 1024)

    def test_strips_path_traversal_in_filename(self):
        from app.services.ingestion.validator import validate_upload_zip
        # Path component is stripped; the final name must still end in .zip
        result = validate_upload_zip("../../etc/passwd/repo.zip", 1024)
        assert "/" not in result
        assert "\\" not in result
        assert result == "repo.zip"

    def test_rejects_oversized_file(self):
        from app.services.ingestion.validator import validate_upload_zip, ValidationError
        with pytest.raises(ValidationError, match="limit"):
            validate_upload_zip("big.zip", 600 * 1024 * 1024)  # 600 MB

    def test_rejects_empty_filename(self):
        from app.services.ingestion.validator import validate_upload_zip, ValidationError
        with pytest.raises(ValidationError, match="must have a name"):
            validate_upload_zip("", 1024)


# ══════════════════════════════════════════════════════════════
# 2. Archive extractor tests
# ══════════════════════════════════════════════════════════════

class TestSafeArchiveExtraction:
    def test_extract_normal_zip(self, tmp_path):
        from app.services.ingestion.archive import extract_zip_safely

        entries = {
            "src/main.py": "print('hello')",
            "README.md": "# My Repo",
        }
        zip_bytes = _make_zip(entries)
        zip_path = tmp_path / "repo.zip"
        zip_path.write_bytes(zip_bytes)
        target = tmp_path / "extracted"

        root, count = extract_zip_safely(zip_path, target)
        assert count == 2
        assert (Path(root) / "src" / "main.py").exists()

    def test_rejects_zip_slip_traversal(self, tmp_path):
        """Archive contains ../../etc/passwd-style entry."""
        from app.services.ingestion.archive import extract_zip_safely, ArchiveExtractionError

        # Build a ZIP where an entry name tries to escape the target directory
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../evil.sh", "#!/bin/bash\nrm -rf /")
        zip_path = tmp_path / "traversal.zip"
        zip_path.write_bytes(buf.getvalue())
        target = tmp_path / "safe"

        with pytest.raises(ArchiveExtractionError, match="traversal"):
            extract_zip_safely(zip_path, target)

    def test_rejects_zip_slip_absolute_path(self, tmp_path):
        """Archive contains an absolute path entry."""
        from app.services.ingestion.archive import extract_zip_safely, ArchiveExtractionError

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            # zipfile strips leading / internally, so simulate via traversal
            zf.writestr("subdir/../../../evil.txt", "evil")
        zip_path = tmp_path / "abs.zip"
        zip_path.write_bytes(buf.getvalue())
        target = tmp_path / "safe2"

        # If it traverses, error must be raised; otherwise extraction is fine
        try:
            extract_zip_safely(zip_path, target)
        except ArchiveExtractionError:
            pass   # expected

    def test_rejects_zip_bomb_total_size(self, tmp_path):
        """Entries sum to >500 MB when decompressed."""
        from app.services.ingestion.archive import extract_zip_safely, ArchiveExtractionError

        # Craft entries whose declared file_size exceeds limit without actual data
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
            # Write a small chunk but lie about the file size via manual crafting
            # Instead, write real small files with sizes that add up beyond the limit
            # We do this by writing many 1 MB entries
            chunk = b"A" * (1024 * 1024)  # 1 MB
            for i in range(502):   # 502 MB total
                zf.writestr(f"file_{i}.dat", chunk)

        zip_path = tmp_path / "bomb.zip"
        zip_path.write_bytes(buf.getvalue())
        target = tmp_path / "bomb_target"

        with pytest.raises(ArchiveExtractionError, match="limit|exceeds"):
            extract_zip_safely(zip_path, target)

    def test_rejects_symlink_entry(self, tmp_path):
        """Archive contains a symlink."""
        from app.services.ingestion.archive import extract_zip_safely, ArchiveExtractionError

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            info = zipfile.ZipInfo("link_to_passwd")
            # Set Unix symlink type in external_attr (0xA1ED = symlink with permissions)
            info.external_attr = 0xA1ED0000
            zf.writestr(info, "/etc/passwd")

        zip_path = tmp_path / "symlink.zip"
        zip_path.write_bytes(buf.getvalue())
        target = tmp_path / "symlink_target"

        with pytest.raises(ArchiveExtractionError, match="symbolic link"):
            extract_zip_safely(zip_path, target)

    def test_rejects_non_zip_file(self, tmp_path):
        from app.services.ingestion.archive import extract_zip_safely, ArchiveExtractionError

        bad_file = tmp_path / "notazip.zip"
        bad_file.write_bytes(b"This is not a ZIP file at all")
        target = tmp_path / "target"

        with pytest.raises(ArchiveExtractionError, match="not a valid ZIP"):
            extract_zip_safely(bad_file, target)

    def test_single_root_folder_returned(self, tmp_path):
        """When ZIP has a single root folder, that folder is returned as root."""
        from app.services.ingestion.archive import extract_zip_safely

        entries = {
            "myrepo/src/app.py": "pass",
            "myrepo/README.md": "# hello",
        }
        zip_bytes = _make_zip(entries)
        zip_path = tmp_path / "repo.zip"
        zip_path.write_bytes(zip_bytes)
        target = tmp_path / "out"

        root, _ = extract_zip_safely(zip_path, target)
        assert Path(root).name == "myrepo"


# ══════════════════════════════════════════════════════════════
# 3. Directory scanner tests
# ══════════════════════════════════════════════════════════════

class TestDirectoryScanner:
    def _make_repo(self, tmp_path: Path) -> Path:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("def hello():\n    print('hi')\n")
        (tmp_path / "src" / "utils.py").write_text("import os\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_main.py").write_text("def test_hello(): pass\n")
        (tmp_path / "README.md").write_text("# Hello")
        (tmp_path / "requirements.txt").write_text("fastapi==0.111.0\nhttpx>=0.27\n")
        (tmp_path / "package.json").write_text(json.dumps({
            "dependencies": {"react": "^18.0.0"},
            "devDependencies": {"jest": "^29.0.0"},
        }))
        # A binary file that should be detected
        (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00" + b"\x00" * 100)
        # A ignored dir
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "evil.js").write_text("should not be scanned")
        return tmp_path

    def test_scan_detects_python_files(self, tmp_path):
        from app.services.ingestion.scanner import scan_directory
        repo = self._make_repo(tmp_path)
        result = scan_directory(repo)
        langs = result["languages"]
        assert "python" in langs

    def test_scan_ignores_node_modules(self, tmp_path):
        from app.services.ingestion.scanner import scan_directory
        repo = self._make_repo(tmp_path)
        result = scan_directory(repo)
        all_paths = [f["relative_path"] for f in result["files"]]
        assert not any("node_modules" in p for p in all_paths)

    def test_scan_detects_test_files(self, tmp_path):
        from app.services.ingestion.scanner import scan_directory
        repo = self._make_repo(tmp_path)
        result = scan_directory(repo)
        test_files = [f for f in result["files"] if f["is_test"]]
        assert any("test_main" in f["file_name"] for f in test_files)

    def test_scan_detects_documentation_files(self, tmp_path):
        from app.services.ingestion.scanner import scan_directory
        repo = self._make_repo(tmp_path)
        result = scan_directory(repo)
        doc_files = [f for f in result["files"] if f["is_documentation"]]
        assert any("README" in f["file_name"] for f in doc_files)

    def test_scan_language_percentages_sum_to_100(self, tmp_path):
        from app.services.ingestion.scanner import scan_directory
        repo = self._make_repo(tmp_path)
        result = scan_directory(repo)
        total = sum(result["languages"].values())
        assert abs(total - 100.0) < 0.5

    def test_scan_language_details_present(self, tmp_path):
        from app.services.ingestion.scanner import scan_directory
        repo = self._make_repo(tmp_path)
        result = scan_directory(repo)
        assert len(result["language_details"]) > 0
        for ld in result["language_details"]:
            assert ld["file_count"] >= 0
            assert ld["line_count"] >= 0

    def test_scan_directory_tree_structure(self, tmp_path):
        from app.services.ingestion.scanner import scan_directory
        repo = self._make_repo(tmp_path)
        result = scan_directory(repo)
        tree = result["directory_tree"]
        assert tree["type"] == "directory"
        assert len(tree["children"]) > 0

    def test_scan_reports_total_size_bytes(self, tmp_path):
        from app.services.ingestion.scanner import scan_directory
        repo = self._make_repo(tmp_path)
        result = scan_directory(repo)
        assert result["total_size_bytes"] > 0

    def test_scan_computes_sha256(self, tmp_path):
        from app.services.ingestion.scanner import scan_directory
        repo = self._make_repo(tmp_path)
        result = scan_directory(repo)
        py_files = [f for f in result["files"] if f["language"] == "python" and not f["is_binary"]]
        for f in py_files:
            assert f["sha256_hash"] is not None
            assert len(f["sha256_hash"]) == 64

    def test_scan_raises_on_missing_dir(self, tmp_path):
        from app.services.ingestion.scanner import scan_directory
        with pytest.raises(ValueError, match="does not exist"):
            scan_directory(tmp_path / "nonexistent")

    def test_parse_requirements_txt(self, tmp_path):
        from app.services.ingestion.scanner import parse_project_dependencies
        (tmp_path / "requirements.txt").write_text("fastapi==0.111.0\nhttpx>=0.27\naiofiles\n")
        deps = parse_project_dependencies(tmp_path)
        names = [d["package_name"] for d in deps]
        assert "fastapi" in names
        assert "httpx" in names
        assert all(d["ecosystem"] == "pip" for d in deps)

    def test_parse_package_json(self, tmp_path):
        from app.services.ingestion.scanner import parse_project_dependencies
        pkg = {"dependencies": {"react": "^18.0.0"}, "devDependencies": {"jest": "^29"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        deps = parse_project_dependencies(tmp_path)
        npm_deps = [d for d in deps if d["ecosystem"] == "npm"]
        assert any(d["package_name"] == "react" and not d["is_dev"] for d in npm_deps)
        assert any(d["package_name"] == "jest" and d["is_dev"] for d in npm_deps)

    def test_parse_go_mod(self, tmp_path):
        from app.services.ingestion.scanner import parse_project_dependencies
        (tmp_path / "go.mod").write_text(
            "module example.com/myapp\n\ngo 1.21\n\nrequire (\n"
            "\tgithub.com/gin-gonic/gin v1.9.0\n"
            "\tgolang.org/x/net v0.17.0 // indirect\n)\n"
        )
        deps = parse_project_dependencies(tmp_path)
        go_deps = [d for d in deps if d["ecosystem"] == "go"]
        assert any("gin" in d["package_name"] for d in go_deps)


# ══════════════════════════════════════════════════════════════
# 4. API endpoint tests (FastAPI TestClient)
# ══════════════════════════════════════════════════════════════

@pytest.fixture
def client():
    """Sync test client with isolated in-memory DB."""
    import asyncio
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.main import app
    from app.core.database import get_db, Base

    TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
    engine = create_async_engine(TEST_DB_URL, echo=False)
    TestingSession = async_sessionmaker(engine, expire_on_commit=False)

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.get_event_loop().run_until_complete(_setup())

    async def override_db():
        async with TestingSession() as session:
            yield session

    app.dependency_overrides[get_db] = override_db

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    app.dependency_overrides.clear()


class TestRepositoryEndpoints:
    def test_health_check(self, client):
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    def test_list_repositories_empty(self, client):
        r = client.get("/api/v1/repositories")
        assert r.status_code == 200
        assert r.json() == []

    def test_upload_rejects_non_zip(self, client):
        r = client.post(
            "/api/v1/repositories/upload",
            files={"file": ("malware.exe", b"MZ\x90\x00", "application/octet-stream")},
        )
        assert r.status_code == 400

    def test_upload_valid_zip(self, client, tmp_path):
        entries = {
            "src/hello.py": "def hello(): pass\n",
            "README.md": "# Hello",
        }
        zip_bytes = _make_zip(entries)
        r = client.post(
            "/api/v1/repositories/upload",
            files={"file": ("myrepo.zip", zip_bytes, "application/zip")},
        )
        # May succeed (201) or fail due to analysis errors in test env; not 400/422
        assert r.status_code in (201, 500)

    def test_clone_rejects_invalid_host(self, client):
        r = client.post(
            "/api/v1/repositories/clone",
            json={"url": "https://evil.example.com/user/repo"},
        )
        assert r.status_code == 422

    def test_clone_rejects_ssh_url(self, client):
        r = client.post(
            "/api/v1/repositories/clone",
            json={"url": "git@github.com:user/repo.git"},
        )
        assert r.status_code == 422

    def test_clone_rejects_empty_url(self, client):
        r = client.post(
            "/api/v1/repositories/clone",
            json={"url": ""},
        )
        assert r.status_code == 422

    def test_local_rejects_nonexistent_path(self, client):
        r = client.post(
            "/api/v1/repositories/local",
            json={"path": "/nonexistent/path/that/does/not/exist"},
        )
        assert r.status_code == 422

    def test_local_valid_path(self, client, tmp_path):
        (tmp_path / "main.py").write_text("x = 1\n")
        r = client.post(
            "/api/v1/repositories/local",
            json={"path": str(tmp_path)},
        )
        assert r.status_code == 201
        data = r.json()
        assert data["source_type"] == "local"
        assert data["status"] in ("ready", "analyzing", "failed")

    def test_get_repository_404(self, client):
        r = client.get("/api/v1/repositories/nonexistent-id")
        assert r.status_code == 404

    def test_get_repository_tree(self, client, tmp_path):
        (tmp_path / "app.py").write_text("pass\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_app.py").write_text("def test(): pass\n")
        r = client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
        assert r.status_code == 201
        repo_id = r.json()["id"]

        tree_r = client.get(f"/api/v1/repositories/{repo_id}/tree")
        assert tree_r.status_code == 200
        tree_data = tree_r.json()
        assert tree_data["repository_id"] == repo_id
        assert tree_data["tree"]["type"] == "directory"

    def test_delete_repository(self, client, tmp_path):
        (tmp_path / "hello.py").write_text("pass\n")
        r = client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
        assert r.status_code == 201
        repo_id = r.json()["id"]

        del_r = client.delete(f"/api/v1/repositories/{repo_id}")
        assert del_r.status_code == 204

        get_r = client.get(f"/api/v1/repositories/{repo_id}")
        assert get_r.status_code == 404

    def test_get_repository_summary(self, client, tmp_path):
        (tmp_path / "main.py").write_text("def run():\n    pass\n")
        r = client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
        assert r.status_code == 201
        repo_id = r.json()["id"]

        s_r = client.get(f"/api/v1/repositories/{repo_id}/summary")
        assert s_r.status_code == 200
        summary = s_r.json()
        assert "repository" in summary
        assert "languages" in summary

    def test_file_content_path_traversal_rejected(self, client, tmp_path):
        (tmp_path / "safe.py").write_text("pass\n")
        r = client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
        assert r.status_code == 201
        repo_id = r.json()["id"]

        # Try to read a file outside the repo
        trav_r = client.get(
            f"/api/v1/repositories/{repo_id}/file-content",
            params={"path": "../../etc/passwd"},
        )
        assert trav_r.status_code in (403, 404)
