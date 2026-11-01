from pathlib import Path
import tempfile

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_impact_analysis_returns_graph_and_test_evidence(client: AsyncClient):
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / "payments.py").write_text(
            """
class PaymentService:
    def process_payment(self, amount):
        return amount

    def settle(self, amount):
        return self.process_payment(amount)

@app.post("/checkout")
def checkout(amount):
    return PaymentService().settle(amount)
""".strip() + "\n",
            encoding="utf-8",
        )
        (repo_path / "tests").mkdir()
        (repo_path / "tests" / "test_payments.py").write_text(
            """
from payments import PaymentService

def test_process_payment():
    assert PaymentService().process_payment(10) == 10
""".strip() + "\n",
            encoding="utf-8",
        )

        ingest = await client.post(
            "/api/v1/repositories/local",
            json={"path": str(repo_path), "name": "impact-demo"},
        )
        assert ingest.status_code == 201, ingest.text
        repo_id = ingest.json()["id"]

        response = await client.post(
            f"/api/v1/repositories/{repo_id}/impact-analysis",
            json={"symbol": "payments.process_payment"},
        )
        assert response.status_code == 200, response.text
        result = response.json()

        assert result["target"][0]["symbol"].endswith("process_payment")
        assert any(item["symbol"].endswith("settle") for item in result["direct_impact"])
        assert any(item["symbol"] == "checkout" for item in result["indirect_impact"])
        assert any(item["symbol"] == "checkout" for item in result["affected_apis"])
        assert any(item["file"] == "tests/test_payments.py" for item in result["affected_tests"])
        assert result["graph_nodes"]
        assert result["graph_edges"]
        node_ids = {node["id"] for node in result["graph_nodes"]}
        assert all(edge["source"] in node_ids and edge["target"] in node_ids for edge in result["graph_edges"])
        assert all(edge["evidence"]["file"] and edge["evidence"]["line"] for edge in result["graph_edges"])
        assert result["potential_risks"]
        assert 0 < result["confidence"] <= 1
        assert "not a guarantee" in result["caveat"]


@pytest.mark.asyncio
async def test_impact_analysis_returns_empty_evidence_for_unknown_symbol(client: AsyncClient):
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / "module.py").write_text("def known():\n    return True\n", encoding="utf-8")

        ingest = await client.post(
            "/api/v1/repositories/local",
            json={"path": str(repo_path), "name": "impact-empty-demo"},
        )
        assert ingest.status_code == 201, ingest.text

        response = await client.post(
            f"/api/v1/repositories/{ingest.json()['id']}/impact-analysis",
            json={"symbol": "does_not_exist"},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["target"] == []
        assert result["direct_impact"] == []
        assert result["confidence"] == 0
        assert result["confidence_reasons"]
        assert "not a guarantee" in result["caveat"]


@pytest.mark.asyncio
async def test_code_change_identifies_affected_files(client: AsyncClient):
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / "models.py").write_text(
            "def calculate_total(price, qty):\n    return price * qty\n",
            encoding="utf-8",
        )
        (repo_path / "orders.py").write_text(
            "from models import calculate_total\ndef place_order(p, q):\n    return calculate_total(p, q)\n",
            encoding="utf-8",
        )
        (repo_path / "tests").mkdir()
        (repo_path / "tests" / "test_orders.py").write_text(
            "from orders import place_order\ndef test_order():\n    assert place_order(10, 2) == 20\n",
            encoding="utf-8",
        )

        ingest = await client.post(
            "/api/v1/repositories/local",
            json={"path": str(repo_path), "name": "code-change-impact-demo"},
        )
        assert ingest.status_code == 201, ingest.text
        repo_id = ingest.json()["id"]

        # User changed code in models.py (modified signature of calculate_total)
        new_code = "def calculate_total(price, qty, discount=0):\n    return (price * qty) - discount\n"
        response = await client.post(
            f"/api/v1/repositories/{repo_id}/impact-analysis",
            json={
                "file_path": "models.py",
                "changed_code": new_code,
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()

        assert "affected_files" in result
        assert "orders.py" in result["affected_files"]
        assert any("test_orders.py" in f for f in result["affected_files"])
        assert any(item["file"] == "orders.py" for item in result["direct_impact"])
        assert any("test_orders.py" in item["file"] for item in result["affected_tests"])
