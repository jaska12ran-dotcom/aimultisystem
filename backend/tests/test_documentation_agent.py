import tempfile
from pathlib import Path

import pytest
from httpx import AsyncClient

from agents.documentation_agent import DocumentationAgent, DocumentationDriftDetector


@pytest.mark.asyncio
async def test_documentation_agent_verifies_sections_and_drift(client: AsyncClient):
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
        (repo_path / "README.md").write_text(
            "# Demo\n\nThis project exposes /health and the old removed_function API.\n",
            encoding="utf-8",
        )

        ingest_res = await client.post(
            "/api/v1/repositories/local",
            json={"path": str(repo_path), "name": "doc-demo"},
        )
        assert ingest_res.status_code == 201, ingest_res.text
        repo_id = ingest_res.json()["id"]

        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            agent = DocumentationAgent()
            sections = await agent.generate_repository_sections(db, repo_id)
            assert len(sections) >= 9
            assert all(item["confidence"] in {"high", "medium", "low"} for item in sections)
            assert all("unsupported_statements" in item for item in sections)

            drift = await DocumentationDriftDetector.detect_drift(
                db,
                repo_id,
                {"content": "# Demo\n\nThis project exposes /health and the old removed_function API.\n"},
            )
            assert drift["has_drift"] is True
            assert any(issue["issue_type"] in {"outdated_api", "removed_function"} for issue in drift["issues"])
            assert any(issue.get("suggested_correction") for issue in drift["issues"])
