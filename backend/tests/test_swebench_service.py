"""Tests for SWEBenchService and its REST endpoints."""

import json
from pathlib import Path
import pytest
from httpx import AsyncClient

from app.services.swebench_service import SWEBenchService


SAMPLE_RECORD = {
    "instance_id": "django__django-11099",
    "repo": "django/django",
    "problem_statement": "UsernameValidator accepts trailing newline in ASCII usernames.",
    "patch": "diff --git a/django/contrib/auth/validators.py b/django/contrib/auth/validators.py\n",
    "modified_files": ["django/contrib/auth/validators.py"],
    "fail_to_pass": ["auth_tests.test_validators.ASCIIUsernameValidatorTest.test_trailing_newline"],
    "base_commit": "1234abcd",
    "version": "3.0",
}


@pytest.mark.asyncio
async def test_swebench_service_search_and_get(tmp_path: Path):
    data_file = tmp_path / "swebench.jsonl"
    data_file.write_text(json.dumps(SAMPLE_RECORD) + "\n", encoding="utf-8")

    service = SWEBenchService(data_path=data_file)
    results = service.search_fixes(query="UsernameValidator trailing newline")
    assert results.total_results == 1
    assert len(results.results) == 1
    assert results.results[0].instance_id == "django__django-11099"
    assert results.results[0].repo == "django/django"

    item = service.get_instance("django__django-11099")
    assert item is not None
    assert item.instance_id == "django__django-11099"
    assert "validators.py" in item.patch


@pytest.mark.asyncio
async def test_swebench_search_endpoint(client: AsyncClient, tmp_path: Path):
    from app.core.database import AsyncSessionLocal
    from app.models.repository import Repository

    data_file = tmp_path / "swebench.jsonl"
    data_file.write_text(json.dumps(SAMPLE_RECORD) + "\n", encoding="utf-8")

    async with AsyncSessionLocal() as db:
        repo = Repository(
            id="repo-swe-1",
            name="test-swe-repo",
            source_type="local",
            source_path=str(tmp_path),
            default_branch="main",
            total_files=1,
            total_lines=10,
            total_symbols=1,
            status="ready",
        )
        db.add(repo)
        await db.commit()

    from app.services import swebench_service
    orig_path = swebench_service.DATASET_RAW_PATH
    swebench_service.DATASET_RAW_PATH = data_file

    try:
        res = await client.post(
            "/api/v1/repositories/repo-swe-1/swebench/search",
            json={"query": "UsernameValidator newline", "limit": 3},
        )
        assert res.status_code == 200
        data = res.json()
        assert "results" in data
        assert data["total_results"] == 1
        assert data["results"][0]["instance_id"] == "django__django-11099"

        # Test single instance endpoint
        res2 = await client.get(
            "/api/v1/repositories/repo-swe-1/swebench/django__django-11099"
        )
        assert res2.status_code == 200
        inst_data = res2.json()
        assert inst_data["instance_id"] == "django__django-11099"
    finally:
        swebench_service.DATASET_RAW_PATH = orig_path
