from pathlib import Path

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_test_strength_and_regression_selection_use_indexed_evidence(client: AsyncClient, tmp_path: Path):
    (tmp_path / "service.py").write_text(
        "def authorize(user):\n"
        "    if not user:\n"
        "        raise ValueError('user required')\n"
        "    return user == 'admin'\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_service.py").write_text(
        "from service import authorize\n\n"
        "def test_authorize_admin():\n"
        "    assert authorize('admin') is True\n",
        encoding="utf-8",
    )
    ingest = await client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
    assert ingest.status_code == 201, ingest.text
    repo_id = ingest.json()["id"]

    strength_response = await client.get(f"/api/v1/repositories/{repo_id}/tests/strength")
    assert strength_response.status_code == 200, strength_response.text
    strength = strength_response.json()
    assert strength["test_file_count"] == 1
    assert strength["python_test_file_count"] == 1
    assert strength["discovered_test_function_count"] == 1
    assert strength["test_files_with_assertions"] == 1
    authorize = next(item for item in strength["symbols"] if item["symbol"].endswith("authorize"))
    assert authorize["mapping_status"] == "linked"
    assert authorize["branch_count"] == 1
    assert authorize["raise_count"] == 1
    assert "tests/test_service.py" in authorize["linked_tests"]
    assert any("Candidate gap" in item for item in authorize["potential_gaps"])

    selection_response = await client.post(
        f"/api/v1/repositories/{repo_id}/tests/select",
        json={"changed_files": ["service.py"], "changed_symbols": ["authorize"]},
    )
    assert selection_response.status_code == 200, selection_response.text
    selection = selection_response.json()
    assert selection["matched_symbols"]
    assert selection["selected_tests"][0]["file"] == "tests/test_service.py"
    assert selection["selected_tests"][0]["confidence"] == "high"
    assert selection["full_suite_recommended"] is True
    assert selection["recommendation_reasons"]


@pytest.mark.asyncio
async def test_regression_selection_rejects_empty_targets(client: AsyncClient, tmp_path: Path):
    (tmp_path / "service.py").write_text("def known():\n    return True\n", encoding="utf-8")
    ingest = await client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
    assert ingest.status_code == 201, ingest.text
    response = await client.post(
        f"/api/v1/repositories/{ingest.json()['id']}/tests/select",
        json={"changed_files": [], "changed_symbols": []},
    )
    assert response.status_code == 422
