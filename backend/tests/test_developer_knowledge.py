from pathlib import Path

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_onboarding_rules_and_code_memory_are_evidence_backed(client: AsyncClient, tmp_path: Path):
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n\n"
        "@app.get('/health')\ndef health():\n    return {'ok': True}\n\n"
        "def validate_limit(limit):\n    if limit <= 0:\n        raise ValueError('limit must be positive')\n    return limit\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("from app import validate_limit\n", encoding="utf-8")
    ingest = await client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
    assert ingest.status_code == 201, ingest.text
    repo_id = ingest.json()["id"]

    onboarding = await client.get(f"/api/v1/repositories/{repo_id}/onboarding")
    assert onboarding.status_code == 200, onboarding.text
    assert onboarding.json()["entry_points"]
    assert onboarding.json()["guided_paths"]

    rules = await client.get(f"/api/v1/repositories/{repo_id}/business-rules")
    assert rules.status_code == 200, rules.text
    result = rules.json()
    assert any(item["explicit"] and "limit <= 0" in item["description"] for item in result["rules"])
    assert result["limitations"]

    memory = await client.get(f"/api/v1/repositories/{repo_id}/code-memory?target=validate_limit")
    assert memory.status_code == 200, memory.text
    assert memory.json()["matched_files"] == ["app.py"]
    assert "not prove developer intent" in memory.json()["limitations"][0]
