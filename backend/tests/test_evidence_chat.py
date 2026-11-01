from pathlib import Path

import pytest
from httpx import AsyncClient

from app.api.v1.endpoints import agents as agents_endpoint


@pytest.mark.asyncio
async def test_chat_returns_ast_citations_and_grounding_limits(client: AsyncClient, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(agents_endpoint.qa_agent.llm, "provider", "disabled")
    monkeypatch.setattr(agents_endpoint.qa_agent.llm, "api_key", "")
    (tmp_path / "auth.py").write_text(
        "def validate_token(token):\n    return token == 'valid'\n",
        encoding="utf-8",
    )

    ingest = await client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
    assert ingest.status_code == 201, ingest.text
    repo_id = ingest.json()["id"]

    response = await client.post(
        f"/api/v1/repositories/{repo_id}/chat",
        json={"message": "Where is validate_token implemented?"},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["citations"][0]["file_path"] == "auth.py"
    assert result["citations"][0]["line_start"] == 1
    assert result["confidence"] == "medium"
    assert result["confidence_reasons"]
    assert "not factual validation" in result["limitations"]
