from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.repository import RepositoryVectorChunk


@pytest.mark.asyncio
async def test_reindex_updates_only_changed_file_indexes_and_freshness(client: AsyncClient, tmp_path):
    (tmp_path / "target.py").write_text("def old_target():\n    return 'before'\n", encoding="utf-8")
    (tmp_path / "caller.py").write_text(
        "from target import old_target\n\ndef caller():\n    return old_target()\n",
        encoding="utf-8",
    )
    (tmp_path / "obsolete.py").write_text("def obsolete():\n    return 0\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("Initial repository notes.\n", encoding="utf-8")

    ingest = await client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
    assert ingest.status_code == 201, ingest.text
    repo_id = ingest.json()["id"]

    first_status = await client.get(f"/api/v1/repositories/{repo_id}/index-status")
    assert first_status.status_code == 200
    assert first_status.json()["status"] == "ready"
    assert first_status.json()["last_successful_at"]

    indexed = await client.post(f"/api/v1/repositories/{repo_id}/index")
    assert indexed.status_code == 200, indexed.text

    (tmp_path / "target.py").write_text("def new_target():\n    return 'after'\n", encoding="utf-8")
    (tmp_path / "added.py").write_text("def added():\n    return True\n", encoding="utf-8")
    (tmp_path / "obsolete.py").unlink()

    refreshed = await client.post(f"/api/v1/repositories/{repo_id}/reindex")
    assert refreshed.status_code == 200, refreshed.text
    result = refreshed.json()
    assert result["added_files"] == 1
    assert result["updated_files"] == 1
    assert result["deleted_files"] == 1
    assert result["unchanged_files"] == 2
    assert result["refreshed_rag_files"] >= 1
    assert result["last_successful_at"]

    files = await client.get(f"/api/v1/repositories/{repo_id}/files")
    paths = {item["relative_path"] for item in files.json()}
    assert {"target.py", "caller.py", "added.py", "README.md"} == paths
    assert "obsolete.py" not in paths

    symbols = await client.get(f"/api/v1/repositories/{repo_id}/symbols")
    names = {item["name"] for item in symbols.json()}
    assert "new_target" in names
    assert "old_target" not in names

    async with AsyncSessionLocal() as db:
        chunks = await db.execute(
            select(RepositoryVectorChunk).where(
                RepositoryVectorChunk.repository_id == repo_id,
                RepositoryVectorChunk.file_path == "target.py",
            )
        )
        target_chunks = chunks.scalars().all()
    assert target_chunks
    assert all("before" not in chunk.content for chunk in target_chunks)

    no_op = await client.post(f"/api/v1/repositories/{repo_id}/reindex")
    assert no_op.status_code == 200, no_op.text
    assert no_op.json()["added_files"] == 0
    assert no_op.json()["updated_files"] == 0
    assert no_op.json()["deleted_files"] == 0
    assert no_op.json()["unchanged_files"] == 4

