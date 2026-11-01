import asyncio
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pydantic import BaseModel, Field


SEVERITY_RANK = {
    "critical": 5,
    "high": 4,
    "medium": 3,
    "low": 2,
    "informational": 1,
    "unknown": 0,
}


SOURCE_FILE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb",
    ".php", ".rs", ".c", ".cpp", ".cs", ".swift", ".kt", ".sh",
    ".yml", ".yaml", ".json", ".env", ".toml", ".ini", ".cfg", ".xml",
}


# (regex, severity, category, description, remediation)
BUILTIN_SECURITY_PATTERNS: List[Tuple[re.Pattern, str, str, str, str]] = [
    (
        re.compile(r"\beval\s*\("),
        "high", "code_injection",
        "eval() executes arbitrary code — code injection risk.",
        "Avoid eval(); use ast.literal_eval() or explicit parsing.",
    ),
    (
        re.compile(r"\bexec\s*\("),
        "high", "code_injection",
        "exec() executes arbitrary code — code injection risk.",
        "Avoid exec(); refactor to explicit function calls.",
    ),
    (
        re.compile(r"subprocess\.(run|Popen|call|check_output|check_call)\s*\([^)]*shell\s*=\s*True"),
        "high", "command_injection",
        "subprocess invoked with shell=True — command injection risk.",
        "Pass shell=False and a argument list instead of a shell string.",
    ),
    (
        re.compile(r"\bos\.system\s*\("),
        "high", "command_injection",
        "os.system() executes shell commands — command injection risk.",
        "Use subprocess.run([...], shell=False) with validated arguments.",
    ),
    (
        re.compile(r"pickle\.loads?\s*\("),
        "high", "insecure_deserialization",
        "pickle deserialization can execute arbitrary code.",
        "Use JSON or a safe serialization format for untrusted data.",
    ),
    (
        re.compile(r"yaml\.load\s*\((?![^)]*Loader\s*=)"),
        "high", "insecure_deserialization",
        "yaml.load() without a safe Loader can execute arbitrary code.",
        "Use yaml.safe_load() or pass Loader=yaml.SafeLoader.",
    ),
    (
        re.compile(r"hashlib\.(md5|sha1)\s*\("),
        "medium", "weak_cryptography",
        "MD5/SHA-1 are cryptographically broken.",
        "Use hashlib.sha256() or stronger for security-relevant hashing.",
    ),
    (
        re.compile(r"random\.(random|randint|choice|choices|shuffle)\s*\("),
        "low", "weak_randomness",
        "random module is not cryptographically secure.",
        "Use the secrets module for tokens, passwords, or keys.",
    ),
    (
        re.compile(r"verify\s*=\s*False"),
        "high", "tls_verification",
        "TLS certificate verification disabled.",
        "Enable certificate verification; use a custom CA bundle if needed.",
    ),
    (
        re.compile(r"(AWS_SECRET_ACCESS_KEY|AWS_ACCESS_KEY_ID|PRIVATE_KEY|SECRET_KEY|API_KEY|PASSWORD)\s*=\s*[\"'][^\"']{8,}[\"']"),
        "critical", "hardcoded_secret",
        "Hardcoded credential or API key detected.",
        "Move secrets to environment variables or a secret manager and rotate.",
    ),
    (
        re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
        "critical", "hardcoded_secret",
        "Private key material embedded in source.",
        "Remove the key, move it to a secret store, and rotate it.",
    ),
    (
        re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
        "critical", "hardcoded_secret",
        "AWS access key ID detected in source.",
        "Revoke and rotate the key; load credentials from the environment.",
    ),
    (
        re.compile(r"password\s*=\s*[\"'][^\"']+[\"']", re.IGNORECASE),
        "high", "hardcoded_secret",
        "Hardcoded password assignment detected.",
        "Load passwords from environment variables or a secret manager.",
    ),
    (
        re.compile(r"innerHTML\s*=|dangerouslySetInnerHTML|v-html"),
        "high", "xss",
        "Unsanitized HTML injection vector — cross-site scripting risk.",
        "Sanitize or escape user-controlled HTML before rendering.",
    ),
    (
        re.compile(r"document\.write\s*\("),
        "medium", "xss",
        "document.write() can enable DOM-based XSS.",
        "Use textContent / safe DOM APIs instead of document.write().",
    ),
    (
        re.compile(r"SELECT\s+.+\s+FROM\s+.+\s+WHERE\s+.*(\+|\%\s*(s|d)|f['\"])", re.IGNORECASE),
        "high", "sql_injection",
        "Possible SQL string concatenation — SQL injection risk.",
        "Use parameterized queries or an ORM instead of string building.",
    ),
    (
        re.compile(r"cursor\.execute\s*\(\s*f[\"']|cursor\.execute\s*\(\s*[\"'][^\"']*%"),
        "high", "sql_injection",
        "SQL query built with an f-string or % formatting.",
        "Pass parameters as a tuple to cursor.execute() to avoid injection.",
    ),
    (
        re.compile(r"requests\.(get|post|put|delete|patch|head)\s*\([^)]*timeout\s*=\s*None"),
        "low", "availability",
        "HTTP request without a timeout can hang indefinitely.",
        "Set an explicit timeout on outbound HTTP calls.",
    ),
    (
        re.compile(r"assert\s+.*(?:password|token|secret|api_key)", re.IGNORECASE),
        "medium", "security_misuse",
        "Secret compared or asserted in code — assertions strip under -O.",
        "Use an explicit equality check that cannot be optimized away.",
    ),
    (
        re.compile(r"random\.randbytes|tempfile\.mktemp\s*\("),
        "medium", "insecure_temporary_file",
        "mktemp() is racy and insecure.",
        "Use tempfile.mkstemp() or TemporaryDirectory instead.",
    ),
]


def _normalize_severity(value: Optional[str]) -> str:
    if not value:
        return "unknown"
    normalized = str(value).strip().lower()
    mapping = {
        "error": "high",
        "fatal": "critical",
        "warn": "medium",
        "warning": "medium",
        "info": "informational",
        "low": "low",
        "medium": "medium",
        "high": "high",
        "critical": "critical",
    }
    return mapping.get(normalized, normalized if normalized in SEVERITY_RANK else "unknown")


def _normalize_confidence(value: Optional[str]) -> str:
    if not value:
        return "medium"
    normalized = str(value).strip().lower()
    mapping = {
        "high": "high",
        "medium": "medium",
        "low": "low",
        "error": "high",
        "warning": "medium",
        "info": "low",
    }
    return mapping.get(normalized, "medium")


class SecurityFinding(BaseModel):
    severity: str = "medium"
    category: str = "security"
    file: str = ""
    line: Optional[int] = None
    description: str = ""
    evidence: str = ""
    remediation: str = "Review and apply project-specific hardening controls."
    tool: str = "unknown"
    confidence: str = "medium"


class SecurityDashboard(BaseModel):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    informational: int = 0
    total_findings: int = 0
    summary: str = "No detected issue from the configured security checks."


class SecurityAnalysisResponse(BaseModel):
    repository_id: str
    repository_path: str
    summary: str = "No detected issue from the configured security checks."
    findings: List[SecurityFinding] = Field(default_factory=list)
    dashboard: SecurityDashboard = Field(default_factory=SecurityDashboard)
    tools_considered: List[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SecurityAgent:
    """Static security analysis agent for repository scanning."""

    SUPPORTED_TOOLS = ["semgrep", "gitleaks", "bandit", "trivy", "pip-audit"]

    def __init__(self):
        self._tool_map = {
            "semgrep": self._run_semgrep,
            "gitleaks": self._run_gitleaks,
            "bandit": self._run_bandit,
            "trivy": self._run_trivy,
            "pip-audit": self._run_pip_audit,
        }

    async def analyze_repository(self, repo_id: str, repo_path: str) -> SecurityAnalysisResponse:
        findings: List[SecurityFinding] = []
        tool_results: List[str] = []
        for tool_name in self.SUPPORTED_TOOLS:
            raw = await asyncio.to_thread(self._run_tool_impl, tool_name, repo_path)
            if raw:
                findings.extend(self._normalize_tool_results(tool_name, raw))
                tool_results.append(tool_name)

        # Built-in scanner always runs so analysis is never empty when external
        # tools are unavailable. External-tool findings dedupe against it.
        builtin = await asyncio.to_thread(self._run_builtin_scanner, repo_path)
        if builtin:
            findings.extend(builtin)
            tool_results.append("builtin")

        findings = self.merge_findings(findings)
        dashboard = self.build_dashboard(findings)
        summary = (
            "No detected issue from the configured security checks."
            if not findings
            else f"Detected {len(findings)} security finding(s) requiring review."
        )
        response = SecurityAnalysisResponse(
            repository_id=repo_id,
            repository_path=repo_path,
            summary=summary,
            findings=findings,
            dashboard=dashboard,
            tools_considered=tool_results,
        )
        response.dashboard.summary = summary
        return response

    def _run_tool_impl(self, tool_name: str, repo_path: str) -> Any:
        command_runner = self._tool_map.get(tool_name)
        if not command_runner:
            return []
        return command_runner(repo_path)

    def _run_semgrep(self, repo_path: str) -> List[Dict[str, Any]]:
        executable = shutil.which("semgrep")
        if not executable:
            return []
        cmd = [executable, "scan", "--json", "--quiet", "--config", "auto", repo_path]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if not proc.stdout.strip():
                return []
            data = json.loads(proc.stdout)
            return data.get("results", [])
        except (json.JSONDecodeError, ValueError, OSError):
            return []

    def _run_gitleaks(self, repo_path: str) -> List[Dict[str, Any]]:
        executable = shutil.which("gitleaks")
        if not executable:
            return []
        cmd = [executable, "detect", "--source", repo_path, "--report-format", "json", "--no-banner", "--exit-code", "0"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if not proc.stdout.strip():
                return []
            return json.loads(proc.stdout)
        except (json.JSONDecodeError, ValueError, OSError):
            return []

    def _run_bandit(self, repo_path: str) -> Dict[str, Any]:
        executable = shutil.which("bandit")
        if not executable:
            return {}
        cmd = [executable, "-r", repo_path, "-f", "json"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if not proc.stdout.strip():
                return {}
            return json.loads(proc.stdout)
        except (json.JSONDecodeError, ValueError, OSError):
            return {}

    def _run_trivy(self, repo_path: str) -> Dict[str, Any]:
        executable = shutil.which("trivy")
        if not executable:
            return {}
        cmd = [executable, "fs", "--security-checks", "vuln,config", "--format", "json", repo_path]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if not proc.stdout.strip():
                return {}
            return json.loads(proc.stdout)
        except (json.JSONDecodeError, ValueError, OSError):
            return {}

    def _run_pip_audit(self, repo_path: str) -> Dict[str, Any]:
        executable = shutil.which("pip-audit")
        if not executable:
            return {}
        requirements = []
        candidates = ["requirements.txt", "pyproject.toml", "setup.py", "Pipfile.lock"]
        for candidate in candidates:
            if os.path.exists(os.path.join(repo_path, candidate)):
                requirements.append(os.path.join(repo_path, candidate))
        if not requirements:
            return {}
        cmd = [executable, "--format", "json"]
        for req_path in requirements:
            cmd.extend(["-r", req_path])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if not proc.stdout.strip():
                return {}
            return json.loads(proc.stdout)
        except (json.JSONDecodeError, ValueError, OSError):
            return {}

    def _run_builtin_scanner(self, repo_path: str) -> List[SecurityFinding]:
        """Dependency-free static scanner using regex + AST checks.

        Guarantees a baseline security signal even when semgrep / bandit /
        gitleaks / trivy / pip-audit are not installed.

        Files are read once and every pattern is applied to each line, so cost
        is O(files) rather than O(patterns × files).
        """
        findings: List[SecurityFinding] = []
        scan_root = Path(repo_path)
        if not scan_root.is_dir():
            return findings

        for file_path in self._iter_source_files(scan_root):
            try:
                rel = str(file_path.relative_to(scan_root))
                lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for line_no, line in enumerate(lines, start=1):
                for pattern, severity, category, description, remediation in BUILTIN_SECURITY_PATTERNS:
                    if pattern.search(line):
                        findings.append(SecurityFinding(
                            severity=severity,
                            category=category,
                            file=rel,
                            line=line_no,
                            description=description,
                            evidence=line.strip()[:300],
                            remediation=remediation,
                            tool="builtin",
                            confidence="medium",
                        ))
        return findings

    @staticmethod
    def _iter_source_files(root: Path) -> Iterable[Path]:
        """Yield scannable source files, pruning skipped directories up front.

        ``os.walk`` allows pruning ``dirnames`` in place, so heavy directories
        (node_modules, .git, virtualenvs, build output) are never descended
        into. A plain ``rglob`` + post-filter would still traverse them.
        """
        skip_dirs = {
            ".git", "node_modules", ".venv", "venv", "__pycache__",
            "dist", "build", ".next", ".pytest_cache", "site-packages",
            ".mypy_cache", ".ruff_cache", "coverage", ".tox",
        }
        for current_dir, dir_names, file_names in os.walk(root):
            dir_names[:] = [name for name in dir_names if name not in skip_dirs]
            for file_name in file_names:
                path = Path(current_dir) / file_name
                if path.suffix.lower() not in SOURCE_FILE_EXTENSIONS:
                    continue
                try:
                    if path.stat().st_size > 1 * 1024 * 1024:
                        continue
                except OSError:
                    continue
                yield path

    def _normalize_tool_results(self, tool_name: str, raw: Any) -> List[SecurityFinding]:
        if tool_name == "semgrep":
            return self._normalize_semgrep(raw)
        if tool_name == "bandit":
            return self._normalize_bandit(raw)
        if tool_name == "gitleaks":
            return self._normalize_gitleaks(raw)
        if tool_name == "trivy":
            return self._normalize_trivy(raw)
        if tool_name == "pip-audit":
            return self._normalize_pip_audit(raw)
        return []

    def _normalize_semgrep(self, items: Iterable[Dict[str, Any]]) -> List[SecurityFinding]:
        findings: List[SecurityFinding] = []
        for item in items or []:
            extra = item.get("extra", {}) or {}
            metadata = extra.get("metadata", {}) or {}
            finding = SecurityFinding(
                severity=_normalize_severity(extra.get("severity") or item.get("severity")),
                category=str(metadata.get("category") or extra.get("category") or "security"),
                file=str(item.get("path") or ""),
                line=item.get("start", {}).get("line") if isinstance(item.get("start"), dict) else None,
                description=str(extra.get("message") or item.get("message") or "Security finding"),
                evidence=json.dumps({
                    "check_id": item.get("check_id"),
                    "message": extra.get("message"),
                    "metadata": metadata,
                }, sort_keys=True),
                remediation=str(metadata.get("remediation") or "Review and remediate this security issue."),
                tool="semgrep",
                confidence=_normalize_confidence(extra.get("confidence") or metadata.get("confidence")),
            )
            findings.append(finding)
        return findings

    def _normalize_bandit(self, payload: Dict[str, Any]) -> List[SecurityFinding]:
        findings: List[SecurityFinding] = []
        for issue in (payload or {}).get("results", []) or []:
            line = issue.get("line_number")
            finding = SecurityFinding(
                severity=_normalize_severity(issue.get("issue_severity")),
                category=str(issue.get("issue_category") or issue.get("issue_type") or "security"),
                file=str(issue.get("filename") or ""),
                line=line,
                description=str(issue.get("issue_text") or "Bandit security finding"),
                evidence=json.dumps({
                    "issue_confidence": issue.get("issue_confidence"),
                    "test_id": issue.get("test_id"),
                    "severity": issue.get("issue_severity"),
                }, sort_keys=True),
                remediation=str(issue.get("issue_text") or "Review the flagged code path and harden it."),
                tool="bandit",
                confidence=_normalize_confidence(issue.get("issue_confidence")),
            )
            findings.append(finding)
        return findings

    def _normalize_gitleaks(self, payload: List[Dict[str, Any]]) -> List[SecurityFinding]:
        findings: List[SecurityFinding] = []
        for item in payload or []:
            normalized_severity = _normalize_severity(item.get("Severity") or item.get("severity"))
            finding = SecurityFinding(
                severity=normalized_severity,
                category=str(item.get("Description") or "secret"),
                file=str(item.get("File") or item.get("file") or ""),
                line=item.get("StartLine") or item.get("start_line") or item.get("line"),
                description=str(item.get("Description") or item.get("description") or "Potential secret disclosure"),
                evidence=json.dumps({
                    "fingerprint": item.get("Fingerprint"),
                    "commit": item.get("Commit"),
                    "description": item.get("Description"),
                }, sort_keys=True),
                remediation="Remove the secret, revoke credentials, and rotate any exposed keys or tokens.",
                tool="gitleaks",
                confidence="high" if normalized_severity in {"high", "critical"} else "medium",
            )
            findings.append(finding)
        return findings

    def _normalize_trivy(self, payload: Dict[str, Any]) -> List[SecurityFinding]:
        findings: List[SecurityFinding] = []
        for result in (payload or {}).get("Results", []) or []:
            target = result.get("Target", "")
            for vuln in result.get("Vulnerabilities", []) or []:
                finding = SecurityFinding(
                    severity=_normalize_severity(vuln.get("Severity") or vuln.get("severity")),
                    category=str(vuln.get("Class") or vuln.get("category") or "dependency"),
                    file=str(target),
                    line=None,
                    description=str(vuln.get("Title") or vuln.get("Description") or "Dependency or configuration vulnerability"),
                    evidence=json.dumps({
                        "pkg_name": vuln.get("PkgName"),
                        "installed_version": vuln.get("InstalledVersion"),
                        "target": target,
                    }, sort_keys=True),
                    remediation=str(vuln.get("FixedVersion") or "Upgrade the affected package or fix the vulnerable configuration."),
                    tool="trivy",
                    confidence="medium",
                )
                findings.append(finding)
            for misconfig in result.get("Misconfigurations", []) or []:
                line = None
                metadata = misconfig.get("CauseMetadata") if isinstance(misconfig.get("CauseMetadata"), dict) else {}
                if metadata:
                    line = metadata.get("StartLine")
                finding = SecurityFinding(
                    severity=_normalize_severity(misconfig.get("Severity") or misconfig.get("severity")),
                    category=str(misconfig.get("Category") or "configuration"),
                    file=str(target),
                    line=line,
                    description=str(misconfig.get("Description") or "Security misconfiguration"),
                    evidence=json.dumps({
                        "issue": misconfig.get("Title"),
                        "target": target,
                        "cause": metadata,
                    }, sort_keys=True),
                    remediation="Apply the Trivy remediation guidance for the flagged misconfiguration.",
                    tool="trivy",
                    confidence="medium",
                )
                findings.append(finding)
        return findings

    def _normalize_pip_audit(self, payload: Dict[str, Any]) -> List[SecurityFinding]:
        findings: List[SecurityFinding] = []
        for issue in (payload or {}).get("vulns", []) or []:
            package = issue.get("name") or issue.get("package") or "unknown-package"
            severity = _normalize_severity(issue.get("severity"))
            description = issue.get("description") or issue.get("summary") or f"Known vulnerability in {package}"
            finding = SecurityFinding(
                severity=severity,
                category="dependency",
                file="requirements.txt",
                line=None,
                description=description,
                evidence=json.dumps({
                    "package": package,
                    "version": issue.get("version"),
                    "aliases": issue.get("aliases"),
                }, sort_keys=True),
                remediation="Upgrade the vulnerable package to a fixed version or replace it with a secure alternative.",
                tool="pip-audit",
                confidence="medium",
            )
            findings.append(finding)
        return findings

    def merge_findings(self, findings: List[SecurityFinding]) -> List[SecurityFinding]:
        grouped: Dict[tuple, SecurityFinding] = {}
        for finding in findings:
            key = (
                str(finding.file or "").strip(),
                int(finding.line) if finding.line is not None else -1,
                str(finding.category or "").strip(),
                str(finding.description or "").strip(),
            )
            current = grouped.get(key)
            if current is None:
                grouped[key] = finding
                continue
            current.severity = self._max_severity(current.severity, finding.severity)
            current.confidence = self._max_confidence(current.confidence, finding.confidence)
            current.tool = self._merge_tools(current.tool, finding.tool)
            current.evidence = self._merge_evidence(current.evidence, finding.evidence)
            if not current.remediation and finding.remediation:
                current.remediation = finding.remediation
            if not current.category and finding.category:
                current.category = finding.category

        merged = sorted(
            grouped.values(),
            key=lambda item: (
                -SEVERITY_RANK.get(item.severity, 0),
                item.file or "",
                item.line if item.line is not None else -1,
            ),
        )
        return merged

    @staticmethod
    def _max_severity(left: str, right: str) -> str:
        return left if SEVERITY_RANK.get(left, 0) >= SEVERITY_RANK.get(right, 0) else right

    @staticmethod
    def _max_confidence(left: str, right: str) -> str:
        order = {"low": 1, "medium": 2, "high": 3}
        return left if order.get(left, 0) >= order.get(right, 0) else right

    @staticmethod
    def _merge_tools(left: str, right: str) -> str:
        merged = {item.strip() for item in (left.split(",") if left else []) + (right.split(",") if right else [])}
        if not merged:
            return "unknown"
        return ", ".join(sorted(merged))

    @staticmethod
    def _merge_evidence(left: str, right: str) -> str:
        left_value = left.strip() if left else ""
        right_value = right.strip() if right else ""
        evidence_parts = []
        for value in [left_value, right_value]:
            if value and value not in evidence_parts:
                evidence_parts.append(value)
        return "; ".join(evidence_parts)

    def build_dashboard(self, findings: List[SecurityFinding]) -> SecurityDashboard:
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "informational": 0}
        for finding in findings:
            level = _normalize_severity(finding.severity)
            if level in counts:
                counts[level] += 1
        summary = "No detected issue from the configured security checks." if not findings else (
            f"Detected {len(findings)} security finding(s) requiring review: "
            f"{counts['critical']} critical, {counts['high']} high, {counts['medium']} medium, "
            f"{counts['low']} low, {counts['informational']} informational."
        )
        return SecurityDashboard(
            critical=counts["critical"],
            high=counts["high"],
            medium=counts["medium"],
            low=counts["low"],
            informational=counts["informational"],
            total_findings=len(findings),
            summary=summary,
        )
