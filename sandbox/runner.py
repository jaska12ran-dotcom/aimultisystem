from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from sandbox.policies import GeneratedTestSafetyScreen, SandboxPolicy, normalize_command
from sandbox.result_parser import parse_result


class SandboxBlockedError(RuntimeError):
    pass


class SandboxResult:
    def __init__(self, *, success: bool, status: str, execution_output: str, tests_run: int = 0, tests_passed: int = 0, tests_failed: int = 0, duration_ms: float = 0.0):
        self.success = success
        self.status = status
        self.execution_output = execution_output
        self.tests_run = tests_run
        self.tests_passed = tests_passed
        self.tests_failed = tests_failed
        self.duration_ms = duration_ms

    @classmethod
    def from_result_dict(cls, result: Dict[str, Any]) -> "SandboxResult":
        tests = result.get("tests") or {}
        return cls(
            success=result.get("status") == "passed",
            status=result.get("status", "failed"),
            execution_output=result.get("stdout", "") + ("\n" + result.get("stderr", "") if result.get("stderr") else ""),
            tests_run=int(tests.get("total", 0) or 0),
            tests_passed=int(tests.get("passed", 0) or 0),
            tests_failed=int(tests.get("failed", 0) or 0),
            duration_ms=float(result.get("duration", 0.0) * 1000),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "execution_output": self.execution_output,
            "tests_run": self.tests_run,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "duration_ms": self.duration_ms,
        }


class DockerSandboxRunner:
    def __init__(self, docker_bin: str = "docker", policy: Optional[SandboxPolicy] = None):
        self.docker_bin = docker_bin
        self.policy = policy or SandboxPolicy()

    def build_command(self, language: str, command: str | Sequence[str] | None = None) -> List[str]:
        language = (language or "python").lower()
        normalized = normalize_command(language, command)
        if language == "python":
            if normalized[:3] != ["python", "-m", "pytest"]:
                raise SandboxBlockedError("Python sandbox only allows pytest runs.")
        elif language in {"javascript", "typescript"}:
            if normalized[0] not in {"npm", "npx"}:
                raise SandboxBlockedError("JavaScript sandbox only allows npm/npx runs.")
        elif language == "java":
            if normalized[0] not in {"mvn", "./gradlew"}:
                raise SandboxBlockedError("Java sandbox only allows Maven or Gradle runs.")
        else:
            raise SandboxBlockedError(f"Unsupported language '{language}' for sandbox execution.")
        return normalized

    def _docker_run_command(self, workspace_root: Path, command: Sequence[str]) -> List[str]:
        return [
            self.docker_bin,
            "run",
            "--rm",
            "--network", "none",
            "--cpus", str(self.policy.cpu_limit),
            "--memory", str(self.policy.memory_limit),
            "--memory-swap", str(self.policy.memory_limit),
            "--pids-limit", str(self.policy.pids_limit),
            "--cap-drop=ALL",
            "--security-opt", "no-new-privileges:true",
            "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=128m",
            "--tmpfs", "/var/tmp:rw,noexec,nosuid,nodev,size=128m",
            "-v", f"{workspace_root}:/workspace:rw",
            "-w", "/workspace",
            "code-twin-sandbox:latest",
            *command,
        ]

    async def execute_python_test(
        self,
        repo_workspace: str,
        test_code: str,
        test_filename: str = "test_generated.py",
        framework: str = "pytest",
    ) -> SandboxResult:
        workspace_root = Path(tempfile.mkdtemp(prefix="code-twin-generated-"))
        start = time.perf_counter()
        try:
            docker_available = shutil.which("docker") is not None
            if not docker_available:
                if self.policy.host_fallback == "disabled":
                    return SandboxResult(
                        success=False,
                        status="blocked",
                        execution_output=(
                            "Host execution is disabled (SANDBOX_HOST_FALLBACK=disabled) "
                            "and no Docker sandbox is available. Install Docker or set "
                            "SANDBOX_HOST_FALLBACK=screened to allow screened host execution."
                        ),
                    )
                # Screened host fallback: never run untrusted generated tests on
                # the host when they contain dangerous constructs.
                safety = GeneratedTestSafetyScreen.screen(test_code)
                if not safety["safe"]:
                    return SandboxResult(
                        success=False,
                        status="blocked",
                        execution_output=(
                            "Host execution blocked: no Docker sandbox is available and the "
                            "generated tests failed the safety screen: "
                            + "; ".join(safety["blocked_reasons"])
                        ),
                    )
            repository_copy = workspace_root / "repo"
            if Path(repo_workspace).exists():
                shutil.copytree(repo_workspace, repository_copy, dirs_exist_ok=True)
            else:
                repository_copy.mkdir(parents=True, exist_ok=True)
            target_file = repository_copy / test_filename
            target_file.write_text(test_code, encoding="utf-8")
            if docker_available:
                result_dict = self.execute(
                    repo_path=repository_copy,
                    language="python",
                    command=["python", "-m", "pytest", test_filename, "-q"],
                    timeout=self.policy.timeout_seconds,
                )
            else:
                env = os.environ.copy()
                env["PYTHONDONTWRITEBYTECODE"] = "1"
                env["PYTHONPATH"] = str(repository_copy)
                completed = subprocess.run(
                    [sys.executable, "-m", "pytest", str(target_file), "-q", "--maxfail=1"],
                    cwd=str(repository_copy),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self.policy.timeout_seconds,
                    check=False,
                )
                result_dict = parse_result(
                    exit_code=completed.returncode,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                    duration=time.perf_counter() - start,
                    language="python",
                )
            return SandboxResult.from_result_dict(result_dict)
        finally:
            shutil.rmtree(workspace_root, ignore_errors=True)

    def execute(
        self,
        repo_path: str | os.PathLike[str],
        language: str,
        command: str | Sequence[str] | None = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        start = time.perf_counter()
        repo_path = Path(repo_path).resolve()
        if not repo_path.exists():
            return {
                "status": "blocked",
                "exit_code": 126,
                "stdout": "",
                "stderr": f"Repository path '{repo_path}' does not exist.",
                "duration": round(time.perf_counter() - start, 3),
                "coverage": {},
                "tests": {},
            }

        try:
            approved_command = self.build_command(language, command)
        except (SandboxBlockedError, ValueError) as exc:
            return {
                "status": "blocked",
                "exit_code": 126,
                "stdout": "",
                "stderr": str(exc),
                "duration": round(time.perf_counter() - start, 3),
                "coverage": {},
                "tests": {},
            }

        workspace_root = Path(tempfile.mkdtemp(prefix="code-twin-sandbox-"))
        try:
            sandbox_workspace = workspace_root / "workspace"
            shutil.copytree(repo_path, sandbox_workspace, dirs_exist_ok=True)
            try:
                docker_cmd = self._docker_run_command(sandbox_workspace, approved_command)
                completed = subprocess.run(
                    docker_cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout or self.policy.timeout_seconds,
                    check=False,
                )
                duration = time.perf_counter() - start
                parsed = parse_result(
                    exit_code=completed.returncode,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                    duration=duration,
                    language=language,
                )
                return parsed
            except subprocess.TimeoutExpired:
                return {
                    "status": "timeout",
                    "exit_code": 124,
                    "stdout": "",
                    "stderr": f"Sandbox execution timed out after {timeout or self.policy.timeout_seconds} seconds.",
                    "duration": round(time.perf_counter() - start, 3),
                    "coverage": {},
                    "tests": {},
                }
            except FileNotFoundError:
                return {
                    "status": "blocked",
                    "exit_code": 126,
                    "stdout": "",
                    "stderr": "Docker is required for sandbox execution but is not installed or is not on PATH.",
                    "duration": round(time.perf_counter() - start, 3),
                    "coverage": {},
                    "tests": {},
                }
        finally:
            shutil.rmtree(workspace_root, ignore_errors=True)


sandbox_runner = DockerSandboxRunner()
