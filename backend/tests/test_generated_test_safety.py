"""Tests for the generated-test safety screen and host-fallback enforcement.

Generated tests are untrusted model output. When Docker is unavailable the
runner falls back to executing pytest on the host; the safety screen ensures
dangerous constructs are refused at that boundary.
"""
from pathlib import Path

import pytest

from sandbox.policies import GeneratedTestSafetyScreen, SandboxPolicy
from sandbox.runner import DockerSandboxRunner

SAFE_SUITE = (
    "import importlib\n"
    "module = importlib.import_module('service')\n"
    "\n"
    "def test_health_check_smoke():\n"
    "    assert hasattr(module, 'health_check')\n"
)

DANGEROUS_SUITE = (
    "import subprocess\n"
    "\n"
    "def test_escape():\n"
    "    subprocess.run(['echo', 'pwned'])\n"
)


def test_screen_accepts_deterministic_generated_suite():
    result = GeneratedTestSafetyScreen.screen(SAFE_SUITE)
    assert result["safe"] is True
    assert result["blocked_reasons"] == []


@pytest.mark.parametrize(
    "code,expected_fragment",
    [
        ("import os\nos.system('echo hi')\n", "os.system"),
        ("import subprocess\nsubprocess.run(['ls'])\n", "subprocess"),
        ("import requests\nrequests.get('https://example.com')\n", "requests"),
        ("import shutil\nshutil.rmtree('/tmp/x')\n", "shutil.rmtree"),
        ("while True:\n    pass\n", "unbounded loop"),
        ("eval('1 + 1')\n", "dynamic code"),
        ("import ctypes\n", "ctypes"),
    ],
)
def test_screen_blocks_dangerous_constructs(code: str, expected_fragment: str):
    result = GeneratedTestSafetyScreen.screen(code)
    assert result["safe"] is False
    assert any(expected_fragment in reason for reason in result["blocked_reasons"])


def test_screen_warns_without_blocking():
    result = GeneratedTestSafetyScreen.screen("import time\n\ndef test_slow():\n    time.sleep(0.01)\n")
    assert result["safe"] is True
    assert result["warnings"]


@pytest.mark.asyncio
async def test_host_fallback_blocks_dangerous_generated_tests(monkeypatch, tmp_path: Path):
    runner = DockerSandboxRunner()
    # Force the no-Docker host fallback path deterministically.
    monkeypatch.setattr("sandbox.runner.shutil.which", lambda name: None)

    result = await runner.execute_python_test(
        repo_workspace=str(tmp_path),
        test_code=DANGEROUS_SUITE,
        test_filename="test_generated.py",
    )

    assert result.status == "blocked"
    assert "safety screen" in result.execution_output
    assert result.tests_run == 0
    assert result.success is False


@pytest.mark.asyncio
async def test_host_fallback_still_runs_safe_generated_tests(monkeypatch, tmp_path: Path):
    runner = DockerSandboxRunner()
    monkeypatch.setattr("sandbox.runner.shutil.which", lambda name: None)

    result = await runner.execute_python_test(
        repo_workspace=str(tmp_path),
        test_code="def test_ok():\n    assert 1 + 1 == 2\n",
        test_filename="test_generated.py",
    )

    assert result.status != "blocked"
    assert result.status in {"passed", "failed"}


@pytest.mark.asyncio
async def test_host_fallback_disabled_fails_closed(monkeypatch, tmp_path: Path):
    runner = DockerSandboxRunner(policy=SandboxPolicy(host_fallback="disabled"))
    monkeypatch.setattr("sandbox.runner.shutil.which", lambda name: None)

    result = await runner.execute_python_test(
        repo_workspace=str(tmp_path),
        # Even safe-looking code is refused when host execution is disabled.
        test_code="def test_ok():\n    assert True\n",
        test_filename="test_generated.py",
    )

    assert result.status == "blocked"
    assert "disabled" in result.execution_output.lower()
    assert result.tests_run == 0


def test_host_fallback_env_controls_policy(monkeypatch):
    monkeypatch.setenv("SANDBOX_HOST_FALLBACK", "screened")
    assert SandboxPolicy().host_fallback == "screened"

    monkeypatch.setenv("SANDBOX_HOST_FALLBACK", "disabled")
    assert SandboxPolicy().host_fallback == "disabled"

    # Unrecognized values fail closed.
    monkeypatch.setenv("SANDBOX_HOST_FALLBACK", "yes-please")
    assert SandboxPolicy().host_fallback == "disabled"
