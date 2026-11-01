from pathlib import Path

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_technical_debt_reports_measured_cycles_and_duplicate_functions(client: AsyncClient, tmp_path: Path):
    (tmp_path / "alpha.py").write_text(
        "from beta import beta\n\n"
        "def repeated(value):\n    first = value + 1\n    second = first * 2\n    return second\n",
        encoding="utf-8",
    )
    (tmp_path / "beta.py").write_text(
        "from alpha import repeated\n\n"
        "def beta(value):\n    first = value + 1\n    second = first * 2\n    return second\n",
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("unused-package==1.0\n", encoding="utf-8")
    ingest = await client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
    assert ingest.status_code == 201, ingest.text
    response = await client.get(f"/api/v1/repositories/{ingest.json()['id']}/technical-debt")
    assert response.status_code == 200, response.text
    result = response.json()
    categories = {item["category"] for item in result["findings"]}
    assert "circular_dependency" in categories
    assert "duplicate_code" in categories
    assert "unused_dependency_candidate" in categories
    assert all(item["remediation"] for item in result["findings"])
    assert result["limitations"]
