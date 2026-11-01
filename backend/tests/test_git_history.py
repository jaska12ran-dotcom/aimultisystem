from pathlib import Path
import tempfile

import git
import pytest
from httpx import AsyncClient


def _initialize_history(repo_path: Path):
    repository = git.Repo.init(repo_path)
    with repository.config_writer() as config:
        config.set_value("user", "name", "History Test Author")
        config.set_value("user", "email", "history@example.test")
    source = repo_path / "service.py"
    source.write_text(
        '@app.post("/pay")\ndef process_payment():\n    return True\n',
        encoding="utf-8",
    )
    for index in range(5):
        with source.open("a", encoding="utf-8") as stream:
            stream.write(f"# payment change {index}\n")
        repository.index.add(["service.py"])
        repository.index.commit(
            f"Improve payment validation for case {index}",
            author=git.Actor("History Test Author", "history@example.test"),
            committer=git.Actor("History Test Author", "history@example.test"),
        )
    return repository


@pytest.mark.asyncio
async def test_git_history_analysis_and_why_answer_are_evidence_backed(client: AsyncClient):
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        git_repo = _initialize_history(repo_path)

        ingest = await client.post(
            "/api/v1/repositories/local",
            json={"path": str(repo_path), "name": "git-history-demo"},
        )
        assert ingest.status_code == 201, ingest.text
        repo_id = ingest.json()["id"]

        analysis_response = await client.get(
            f"/api/v1/repositories/{repo_id}/history-analysis"
        )
        assert analysis_response.status_code == 200, analysis_response.text
        analysis = analysis_response.json()

        assert analysis["history_available"] is True
        assert analysis["commits_analyzed"] == 5
        assert git_repo.active_branch.name in analysis["branches"]
        assert analysis["branch_history_available"] is True
        file_summary = next(item for item in analysis["files"] if item["file"] == "service.py")
        assert file_summary["change_frequency"] == 5
        assert file_summary["churn"] > 0
        assert file_summary["critical_component"] is True
        assert file_summary["recently_modified_critical"] is True
        assert file_summary["is_hotspot"] is True
        assert file_summary["evidence"]

        why_response = await client.post(
            f"/api/v1/repositories/{repo_id}/history/why",
            json={"target": "process_payment"},
        )
        assert why_response.status_code == 200, why_response.text
        why = why_response.json()
        assert why["sufficient_history"] is True
        assert "Improve payment validation" in why["answer"]
        assert why["evidence"]
        assert "do not establish intent" in why["answer"]
        git_repo.close()


@pytest.mark.asyncio
async def test_why_code_exists_explicitly_reports_insufficient_history(client: AsyncClient):
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / "service.py").write_text(
            "def process_payment():\n    return True\n",
            encoding="utf-8",
        )
        ingest = await client.post(
            "/api/v1/repositories/local",
            json={"path": str(repo_path), "name": "history-empty-demo"},
        )
        assert ingest.status_code == 201, ingest.text
        repo_id = ingest.json()["id"]

        why_response = await client.post(
            f"/api/v1/repositories/{repo_id}/history/why",
            json={"target": "process_payment"},
        )
        assert why_response.status_code == 200, why_response.text
        why = why_response.json()
        assert why["sufficient_history"] is False
        assert why["evidence"] == []
        assert "cannot determine" in why["answer"].lower()
        assert "No developer intention has been inferred." in why["limitation"]
