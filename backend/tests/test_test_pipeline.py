import tempfile
from pathlib import Path

import pytest

from agents.test_pipeline import TestGenerationPipeline
from app.core.database import AsyncSessionLocal


@pytest.mark.asyncio
async def test_pipeline_detects_test_gaps_and_reports_quality(client):
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / "service.py").write_text(
            """
from fastapi import FastAPI

app = FastAPI()

@app.get(\"/health\")
def health_check():
    return {\"status\": \"ok\"}

class UserService:
    def fetch_user(self, user_id):
        return {\"id\": user_id}
""".strip() + "\n",
            encoding="utf-8",
        )

        ingest_res = await client.post(
            "/api/v1/repositories/local",
            json={"path": str(repo_path), "name": "test-pipeline-demo"},
        )
        assert ingest_res.status_code == 201, ingest_res.text
        repo_id = ingest_res.json()["id"]

        async with AsyncSessionLocal() as db:
            pipeline = TestGenerationPipeline(db, repo_id)
            result = await pipeline.run()

            assert result["repository_id"] == repo_id
            assert isinstance(result["plan"]["api_test_gaps"], list)
            assert "generated_tests" in result
            assert result["verification"]["status"] in {"passed", "failed", "blocked", "timeout"}
            assert "quality_score" in result
            assert 0.0 <= result["quality_score"]["score"] <= 1.0
