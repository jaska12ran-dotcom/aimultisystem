import tempfile
import zipfile
from pathlib import Path
import pytest
from app.services.ingestion.scanner import scan_directory, parse_project_dependencies, is_test_file
from app.services.ingestion.archive import extract_zip_safely, ArchiveExtractionError

def test_test_file_detection():
    assert is_test_file("tests/test_auth.py", "test_auth.py") is True
    assert is_test_file("src/components/button.test.tsx", "button.test.tsx") is True
    assert is_test_file("src/main.py", "main.py") is False

def test_directory_scanner():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # Create some files
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "index.py").write_text("def hello():\n    print('hi')\n", encoding="utf-8")
        (src_dir / "utils.js").write_text("console.log('util');\n", encoding="utf-8")
        
        req = tmp_path / "requirements.txt"
        req.write_text("fastapi>=0.100.0\npydantic==2.5.0\n", encoding="utf-8")

        result = scan_directory(tmp_path)
        assert result["total_files"] == 3
        assert result["total_lines"] > 0
        assert "python" in result["languages"]
        assert "javascript" in result["languages"]

        deps = parse_project_dependencies(tmp_path)
        assert len(deps) == 2
        dep_names = [d["package_name"] for d in deps]
        assert "fastapi" in dep_names
        assert "pydantic" in dep_names

def test_safe_zip_extraction():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        zip_file = tmp_path / "sample.zip"
        target_dir = tmp_path / "extracted"

        # Build clean zip
        with zipfile.ZipFile(zip_file, "w") as zf:
            zf.writestr("app/main.py", "print('hello from zip')")
            zf.writestr("app/config.json", '{"version": "1.0"}')

        extracted_dir, count = extract_zip_safely(zip_file, target_dir)
        assert count == 2
        assert Path(extracted_dir).exists()
        assert (Path(extracted_dir) / "main.py").exists() or (Path(extracted_dir) / "app" / "main.py").exists()

def test_zip_slip_protection():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        malicious_zip = tmp_path / "malicious.zip"
        target_dir = tmp_path / "extracted"

        with zipfile.ZipFile(malicious_zip, "w") as zf:
            zf.writestr("../../../evil.txt", "exploit")

        with pytest.raises(ArchiveExtractionError):
            extract_zip_safely(malicious_zip, target_dir)
