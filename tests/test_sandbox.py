from pathlib import Path

import pytest

from sandbox.runner import DockerSandboxRunner


def test_rejects_injected_shell_command(tmp_path: Path):
    runner = DockerSandboxRunner()
    with pytest.raises(Exception):
        runner.build_command("python", "python -m pytest -q; cat /etc/passwd")

    result = runner.execute(tmp_path, "python", "python -m pytest -q; cat /etc/passwd")
    assert result["status"] == "blocked"
    assert result["exit_code"] == 126
    assert "not allowed" in result["stderr"].lower()


def test_valid_python_command_is_approved():
    runner = DockerSandboxRunner()
    command = runner.build_command("python", "python -m pytest -q --maxfail=1")
    assert command[:3] == ["python", "-m", "pytest"]


def test_allowlist_supports_javascript_and_java():
    runner = DockerSandboxRunner()
    assert runner.build_command("javascript", ["npm", "test", "--", "--runInBand"])[0] == "npm"
    assert runner.build_command("java", ["mvn", "-q", "test"])[0] == "mvn"


def test_execute_returns_parsed_result_for_valid_command(monkeypatch, tmp_path: Path):
    runner = DockerSandboxRunner()

    def fake_run(args, capture_output, text, timeout, check):
        class Completed:
            returncode = 0
            stdout = "1 passed in 0.02s\n"
            stderr = ""

        return Completed()

    monkeypatch.setattr("sandbox.runner.subprocess.run", fake_run)
    result = runner.execute(tmp_path, "python", "python -m pytest -q")

    assert result["status"] == "passed"
    assert result["exit_code"] == 0
    assert result["tests"]["passed"] == 1
    assert result["coverage"] == {}
