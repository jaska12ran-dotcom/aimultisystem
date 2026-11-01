from pathlib import Path

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_code_health_returns_all_dimensions_and_consistent_score(client: AsyncClient, tmp_path: Path):
    (tmp_path / "app.py").write_text(
        "def compute_total(items):\n"
        "    '''Compute the running total of items.'''\n"
        "    total = 0\n"
        "    for item in items:\n"
        "        total += item\n"
        "    return total\n",
        encoding="utf-8",
    )

    ingest = await client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
    assert ingest.status_code == 201, ingest.text
    repo_id = ingest.json()["id"]

    response = await client.get(f"/api/v1/repositories/{repo_id}/code-health")
    assert response.status_code == 200, response.text
    result = response.json()

    # Structural contract.
    assert result["repository_id"] == repo_id
    assert 0.0 <= result["overall_score"] <= 100.0
    assert result["grade"] in {"A", "B", "C", "D", "F"}
    assert result["limitations"]
    assert result["summary"]

    dimension_names = {d["name"] for d in result["dimensions"]}
    assert dimension_names == {
        "security", "tests", "documentation", "dependencies", "structure", "stability",
    }

    # Weights must sum to ~1 and the overall score must equal the weighted sum.
    weight_sum = sum(d["weight"] for d in result["dimensions"])
    assert weight_sum == pytest.approx(1.0, abs=1e-6)

    recomputed = sum(d["score"] * d["weight"] for d in result["dimensions"])
    assert recomputed == pytest.approx(result["overall_score"], abs=0.15)

    # Every dimension carries a grade and at least one finding.
    for dimension in result["dimensions"]:
        assert dimension["grade"] in {"A", "B", "C", "D", "F"}
        assert 0.0 <= dimension["score"] <= 100.0
        assert dimension["findings"]


@pytest.mark.asyncio
async def test_code_health_is_deterministic_across_calls(client: AsyncClient, tmp_path: Path):
    (tmp_path / "service.py").write_text(
        "class Invoice:\n"
        "    '''Represents a billing invoice.'''\n"
        "    def total(self):\n"
        "        return 0\n",
        encoding="utf-8",
    )

    ingest = await client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
    assert ingest.status_code == 201, ingest.text
    repo_id = ingest.json()["id"]

    first = (await client.get(f"/api/v1/repositories/{repo_id}/code-health")).json()
    second = (await client.get(f"/api/v1/repositories/{repo_id}/code-health")).json()

    # Deterministic service: identical inputs yield identical scores.
    assert first["overall_score"] == second["overall_score"]
    assert first["grade"] == second["grade"]
    assert [d["score"] for d in first["dimensions"]] == [d["score"] for d in second["dimensions"]]
