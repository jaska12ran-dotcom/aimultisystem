"""
Production Readiness Score Service
------------------------------------
Aggregates signals from:
  - Security analysis (SecurityAgent)
  - Technical debt (TechnicalDebtService)
  - Test strength (TestIntelligenceService)
  - Git history / churn
  - Documentation presence

Produces a single composite 0-100 score with a letter grade and
per-dimension breakdown so developers know exactly what to fix.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import Repository
from app.services.technical_debt import TechnicalDebtService
from app.services.test_intelligence import TestIntelligenceService


# ── Output schema ──────────────────────────────────────────────────────────────


class ReadinessDimension(BaseModel):
    name: str
    score: float          # 0-100
    weight: float         # contribution weight (0-1, sum == 1)
    grade: str            # A/B/C/D/F
    findings: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class ProductionReadinessResponse(BaseModel):
    repository_id: str
    overall_score: float       # 0-100
    grade: str                 # A/B/C/D/F
    dimensions: List[ReadinessDimension] = Field(default_factory=list)
    summary: str
    blockers: List[str] = Field(default_factory=list)
    quick_wins: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _letter(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


# ── Service ────────────────────────────────────────────────────────────────────


class ProductionReadinessService:
    """
    Compute a composite production-readiness score from indexed repository data.

    Dimension weights (tunable):
      security       35 %
      test_coverage  25 %
      tech_debt      20 %
      documentation  10 %
      git_stability  10 %
    """

    WEIGHTS = {
        "security": 0.35,
        "test_coverage": 0.25,
        "tech_debt": 0.20,
        "documentation": 0.10,
        "git_stability": 0.10,
    }

    def __init__(self, db: AsyncSession, repository: Repository):
        self.db = db
        self.repository = repository

    async def analyze(
        self,
        security_response: Optional[Any] = None,
    ) -> ProductionReadinessResponse:
        """
        Parameters
        ----------
        security_response : SecurityAnalysisResponse | None
            Pass the already-computed security response to avoid re-running
            the full scanner (slow).  If None the dimension uses safe defaults.
        """
        dimensions: List[ReadinessDimension] = []

        # ── Security dimension ────────────────────────────────────────────────
        sec_dim = self._score_security(security_response)
        dimensions.append(sec_dim)

        # ── Test coverage dimension ───────────────────────────────────────────
        test_dim = await self._score_tests()
        dimensions.append(test_dim)

        # ── Technical debt dimension ──────────────────────────────────────────
        debt_dim = await self._score_debt()
        dimensions.append(debt_dim)

        # ── Documentation dimension ───────────────────────────────────────────
        doc_dim = await self._score_docs()
        dimensions.append(doc_dim)

        # ── Git stability dimension ───────────────────────────────────────────
        git_dim = await self._score_git_stability()
        dimensions.append(git_dim)

        # ── Composite score ───────────────────────────────────────────────────
        overall = sum(d.score * d.weight for d in dimensions)
        overall = round(overall, 1)

        blockers = [
            f
            for d in dimensions
            for f in d.findings
            if any(kw in f.lower() for kw in ("critical", "high", "blocker", "no test"))
        ][:5]
        quick_wins = [
            r
            for d in dimensions
            for r in d.recommendations
            if any(kw in r.lower() for kw in ("add", "run", "enable", "update", "fix"))
        ][:5]

        grade = _letter(overall)
        summary = (
            f"Production readiness: {grade} ({overall}/100). "
            + (
                f"{len(blockers)} blocker(s) found — address these before release. "
                if blockers
                else "No critical blockers detected. "
            )
            + f"Top quick win: {quick_wins[0]}" if quick_wins else ""
        )

        return ProductionReadinessResponse(
            repository_id=self.repository.id,
            overall_score=overall,
            grade=grade,
            dimensions=dimensions,
            summary=summary,
            blockers=blockers,
            quick_wins=quick_wins,
            limitations=[
                "Scores are based on statically indexed evidence; runtime behaviour is not assessed.",
                "Security dimension requires security tools (semgrep/bandit/etc.) to be installed for accurate results.",
                "Test coverage is estimated from indexed symbol-to-test relationships, not instrumented code coverage.",
            ],
        )

    # ── Dimension scorers ──────────────────────────────────────────────────────

    def _score_security(self, sec_response: Optional[Any]) -> ReadinessDimension:
        weight = self.WEIGHTS["security"]
        if sec_response is None:
            return ReadinessDimension(
                name="security",
                score=50.0,
                weight=weight,
                grade="C",
                findings=["Security scan not yet run — score defaulted to 50."],
                recommendations=["Run POST /security/analyze to get an accurate security score."],
            )

        dashboard = sec_response.dashboard
        total = dashboard.total_findings
        findings = []
        recommendations = []

        # Penalty schedule (per finding):  critical=20, high=10, medium=3, low=1
        penalty = (
            dashboard.critical * 20
            + dashboard.high * 10
            + dashboard.medium * 3
            + dashboard.low * 1
        )
        score = max(0.0, 100.0 - penalty)

        if dashboard.critical:
            findings.append(f"{dashboard.critical} CRITICAL security finding(s) — release blocker.")
            recommendations.append("Fix all critical security findings before deployment.")
        if dashboard.high:
            findings.append(f"{dashboard.high} HIGH severity finding(s) require prompt attention.")
            recommendations.append("Remediate high-severity findings; they often indicate exploitable issues.")
        if total == 0:
            findings.append("No security issues detected by configured tools.")

        return ReadinessDimension(
            name="security",
            score=round(score, 1),
            weight=weight,
            grade=_letter(score),
            findings=findings,
            recommendations=recommendations,
        )

    async def _score_tests(self) -> ReadinessDimension:
        weight = self.WEIGHTS["test_coverage"]
        try:
            strength = await TestIntelligenceService(self.db, self.repository).analyze_strength()
            linked = strength.mapped_symbols
            total = strength.analyzed_symbols
            pct = (linked / total * 100) if total > 0 else 0.0
            score = min(100.0, pct)
            findings = [f"{linked}/{total} symbols ({pct:.0f}%) have test coverage."]
            recommendations = []
            if pct < 40:
                findings.append("Low test coverage — major risk for regressions.")
                recommendations.append("Generate tests for untested symbols via POST /tests/pipeline.")
            elif pct < 70:
                recommendations.append("Improve test coverage for core API routes and data models.")
            return ReadinessDimension(
                name="test_coverage",
                score=round(score, 1),
                weight=weight,
                grade=_letter(score),
                findings=findings,
                recommendations=recommendations,
            )
        except Exception as exc:
            return ReadinessDimension(
                name="test_coverage", score=40.0, weight=weight, grade="D",
                findings=[f"Test analysis unavailable: {exc}"],
                recommendations=["Run tests pipeline to assess coverage."],
            )

    async def _score_debt(self) -> ReadinessDimension:
        weight = self.WEIGHTS["tech_debt"]
        try:
            debt = await TechnicalDebtService(self.db, self.repository).analyze()
            high_sev = [f for f in debt.findings if f.severity in {"high"}]
            medium_sev = [f for f in debt.findings if f.severity == "medium"]
            penalty = len(high_sev) * 8 + len(medium_sev) * 3
            score = max(0.0, 100.0 - penalty)
            findings = [f"{len(debt.findings)} debt finding(s): {len(high_sev)} high, {len(medium_sev)} medium."]
            recommendations = []
            if high_sev:
                recommendations.append(f"Address high-severity debt: {high_sev[0].title}.")
            if medium_sev:
                recommendations.append("Review circular dependencies and oversized modules.")
            return ReadinessDimension(
                name="tech_debt",
                score=round(score, 1),
                weight=weight,
                grade=_letter(score),
                findings=findings,
                recommendations=recommendations,
            )
        except Exception as exc:
            return ReadinessDimension(
                name="tech_debt", score=50.0, weight=weight, grade="C",
                findings=[f"Debt analysis unavailable: {exc}"],
                recommendations=["Run GET /technical-debt for a full analysis."],
            )

    async def _score_docs(self) -> ReadinessDimension:
        weight = self.WEIGHTS["documentation"]
        from sqlalchemy import select, func
        from app.models.agent_artifact import GeneratedDoc
        from app.models.repository import RepositoryFile

        try:
            doc_count = await self.db.scalar(
                select(func.count(GeneratedDoc.id)).where(
                    GeneratedDoc.repository_id == self.repository.id
                )
            ) or 0
            doc_file_count = await self.db.scalar(
                select(func.count(RepositoryFile.id)).where(
                    RepositoryFile.repository_id == self.repository.id,
                    RepositoryFile.is_documentation == True,
                )
            ) or 0
            score = min(100.0, doc_count * 15 + doc_file_count * 5)
            findings = [
                f"{doc_count} AI-generated doc(s), {doc_file_count} documentation file(s) detected."
            ]
            recommendations = []
            if doc_count == 0:
                recommendations.append("Generate architecture and API docs via POST /docs/generate.")
            return ReadinessDimension(
                name="documentation",
                score=round(score, 1),
                weight=weight,
                grade=_letter(score),
                findings=findings,
                recommendations=recommendations,
            )
        except Exception as exc:
            return ReadinessDimension(
                name="documentation", score=30.0, weight=weight, grade="D",
                findings=[f"Documentation check unavailable: {exc}"],
                recommendations=["Generate documentation to improve this score."],
            )

    async def _score_git_stability(self) -> ReadinessDimension:
        weight = self.WEIGHTS["git_stability"]
        from sqlalchemy import select
        from app.models.repository import GitCommit

        try:
            commits = (
                await self.db.execute(
                    select(GitCommit)
                    .where(GitCommit.repository_id == self.repository.id)
                    .order_by(GitCommit.committed_at.desc())
                    .limit(50)
                )
            ).scalars().all()

            if not commits:
                return ReadinessDimension(
                    name="git_stability", score=50.0, weight=weight, grade="C",
                    findings=["No Git history indexed — stability cannot be assessed."],
                    recommendations=["Ingest from a Git repository to enable history analysis."],
                )

            # Churn: ratio of recent fix commits
            fix_msgs = [c for c in commits if any(
                kw in (c.message or "").lower() for kw in ("fix", "bug", "hotfix", "revert", "crash")
            )]
            fix_ratio = len(fix_msgs) / max(len(commits), 1)
            score = max(0.0, 100.0 - fix_ratio * 60)

            findings = [
                f"Analyzed {len(commits)} recent commits; {len(fix_msgs)} are bug-fix commits ({fix_ratio:.0%})."
            ]
            recommendations = []
            if fix_ratio > 0.3:
                recommendations.append("High bug-fix commit ratio; review recent changes carefully before release.")
            elif fix_ratio > 0.15:
                recommendations.append("Moderate bug-fix ratio; ensure regressions are covered by tests.")

            return ReadinessDimension(
                name="git_stability",
                score=round(score, 1),
                weight=weight,
                grade=_letter(score),
                findings=findings,
                recommendations=recommendations,
            )
        except Exception as exc:
            return ReadinessDimension(
                name="git_stability", score=50.0, weight=weight, grade="C",
                findings=[f"Git stability analysis unavailable: {exc}"],
                recommendations=[],
            )
