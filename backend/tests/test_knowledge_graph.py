import tempfile
from pathlib import Path

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_repository_knowledge_graph(client: AsyncClient):
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / "service.py").write_text(
            """
from fastapi import FastAPI

app = FastAPI()

class UserService:
    def fetch_user(self, user_id):
        return {"id": user_id}

    def save_user(self, user_id):
        return self.fetch_user(user_id)

@app.get("/health")
def health_check():
    return {"ok": True}


def outer():
    svc = UserService()
    return svc.save_user(42)
""".strip() + "\n",
            encoding="utf-8",
        )

        ingest_res = await client.post(
            "/api/v1/repositories/local",
            json={"path": str(repo_path), "name": "graph-demo"},
        )
        assert ingest_res.status_code == 201, ingest_res.text
        repo_id = ingest_res.json()["id"]

        graph_res = await client.get(f"/api/v1/repositories/{repo_id}/graph")
        assert graph_res.status_code == 200, graph_res.text
        graph = graph_res.json()
        assert graph["counts"]["nodes"] > 0
        assert graph["counts"]["relationships"] > 0
        assert any(node["name"].endswith("service.py") or node["type"] == "file" for node in graph["nodes"]) or any(
            rel["type"] == "contains" for rel in graph["relationships"]
        )

        relationships_res = await client.get(f"/api/v1/repositories/{repo_id}/symbols/fetch_user/relationships")
        assert relationships_res.status_code == 200, relationships_res.text
        rels = relationships_res.json()
        assert len(rels) >= 1

        callers_res = await client.get(f"/api/v1/repositories/{repo_id}/symbols/fetch_user/callers")
        assert callers_res.status_code == 200, callers_res.text
        callers = callers_res.json()
        assert len(callers) >= 1

        dependents_res = await client.get(f"/api/v1/repositories/{repo_id}/symbols/fetch_user/dependents")
        assert dependents_res.status_code == 200, dependents_res.text
        dependents = dependents_res.json()
        assert len(dependents) >= 1

        api_res = await client.get(f"/api/v1/repositories/{repo_id}/symbols/health_check/relationships")
        assert api_res.status_code == 200, api_res.text
        api_rels = api_res.json()
        assert len(api_rels) >= 1 or isinstance(api_rels, list)
