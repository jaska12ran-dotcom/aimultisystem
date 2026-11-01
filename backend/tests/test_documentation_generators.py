from pathlib import Path

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_readme_doc_type_generates_grounded_readme(client: AsyncClient, tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("fastapi==0.110.0\n", encoding="utf-8")
    (tmp_path / "service.py").write_text(
        "from fastapi import FastAPI\n\n"
        "app = FastAPI()\n\n"
        "@app.get('/health')\n"
        "def health_check():\n"
        "    '''Return service health.'''\n"
        "    return {'status': 'ok'}\n\n"
        "class UserService:\n"
        "    '''Handles user lookups.'''\n"
        "    def fetch_user(self, user_id):\n"
        "        return {'id': user_id}\n",
        encoding="utf-8",
    )

    ingest = await client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
    assert ingest.status_code == 201, ingest.text
    repo_id = ingest.json()["id"]

    res = await client.post(
        f"/api/v1/repositories/{repo_id}/docs/generate",
        json={"doc_type": "readme"},
    )
    assert res.status_code == 201, res.text
    body = res.json()

    content = body["content_markdown"]
    assert body["doc_type"] == "readme"
    assert "# " in content                       # has a top-level title
    assert "## Dependencies" in content          # manifests were detected
    assert "requirements.txt" in content
    assert "## API Surface" in content           # api route table rendered
    assert "health_check" in content
    assert "## Key Components" in content
    assert "UserService" in content
    assert "Getting Started" in content


@pytest.mark.asyncio
async def test_diagram_doc_type_generates_valid_mermaid(client: AsyncClient, tmp_path: Path):
    # Two first-party modules with a cross-module import edge.
    (tmp_path / "alpha.py").write_text(
        "from beta import helper\n\n"
        "def main():\n"
        "    return helper()\n",
        encoding="utf-8",
    )
    (tmp_path / "beta.py").write_text(
        "def helper():\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )

    ingest = await client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
    assert ingest.status_code == 201, ingest.text
    repo_id = ingest.json()["id"]

    res = await client.post(
        f"/api/v1/repositories/{repo_id}/docs/generate",
        json={"doc_type": "diagram"},
    )
    assert res.status_code == 201, res.text
    body = res.json()

    content = body["content_markdown"]
    assert body["doc_type"] == "diagram"
    assert "```mermaid" in content
    assert "flowchart LR" in content
    assert "-->" in content          # at least one rendered edge
    assert "```" in content          # code fence closed
    # Both modules should appear as nodes.
    assert "alpha" in content
    assert "beta" in content


@pytest.mark.asyncio
async def test_diagram_doc_type_handles_repo_without_module_edges(client: AsyncClient, tmp_path: Path):
    # Single module, no first-party imports -> graceful fallback, still valid mermaid.
    (tmp_path / "solo.py").write_text("import os\n\ndef run():\n    return os.getcwd()\n", encoding="utf-8")

    ingest = await client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
    assert ingest.status_code == 201, ingest.text
    repo_id = ingest.json()["id"]

    res = await client.post(
        f"/api/v1/repositories/{repo_id}/docs/generate",
        json={"doc_type": "diagram"},
    )
    assert res.status_code == 201, res.text
    content = res.json()["content_markdown"]

    # Must still be valid, renderable mermaid even with nothing to draw.
    assert "```mermaid" in content
    assert "flowchart LR" in content
    assert content.count("```") % 2 == 0  # balanced fences
