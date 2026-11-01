import tempfile
from pathlib import Path

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_repository_rag_index_search_and_ask(client: AsyncClient):
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
            json={"path": str(repo_path), "name": "rag-demo"},
        )
        assert ingest_res.status_code == 201, ingest_res.text
        repo_id = ingest_res.json()["id"]

        index_res = await client.post(f"/api/v1/repositories/{repo_id}/index")
        assert index_res.status_code == 200, index_res.text
        index_payload = index_res.json()
        assert index_payload["indexed_chunks"] > 0

        search_res = await client.post(
            f"/api/v1/repositories/{repo_id}/search",
            json={"query": "health_check returns status ok", "limit": 3},
        )
        assert search_res.status_code == 200, search_res.text
        matches = search_res.json()
        assert len(matches) > 0
        assert any(item["symbol"] == "health_check" for item in matches)

        ask_res = await client.post(
            f"/api/v1/repositories/{repo_id}/ask",
            json={"question": "What does health_check do?"},
        )
        assert ask_res.status_code == 200, ask_res.text
        answer_payload = ask_res.json()
        assert "answer" in answer_payload
        assert "evidence" in answer_payload
        assert answer_payload["confidence"] in {"high", "medium", "low"}
        assert len(answer_payload["evidence"]) > 0
        assert "cannot determine" in answer_payload["answer"].lower() or "status" in answer_payload["answer"].lower() or "health" in answer_payload["answer"].lower()
