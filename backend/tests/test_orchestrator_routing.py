from pathlib import Path

import pytest
from httpx import AsyncClient

from agents.orchestrator import _classify_intent


def test_intent_classifier_routes_key_phrases():
    assert _classify_intent("is my code healthy? health score please") == "health"
    assert _classify_intent("are there vulnerable dependency cve issues") == "dependencies"
    assert _classify_intent("what is the production readiness of this repo") == "readiness"
    assert _classify_intent("check for security vulnerabilities") == "security"


@pytest.mark.asyncio
async def test_orchestrator_dispatches_health_intent(client: AsyncClient, tmp_path: Path):
    (tmp_path / "app.py").write_text(
        "def add(a, b):\n    return a + b\n",
        encoding="utf-8",
    )
    ingest = await client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
    assert ingest.status_code == 201, ingest.text
    repo_id = ingest.json()["id"]

    res = await client.post(
        f"/api/v1/repositories/{repo_id}/ask/orchestrate",
        json={"query": "What is the code health and maintainability score?"},
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["intent"] == "health"
    assert body["steps"]
    step = body["steps"][0]
    assert step["agent"] == "CodeHealthService"
    assert step["status"] == "completed"
    assert body["answer"]


@pytest.mark.asyncio
async def test_orchestrator_dispatches_dependency_intent(client: AsyncClient, tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("requests==2.28.0\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("import requests\n", encoding="utf-8")

    ingest = await client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
    assert ingest.status_code == 201, ingest.text
    repo_id = ingest.json()["id"]

    res = await client.post(
        f"/api/v1/repositories/{repo_id}/ask/orchestrate",
        json={"query": "Do we have any vulnerable dependencies or CVE issues?"},
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["intent"] == "dependencies"
    assert body["steps"][0]["agent"] == "DependencySecurityService"
    assert body["steps"][0]["status"] == "completed"
    assert "requests" in body["answer"].lower()
