import pytest
import tempfile
from pathlib import Path
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_agent_documentation_and_testing_lifecycle(client: AsyncClient):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create sample Python project with class, function, and models
        (tmp_path / "service.py").write_text(
            "class UserService:\n"
            "    '''Handles user accounts and profiles.'''\n"
            "    def __init__(self):\n"
            "        self.users = {}\n"
            "    def register_user(self, username: str, email: str) -> dict:\n"
            "        '''Registers a new user into the service.'''\n"
            "        user = {'username': username, 'email': email, 'active': True}\n"
            "        self.users[username] = user\n"
            "        return user\n\n"
            "def calculate_tax(amount: float, rate: float = 0.1) -> float:\n"
            "    '''Calculates tax on an amount.'''\n"
            "    if amount < 0:\n"
            "        raise ValueError('Amount cannot be negative')\n"
            "    return amount * rate\n",
            encoding="utf-8"
        )

        # Ingest local repo
        ingest_res = await client.post(
            "/api/v1/repositories/local",
            json={"path": str(tmp_path), "name": "sample-agent-repo"}
        )
        assert ingest_res.status_code == 201
        repo_id = ingest_res.json()["id"]

        # 1. Test Architecture Documentation Generation
        doc_res = await client.post(
            f"/api/v1/repositories/{repo_id}/docs/generate",
            json={"doc_type": "architecture", "title": "System Architecture"}
        )
        assert doc_res.status_code == 201
        doc_data = doc_res.json()
        assert doc_data["title"] == "System Architecture"
        assert "UserService" in doc_data["content_markdown"]
        assert doc_data["doc_type"] == "architecture"

        # 2. Test Listing Generated Docs
        list_docs_res = await client.get(f"/api/v1/repositories/{repo_id}/docs")
        assert list_docs_res.status_code == 200
        docs_list = list_docs_res.json()
        assert len(docs_list) >= 1

        # 3. Test Module Documentation Generation
        mod_doc_res = await client.post(
            f"/api/v1/repositories/{repo_id}/docs/generate",
            json={"doc_type": "module", "target_file": "service.py"}
        )
        assert mod_doc_res.status_code == 201
        assert "register_user" in mod_doc_res.json()["content_markdown"]

        # 4. Test Test Planning
        plan_res = await client.post(
            f"/api/v1/repositories/{repo_id}/tests/plan",
            json={"target_file": "service.py", "test_framework": "pytest"}
        )
        assert plan_res.status_code == 200
        plan_data = plan_res.json()
        assert len(plan_data["planned_cases"]) >= 1
        assert plan_data["test_framework"] == "pytest"

        # 5. Test Test Generation with Immediate Execution
        gen_test_res = await client.post(
            f"/api/v1/repositories/{repo_id}/tests/generate",
            json={
                "target_file": "service.py",
                "test_framework": "pytest",
                "execute_immediately": True,
            }
        )
        assert gen_test_res.status_code == 201
        test_suite = gen_test_res.json()
        test_id = test_suite["id"]
        assert "def test_" in test_suite["test_code"]
        assert test_suite["status"] in ("passed", "failed")
        assert test_suite["tests_run"] >= 1

        # 6. Test Sandbox Test Execution Endpoint
        exec_res = await client.post(f"/api/v1/repositories/{repo_id}/tests/{test_id}/execute")
        assert exec_res.status_code == 200
        exec_data = exec_res.json()
        assert exec_data["status"] in ("passed", "failed")
        assert exec_data["tests_run"] >= 1
        assert exec_data["duration_ms"] > 0

        # 7. Test Codebase Q&A Chat with Citations
        chat_res = await client.post(
            f"/api/v1/repositories/{repo_id}/chat",
            json={"message": "Where is calculate_tax implemented?"}
        )
        assert chat_res.status_code == 200
        chat_data = chat_res.json()
        assert "calculate_tax" in chat_data["reply"]
        assert len(chat_data["citations"]) >= 1
        assert chat_data["citations"][0]["file_path"] == "service.py"
