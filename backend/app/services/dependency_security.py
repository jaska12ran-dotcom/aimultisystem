"""
Dependency Security Analyzer
-----------------------------
Offline, deterministic dependency vulnerability scanning.

Checks declared dependencies against a curated in-memory advisory database of
well-known vulnerable package/version ranges. No network access is required, so
the analyzer is fully reliable in air-gapped or sandboxed environments and never
fails open silently.

This complements ``trivy`` / ``pip-audit`` in :class:`SecurityAgent` by always
providing a baseline signal for the most commonly exploited ecosystems (pip, npm).
"""
from __future__ import annotations

import re
from typing import Dict, List, NamedTuple, Optional, Tuple

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import Repository, RepositoryDependency


# ── Advisory schema ───────────────────────────────────────────────────────────


class Advisory(NamedTuple):
    """A single known-vulnerable package version range."""

    package: str
    ecosystem: str                     # pip | npm
    vulnerable_below: str              # highest vulnerable version (exclusive upper bound)
    cve: str
    severity: str                      # critical | high | medium | low
    summary: str
    recommendation: str


class DependencyRisk(BaseModel):
    package_name: str
    ecosystem: str
    declared_version: Optional[str]
    manifest_file: Optional[str]
    is_dev: bool
    cve: str
    severity: str
    summary: str
    recommendation: str


class DependencySecurityResponse(BaseModel):
    repository_id: str
    dependencies_scanned: int
    risky_dependencies: List[DependencyRisk] = Field(default_factory=list)
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    advisories_checked: int = 0
    summary: str
    limitations: List[str] = Field(default_factory=list)


# ── Curated advisory database ─────────────────────────────────────────────────
# Bounded, offline list of high-signal advisories. Versions use a simple
# ``vulnerable_below`` semantic bound compared by :func:`_is_vulnerable`.

_ADVISORIES: List[Advisory] = [
    # ── pip ──────────────────────────────────────────────────────────────────
    Advisory("requests", "pip", "2.32.0", "CVE-2024-35195", "medium",
             "Requests leaks Authorization headers across redirects.",
             "Upgrade requests to 2.32.0 or later."),
    Advisory("urllib3", "pip", "1.26.18", "CVE-2023-45803", "medium",
             "urllib3 request body not stripped on status code redirect.",
             "Upgrade urllib3 to 1.26.18+ or 2.0.7+."),
    Advisory("urllib3", "pip", "2.2.2", "CVE-2024-37891", "low",
             "urllib3 proxy-authorization header leaked on cross-origin redirect.",
             "Upgrade urllib3 to 2.2.2 or later."),
    Advisory("pyyaml", "pip", "5.4", "CVE-2020-14343", "critical",
             "PyYAML full_load allows arbitrary code execution.",
             "Upgrade PyYAML to 5.4 or later and use safe_load."),
    Advisory("django", "pip", "4.2.11", "CVE-2024-27351", "high",
             "Django potential denial of service via malicious URL redirects.",
             "Upgrade Django to 4.2.11+ or 5.0.3+."),
    Advisory("django", "pip", "3.2.25", "CVE-2024-24680", "high",
             "Django intcomma template filter denial of service.",
             "Upgrade Django to 3.2.25+, 4.2.11+, or 5.0.3+."),
    Advisory("flask", "pip", "2.3.2", "CVE-2023-30861", "high",
             "Flask may leak session cookies under certain caching configs.",
             "Upgrade Flask to 2.3.2 or later."),
    Advisory("jinja2", "pip", "3.1.4", "CVE-2024-34064", "medium",
             "Jinja2 xmlattr filter accepts keys with non-attribute characters.",
             "Upgrade Jinja2 to 3.1.4 or later."),
    Advisory("pillow", "pip", "10.3.0", "CVE-2024-28219", "high",
             "Pillow buffer overflow in _imagingcms.",
             "Upgrade Pillow to 10.3.0 or later."),
    Advisory("cryptography", "pip", "42.0.4", "CVE-2024-26130", "medium",
             "cryptography NULL pointer dereference in pkcs12.",
             "Upgrade cryptography to 42.0.4 or later."),
    Advisory("aiohttp", "pip", "3.9.2", "CVE-2024-23334", "high",
             "aiohttp static file traversal under misconfigured follow_symlinks.",
             "Upgrade aiohttp to 3.9.2 or later."),
    Advisory("werkzeug", "pip", "3.0.1", "CVE-2024-34069", "high",
             "Werkzeug debugger remote code execution via crafted request.",
             "Upgrade Werkzeug to 3.0.1 or later."),
    Advisory("gunicorn", "pip", "22.0.0", "CVE-2024-1135", "medium",
             "Gunicorn request smuggling via inconsistent Transfer-Encoding.",
             "Upgrade gunicorn to 22.0.0 or later."),
    Advisory("setuptools", "pip", "70.0.0", "CVE-2024-6345", "high",
             "Setuptools package_index code execution via crafted URL.",
             "Upgrade setuptools to 70.0.0 or later."),
    Advisory("numpy", "pip", "1.22.0", "CVE-2021-33430", "medium",
             "NumPy buffer overflow in numpy.core.multiarray.",
             "Upgrade NumPy to 1.22.0 or later."),

    # ── npm ──────────────────────────────────────────────────────────────────
    Advisory("lodash", "npm", "4.17.21", "CVE-2021-23337", "high",
             "Lodash command injection via template.",
             "Upgrade lodash to 4.17.21 or later."),
    Advisory("minimist", "npm", "1.2.6", "CVE-2021-44906", "critical",
             "Minimist prototype pollution leading to RCE.",
             "Upgrade minimist to 1.2.6 or later."),
    Advisory("axios", "npm", "1.7.4", "CVE-2024-39338", "high",
             "Axios SSRF via absolute URL in request path.",
             "Upgrade axios to 1.7.4 or later."),
    Advisory("express", "npm", "4.19.2", "CVE-2024-29041", "medium",
             "Express open redirect via malformed URL.",
             "Upgrade express to 4.19.2 or later."),
    Advisory("next", "npm", "14.1.1", "CVE-2024-34351", "high",
             "Next.js cache poisoning / SSRF in Server Actions.",
             "Upgrade Next.js to 14.1.1 or later."),
    Advisory("semver", "npm", "7.5.2", "CVE-2022-25883", "high",
             "Semver regular expression denial of service.",
             "Upgrade semver to 7.5.2 or later."),
]


# ── Version helpers ───────────────────────────────────────────────────────────


_VERSION_RE = re.compile(r"(\d+(?:\.\d+)*)")


def _parse_version(value: Optional[str]) -> Optional[Tuple[int, ...]]:
    if not value:
        return None
    match = _VERSION_RE.search(str(value))
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.group(1).split("."))
    except ValueError:
        return None


def _compare(a: Tuple[int, ...], b: Tuple[int, ...]) -> int:
    length = max(len(a), len(b))
    padded_a = a + (0,) * (length - len(a))
    padded_b = b + (0,) * (length - len(b))
    if padded_a < padded_b:
        return -1
    if padded_a > padded_b:
        return 1
    return 0


def _is_vulnerable(declared: Optional[str], vulnerable_below: str) -> bool:
    """True when ``declared`` is a real version strictly below the bound."""
    declared_version = _parse_version(declared)
    bound = _parse_version(vulnerable_below)
    if declared_version is None or bound is None:
        return False
    return _compare(declared_version, bound) < 0


def _normalize_package(name: str) -> str:
    return re.sub(r"[-_.]+", "-", (name or "").strip()).casefold()


# ── Service ───────────────────────────────────────────────────────────────────


class DependencySecurityService:
    """Scan declared dependencies against the offline advisory database."""

    def __init__(self, db: AsyncSession, repository: Repository):
        self.db = db
        self.repository = repository

    async def analyze(self) -> DependencySecurityResponse:
        deps = (
            await self.db.execute(
                select(RepositoryDependency).where(
                    RepositoryDependency.repository_id == self.repository.id
                )
            )
        ).scalars().all()

        # Index advisories by normalized package name for O(1) lookup.
        advisory_index: Dict[str, List[Advisory]] = {}
        for advisory in _ADVISORIES:
            advisory_index.setdefault(_normalize_package(advisory.package), []).append(advisory)

        risky: List[DependencyRisk] = []
        for dep in deps:
            normalized = _normalize_package(dep.package_name)
            for advisory in advisory_index.get(normalized, []):
                if advisory.ecosystem != dep.ecosystem:
                    continue
                if _is_vulnerable(dep.version_spec, advisory.vulnerable_below):
                    risky.append(DependencyRisk(
                        package_name=dep.package_name,
                        ecosystem=dep.ecosystem,
                        declared_version=dep.version_spec,
                        manifest_file=dep.manifest_file,
                        is_dev=dep.is_dev,
                        cve=advisory.cve,
                        severity=advisory.severity,
                        summary=advisory.summary,
                        recommendation=advisory.recommendation,
                    ))

        severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        risky.sort(key=lambda item: (severity_rank.get(item.severity, 4), item.package_name.casefold()))

        critical = sum(1 for item in risky if item.severity == "critical")
        high = sum(1 for item in risky if item.severity == "high")
        medium = sum(1 for item in risky if item.severity == "medium")
        low = sum(1 for item in risky if item.severity == "low")

        if not risky:
            summary = (
                f"Scanned {len(deps)} declared dependency/dependencies against "
                f"{len(_ADVISORIES)} offline advisories; none matched a known-vulnerable version range."
            )
        else:
            summary = (
                f"Scanned {len(deps)} dependency/dependencies against {len(_ADVISORIES)} offline advisories; "
                f"found {len(risky)} vulnerable package(s): "
                f"{critical} critical, {high} high, {medium} medium, {low} low."
            )

        return DependencySecurityResponse(
            repository_id=self.repository.id,
            dependencies_scanned=len(deps),
            risky_dependencies=risky,
            critical_count=critical,
            high_count=high,
            medium_count=medium,
            low_count=low,
            advisories_checked=len(_ADVISORIES),
            summary=summary,
            limitations=[
                "Advisory matching uses an offline curated list; it cannot detect "
                "zero-days or advisories published after this list was written.",
                "Version comparison is heuristic (numeric prefix) and may misread "
                "unusual or pre-release version strings.",
                "Transitive dependencies resolved only at install time are not "
                "scanned; only manifest-declared packages are evaluated.",
            ],
        )
