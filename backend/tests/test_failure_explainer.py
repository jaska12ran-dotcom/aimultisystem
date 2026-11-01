from pathlib import Path

import pytest
from httpx import AsyncClient


ASSERTION_FAILURE_OUTPUT = """
============================= test session starts =============================
collected 2 items

test_billing.py F.                                                        [ 50%]

================================== FAILURES ===================================
______________________________ test_invoice_total ______________________________

def test_invoice_total():
        invoice = Invoice(items=[10, 20])
>       assert invoice.total() == 30
E       assert 0 == 30
E        +  where 0 = Invoice(items=[10, 20]).total()

test_billing.py:14: AssertionError
=========================== short test summary info ===========================
FAILED test_billing.py::test_invoice_total - assert 0 == 30
========================= 1 failed, 1 passed in 0.42s =========================
""".strip()


IMPORT_FAILURE_OUTPUT = """
=================================== FAILURES ===================================
___________________________________ test_api ___________________________________

    def test_api():
>       import nonexistent_module
E       ModuleNotFoundError: No module named 'nonexistent_module'

test_api.py:3: ModuleNotFoundError
""".strip()


@pytest.mark.asyncio
async def test_failure_explainer_classifies_assertion_failures(client: AsyncClient, tmp_path: Path):
    (tmp_path / "billing.py").write_text(
        "class Invoice:\n"
        "    def __init__(self, items=None):\n"
        "        self.items = items or []\n"
        "    def total(self):\n"
        "        return 0\n",
        encoding="utf-8",
    )
    ingest = await client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
    assert ingest.status_code == 201, ingest.text
    repo_id = ingest.json()["id"]

    res = await client.post(
        f"/api/v1/repositories/{repo_id}/tests/explain-failures",
        json={"execution_output": ASSERTION_FAILURE_OUTPUT},
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["failures_found"] == 1
    explanation = body["explanations"][0]
    assert explanation["test_name"].strip() == "test_invoice_total"
    assert explanation["category"] == "assertion"
    assert "assert" in explanation["summary"].lower()
    assert explanation["likely_cause"]
    assert explanation["suggested_fix"]
    assert explanation["evidence"]
    assert body["category_counts"] == {"assertion": 1}
    assert body["limitations"]


@pytest.mark.asyncio
async def test_failure_explainer_classifies_import_failures(client: AsyncClient, tmp_path: Path):
    (tmp_path / "main.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    ingest = await client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
    assert ingest.status_code == 201, ingest.text
    repo_id = ingest.json()["id"]

    res = await client.post(
        f"/api/v1/repositories/{repo_id}/tests/explain-failures",
        json={"execution_output": IMPORT_FAILURE_OUTPUT},
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["failures_found"] == 1
    explanation = body["explanations"][0]
    assert explanation["category"] == "import"
    assert "nonexistent_module" in explanation["summary"]
    assert "import" in explanation["suggested_fix"].lower()


@pytest.mark.asyncio
async def test_failure_explainer_handles_clean_output_gracefully(client: AsyncClient, tmp_path: Path):
    (tmp_path / "app.py").write_text("def ok():\n    return True\n", encoding="utf-8")
    ingest = await client.post("/api/v1/repositories/local", json={"path": str(tmp_path)})
    assert ingest.status_code == 201, ingest.text
    repo_id = ingest.json()["id"]

    res = await client.post(
        f"/api/v1/repositories/{repo_id}/tests/explain-failures",
        json={"execution_output": "2 passed in 0.11s"},
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["failures_found"] == 0
    assert body["explanations"] == []
    assert "No parseable test failures" in body["summary"]
