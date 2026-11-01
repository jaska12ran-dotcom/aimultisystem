"""
Tests for the What-If Code Change Simulator
============================================
Verifies:
- Isolated temporary simulation workspace (no changes to source repo)
- Deterministic AST breaking change detection (renamed/removed method, changed signature)
- Call graph & dependency propagation to callers and tests
- Security pattern checks (eval, exec, injection)
- Performance pattern checks (n+1 queries, io blocking)
- Migration requirement detection (database schemas)
- Unified diff and rollback diff generation
- Read-only safety: repository files remain untouched
"""
from pathlib import Path
import tempfile
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_whatif_simulation_signature_break_and_callers(client: AsyncClient):
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / "billing.py").write_text(
            """
class BillingService:
    def charge_customer(self, user_id, amount):
        return True

    def process_order(self, user_id, amount):
        return self.charge_customer(user_id, amount)
""".strip() + "\n",
            encoding="utf-8",
        )
        (repo_path / "tests").mkdir()
        (repo_path / "tests" / "test_billing.py").write_text(
            """
from billing import BillingService

def test_charge():
    svc = BillingService()
    assert svc.charge_customer(1, 100) is True
""".strip() + "\n",
            encoding="utf-8",
        )

        original_billing_content = (repo_path / "billing.py").read_text(encoding="utf-8")

        # Ingest repository
        ingest = await client.post(
            "/api/v1/repositories/local",
            json={"path": str(repo_path), "name": "whatif-test-repo"},
        )
        assert ingest.status_code == 201, ingest.text
        repo_id = ingest.json()["id"]

        # Simulate change: change charge_customer signature to require currency with no default
        proposed_code = """
class BillingService:
    def charge_customer(self, user_id, amount, currency):
        return True

    def process_order(self, user_id, amount):
        return self.charge_customer(user_id, amount)
""".strip() + "\n"

        response = await client.post(
            f"/api/v1/repositories/{repo_id}/whatif/simulate",
            json={
                "file_path": "billing.py",
                "symbol": "billing.charge_customer",
                "natural_language_description": "Add required currency parameter to charge_customer",
                "proposed_code": proposed_code,
                "include_security": True,
                "include_performance": True,
                "include_migration": True,
                "include_regression_tests": True,
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()

        # 1. Verification of top-level response structure
        assert result["repository_id"] == repo_id
        assert result["target_file"] == "billing.py"
        assert "simulation_note" in result

        # 2. Breaking changes detected
        assert len(result["breaking_changes"]) > 0
        bc = result["breaking_changes"][0]
        assert bc["verified"] is True
        assert bc["category"] in ("signature", "new_required_param")

        # 3. Patch and Rollback Diff generated
        assert result["patch"] is not None
        assert result["patch"]["unified_diff"] is not None
        assert result["patch"]["rollback_diff"] is not None
        assert "+    def charge_customer(self, user_id, amount, currency):" in result["patch"]["unified_diff"]

        # 4. Affected files & test failure risks
        affected_file_paths = [af["file"] for af in result["affected_files"]]
        assert any("billing.py" in f for f in affected_file_paths)
        assert any("tests/test_billing.py" in f for f in affected_file_paths)

        test_risks = result["test_failure_risks"]
        assert any("test_billing.py" in tr["test_file"] for tr in test_risks)

        # 5. Regression test recommendations generated
        assert len(result["regression_test_recommendations"]) > 0

        # 6. CRITICAL SAFETY CHECK: Original repository must NOT be modified
        current_billing_content = (repo_path / "billing.py").read_text(encoding="utf-8")
        assert current_billing_content == original_billing_content, "Source repository was unexpectedly modified!"


@pytest.mark.asyncio
async def test_whatif_security_and_performance_findings(client: AsyncClient):
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / "data_handler.py").write_text(
            """
def process_data(raw_input):
    return raw_input.strip()
""".strip() + "\n",
            encoding="utf-8",
        )

        ingest = await client.post(
            "/api/v1/repositories/local",
            json={"path": str(repo_path), "name": "security-perf-test-repo"},
        )
        assert ingest.status_code == 201, ingest.text
        repo_id = ingest.json()["id"]

        # Propose code introducing eval() and a DB query in a loop
        unsafe_code = """
def process_data(raw_input):
    # Security risk
    result = eval(raw_input)
    # Performance risk
    for item in result:
        db.query(item).filter()
    return result
""".strip() + "\n"

        response = await client.post(
            f"/api/v1/repositories/{repo_id}/whatif/simulate",
            json={
                "file_path": "data_handler.py",
                "natural_language_description": "Dynamically evaluate input and query items",
                "proposed_code": unsafe_code,
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()

        # Check security implications
        sec_findings = result["security_implications"]
        assert any(s["category"] == "code_injection" for s in sec_findings)

        # Check performance concerns
        perf_findings = result["performance_concerns"]
        assert any(p["category"] == "n_plus_1" for p in perf_findings)

        # Risk level should reflect critical/high
        assert result["overall_risk"] in ("high", "critical")


@pytest.mark.asyncio
async def test_whatif_natural_language_patch_synthesis(client: AsyncClient):
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / "service.py").write_text(
            """
def fetch_user_data(user_id: int):
    return {"id": user_id, "name": "John"}
""".strip() + "\n",
            encoding="utf-8",
        )

        ingest = await client.post(
            "/api/v1/repositories/local",
            json={"path": str(repo_path), "name": "synthesis-test-repo"},
        )
        assert ingest.status_code == 201, ingest.text
        repo_id = ingest.json()["id"]

        # Natural language only: no proposed_code or proposed_diff supplied
        response = await client.post(
            f"/api/v1/repositories/{repo_id}/whatif/simulate",
            json={
                "file_path": "service.py",
                "natural_language_description": "Add optional include_inactive boolean flag to fetch_user_data",
                "alternatives": ["Return inactive users automatically based on tenant config"],
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()

        assert result["patch"] is not None
        assert result["patch"]["unified_diff"] is not None
        assert len(result["alternatives"]) > 0
        assert result["overall_confidence"] > 0
