import tempfile
from pathlib import Path
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"

@pytest.mark.asyncio
async def test_ingest_local_repository_and_query_twin(client: AsyncClient):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # Create a sample repository structure
        (tmp_path / "calc.py").write_text(
            "class Calculator:\n"
            "    '''Performs basic arithmetic.'''\n"
            "    def add(self, a: int, b: int) -> int:\n"
            "        return a + b\n\n"
            "def compute_total(val: int):\n"
            "    calc = Calculator()\n"
            "    return calc.add(val, 10)\n",
            encoding="utf-8"
        )
        (tmp_path / "requirements.txt").write_text("pytest>=7.0.0\n", encoding="utf-8")

        # Ingest local repo
        ingest_res = await client.post(
            "/api/v1/repositories/local",
            json={"path": str(tmp_path), "name": "sample-calc-repo"}
        )
        assert ingest_res.status_code == 201
        repo_data = ingest_res.json()
        repo_id = repo_data["id"]
        assert repo_data["name"] == "sample-calc-repo"
        assert repo_data["status"] == "ready"
        assert repo_data["total_files"] == 2

        # Query summary
        summary_res = await client.get(f"/api/v1/repositories/{repo_id}/summary")
        assert summary_res.status_code == 200
        summary_data = summary_res.json()
        assert summary_data["total_files"] == 2
        assert summary_data["total_symbols"] >= 3  # Calculator, add, compute_total
        language_names = [l["language"] for l in summary_data["languages"]]
        assert "python" in language_names

        # Query files
        files_res = await client.get(f"/api/v1/repositories/{repo_id}/files")
        assert files_res.status_code == 200
        files = files_res.json()
        file_paths = [f["relative_path"] for f in files]
        assert "calc.py" in file_paths
        assert "requirements.txt" in file_paths

        # Query symbols
        symbols_res = await client.get(f"/api/v1/repositories/{repo_id}/symbols")
        assert symbols_res.status_code == 200
        symbols = symbols_res.json()
        sym_names = [s["name"] for s in symbols]
        assert "Calculator" in sym_names
        assert "add" in sym_names
        assert "compute_total" in sym_names

        # Query file content with symbols for Monaco editor
        content_res = await client.get(
            f"/api/v1/repositories/{repo_id}/file-content",
            params={"path": "calc.py"}
        )
        assert content_res.status_code == 200
        content_data = content_res.json()
        assert "class Calculator:" in content_data["content"]
        assert len(content_data["symbols"]) >= 3
        # Evidence line check
        calc_symbol = next(s for s in content_data["symbols"] if s["name"] == "Calculator")
        assert calc_symbol["start_line"] == 1
