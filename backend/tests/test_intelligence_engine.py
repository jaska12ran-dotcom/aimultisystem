import tempfile
from pathlib import Path

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_repository_analysis_engine(client: AsyncClient):
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / "app.py").write_text(
            """
from fastapi import FastAPI

app = FastAPI()

class UserModel:
    pass

@app.get(\"/health\")
def health_check():
    return {\"status\": \"ok\"}
""".strip() + "\n",
            encoding="utf-8",
        )
        (repo_path / "package.json").write_text(
            '{\n  "dependencies": {\n    "react": "^18.0.0"\n  }\n}\n',
            encoding="utf-8",
        )

        ingest_res = await client.post(
            "/api/v1/repositories/local",
            json={"path": str(repo_path), "name": "analysis-demo"},
        )
        assert ingest_res.status_code == 201, ingest_res.text
        repo_id = ingest_res.json()["id"]

        analyze_res = await client.post(f"/api/v1/repositories/{repo_id}/analyze")
        assert analyze_res.status_code == 200, analyze_res.text
        analysis = analyze_res.json()
        assert analysis["repository_id"] == repo_id
        assert analysis["total_files"] >= 2
        assert any(item["symbol_name"] == "UserModel" for item in analysis["classes"])
        assert any(item["symbol_name"] == "health_check" for item in analysis["functions"])
        assert any(item["path"] == "/health" for item in analysis["api_endpoints"])
        assert any(item["package_name"] == "react" for item in analysis["dependencies"])

        symbols_res = await client.get(f"/api/v1/repositories/{repo_id}/symbols")
        assert symbols_res.status_code == 200
        names = {sym["name"] for sym in symbols_res.json()}
        assert {"UserModel", "health_check"}.issubset(names)

        deps_res = await client.get(f"/api/v1/repositories/{repo_id}/dependencies")
        assert deps_res.status_code == 200
        dep_names = {dep["package_name"] for dep in deps_res.json()}
        assert "react" in dep_names
