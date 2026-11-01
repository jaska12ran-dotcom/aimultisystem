import tempfile
from pathlib import Path

import pytest

from agents.security_agent import SecurityAgent


@pytest.mark.asyncio
async def test_security_analysis_returns_safe_summary_and_dashboard(client):
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / "app.py").write_text(
            "def safe_function():\n    return 'ok'\n",
            encoding="utf-8",
        )

        ingest = await client.post(
            "/api/v1/repositories/local",
            json={"path": str(repo_path), "name": "security-demo"},
        )
        assert ingest.status_code == 201, ingest.text
        repo_id = ingest.json()["id"]

        res = await client.post(f"/api/v1/repositories/{repo_id}/security/analyze")
        assert res.status_code == 200, res.text
        body = res.json()

        assert body["summary"] == "No detected issue from the configured security checks."
        assert body["findings"] == []
        assert body["dashboard"]["total_findings"] == 0
        assert set(["critical", "high", "medium", "low", "informational"]).issubset(body["dashboard"].keys())


def test_security_findings_are_normalized_and_duplicates_merged():
    agent = SecurityAgent()

    semgrep_item = {
        "check_id": "python.lang.security.audit.dangerous-subprocess-use",
        "path": "src/runner.py",
        "start": {"line": 12},
        "extra": {
            "severity": "ERROR",
            "message": "Subprocess call is unsafe.",
            "metadata": {"category": "command-execution", "remediation": "Use a safe API."},
            "confidence": "high",
        },
    }
    bandit_item = {
        "issue_severity": "HIGH",
        "issue_confidence": "MEDIUM",
        "issue_text": "Subprocess call is unsafe.",
        "filename": "src/runner.py",
        "line_number": 12,
        "issue_category": "command-execution",
    }

    normalized = agent._normalize_semgrep([semgrep_item]) + agent._normalize_bandit({"results": [bandit_item]})
    merged = agent.merge_findings(normalized)

    assert len(merged) == 1
    assert merged[0].severity == "high"
    assert "semgrep" in merged[0].tool
    assert "bandit" in merged[0].tool
    assert merged[0].category == "command-execution"
    assert merged[0].file == "src/runner.py"
    assert merged[0].line == 12
    assert "unsafe" in merged[0].description.lower()


def test_iter_source_files_prunes_skipped_directories(tmp_path: Path):
    """Heavy directories are pruned during traversal, not filtered afterwards."""
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    for skipped in ("node_modules", ".git", ".venv", "dist", "__pycache__", "site-packages"):
        target = tmp_path / skipped / "pkg"
        target.mkdir(parents=True)
        (target / "mod.py").write_text("eval('1')\n", encoding="utf-8")

    yielded = {
        path.relative_to(tmp_path).as_posix()
        for path in SecurityAgent._iter_source_files(tmp_path)
    }
    assert yielded == {"app.py"}


def test_builtin_scanner_ignores_skipped_directories(tmp_path: Path):
    """Dangerous code inside node_modules/.git must not be reported as a finding."""
    (tmp_path / "app.py").write_text("eval(user_input)\n", encoding="utf-8")
    vendored = tmp_path / "node_modules" / "evil"
    vendored.mkdir(parents=True)
    (vendored / "evil.py").write_text("eval('x')\n", encoding="utf-8")
    git_hooks = tmp_path / ".git" / "hooks"
    git_hooks.mkdir(parents=True)
    (git_hooks / "hook.py").write_text("os.system('echo hi')\n", encoding="utf-8")

    findings = SecurityAgent()._run_builtin_scanner(str(tmp_path))

    assert len(findings) == 1
    assert findings[0].file == "app.py"
