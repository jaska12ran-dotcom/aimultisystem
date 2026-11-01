from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence


SAFE_TOKEN_RE = r"^[A-Za-z0-9_./:@=+\-\\,\[\]\{\}]*$"


def _default_host_fallback() -> str:
    value = os.getenv("SANDBOX_HOST_FALLBACK", "screened").strip().lower()
    # Misconfiguration fails closed.
    return value if value in {"screened", "disabled"} else "disabled"


@dataclass(frozen=True)
class SandboxPolicy:
    cpu_limit: str = "1.0"
    memory_limit: str = "512m"
    timeout_seconds: int = 60
    pids_limit: int = 256
    network_disabled: bool = True
    read_only_root: bool = True
    allow_root: bool = False
    max_output_bytes: int = 200000
    allowed_languages: Sequence[str] = field(
        default_factory=lambda: ("python", "javascript", "typescript", "java")
    )
    # What to do when Docker is unavailable:
    #   "screened" — run only generated tests that pass the static safety screen
    #   "disabled" — refuse host execution entirely (fail closed)
    host_fallback: str = field(default_factory=_default_host_fallback)

    def docker_args(self) -> List[str]:
        args = [
            "--rm",
            "--network", "none" if self.network_disabled else "bridge",
            "--cpus", str(self.cpu_limit),
            "--memory", str(self.memory_limit),
            "--memory-swap", str(self.memory_limit),
            "--pids-limit", str(self.pids_limit),
            "--cap-drop=ALL",
            "--security-opt", "no-new-privileges:true",
            "--read-only" if self.read_only_root else "--read-only=false",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=128m",
            "--tmpfs", "/var/tmp:rw,noexec,nosuid,nodev,size=128m",
        ]
        if not self.allow_root:
            args.extend(["--user", "1000:1000"])
        return args


APPROVED_TEST_COMMANDS: Dict[str, List[str]] = {
    "python": ["python", "-m", "pytest", "-q", "--maxfail=1", "--disable-warnings"],
    "javascript": ["npm", "test", "--", "--runInBand", "--ci"],
    "typescript": ["npx", "vitest", "run"],
    "java": ["mvn", "-q", "test"],
}


class GeneratedTestSafetyScreen:
    """Static safety screen for AI-generated test code.

    Generated tests are untrusted model output. When the Docker sandbox is
    available the container confines their side effects, but when execution
    falls back to the host there is no isolation — so the runner refuses to
    execute host-fallback code that contains dangerous constructs.

    The screen is deliberately simple and deterministic: a fixed set of
    regular expressions over the test source. It is a safety net, not a
    proof; it never replaces sandbox isolation when Docker is available.
    """

    BLOCKED: List[tuple[re.Pattern[str], str]] = [
        (re.compile(r"\bos\.system\s*\("), "os.system call"),
        (re.compile(r"\bsubprocess\b"), "subprocess usage"),
        (re.compile(r"\bsocket\b"), "raw socket usage"),
        (re.compile(r"\brequests\.(get|post|put|patch|delete|request)\s*\("), "network call via requests"),
        (re.compile(r"\burllib\.(request|urlopen)\b"), "network call via urllib"),
        (re.compile(r"\bhttpx\.(get|post|put|patch|delete|request|Client)\b"), "network call via httpx"),
        (re.compile(r"\bshutil\.rmtree\s*\("), "recursive deletion via shutil.rmtree"),
        (re.compile(r"\bos\.(remove|unlink|rmdir)\s*\("), "file deletion"),
        (re.compile(r"\bsys\.exit\s*\("), "process exit"),
        (re.compile(r"\b(eval|exec)\s*\("), "dynamic code execution"),
        (re.compile(r"\b__import__\s*\("), "dynamic import via __import__"),
        (re.compile(r"while\s+True\s*:"), "unbounded loop"),
        (re.compile(r"\bctypes\b"), "ctypes low-level access"),
        (re.compile(r"\bpip\s+(install|uninstall)\b"), "package installation"),
    ]

    WARNED: List[tuple[re.Pattern[str], str]] = [
        (re.compile(r"\btime\.sleep\s*\("), "uses time.sleep; timing-sensitive test may be flaky"),
        (re.compile(r"\bos\.environ\b[^\n]*="), "mutates process environment"),
        (re.compile(r"\brandom\.(random|randint|choice|shuffle)\s*\("), "uses unseeded randomness"),
    ]

    @classmethod
    def screen(cls, test_code: str) -> Dict[str, Any]:
        code = test_code or ""
        blocked = [reason for pattern, reason in cls.BLOCKED if pattern.search(code)]
        warned = [reason for pattern, reason in cls.WARNED if pattern.search(code)]
        return {
            "safe": not blocked,
            "blocked_reasons": blocked,
            "warnings": warned,
        }


def validate_command(language: str, command: Sequence[str]) -> None:
    allowed = APPROVED_TEST_COMMANDS.get(language.lower())
    if allowed is None:
        raise ValueError(f"Unsupported sandbox language: {language}")

    sanitized = list(command)
    if not sanitized:
        raise ValueError("Test command cannot be empty.")

    if any(token is None or token == "" for token in sanitized):
        raise ValueError("Command contains empty tokens.")

    blocked_tokens = [";", "&&", "||", "|", "<", ">", "$(", "`", "\\n"]
    for token in sanitized:
        if any(marker in token for marker in blocked_tokens):
            raise ValueError(f"Unsafe command token '{token}' is not allowed in the sandbox.")
        if token.startswith("-"):
            continue
        if token.startswith("/bin/") or token.startswith("/usr/bin/"):
            raise ValueError(f"Direct host command from path '{token}' is not allowed.")
        if token.startswith("sudo") or token.startswith("ssh"):
            raise ValueError(f"Command '{token}' is not approved for execution in the sandbox.")
        if token.startswith("docker") or token.startswith("kubectl"):
            raise ValueError(f"Nested container orchestration is not allowed in the sandbox: '{token}'.")
        if token.startswith("http://") or token.startswith("https://"):
            raise ValueError("Network fetches are not allowed from repository test commands.")

    if sanitized[0] not in {"python", "npm", "npx", "mvn", "pytest", "vitest", "gradlew"}:
        raise ValueError(f"Command '{sanitized[0]}' is not on the approved execution allowlist.")

    if language.lower() in {"python"} and sanitized[:3] != ["python", "-m", "pytest"]:
        raise ValueError("Python executions are restricted to pytest in the sandbox.")
    if language.lower() in {"javascript", "typescript"} and sanitized[0] not in {"npm", "npx"}:
        raise ValueError("JavaScript/TypeScript executions are restricted to npm or npx in the sandbox.")
    if language.lower() == "java" and sanitized[0] not in {"mvn", "./gradlew"}:
        raise ValueError("Java executions are restricted to Maven or Gradle in the sandbox.")


def normalize_command(language: str, command: str | Sequence[str] | None) -> List[str]:
    if command is None:
        return list(APPROVED_TEST_COMMANDS.get(language.lower(), []))

    if isinstance(command, str):
        tokens = shlex.split(command)
    else:
        tokens = list(command)

    validate_command(language, tokens)
    return tokens
