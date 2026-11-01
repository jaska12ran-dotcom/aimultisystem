"""
Code Health Score Service
-------------------------
Produces a maintenance-focused 0-100 health score with a per-dimension breakdown.

Unlike :class:`ProductionReadinessService` (which gates a release decision), this
service answers a different question: *how healthy is this codebase to maintain
over time?*  It aggregates deterministic signals that require no LLM and no
network access, so the score is reproducible and reliable:

  - security posture   (severity-weighted findings)
  - test coverage      (symbols linked to tests)
  - documentation      (README presence + docstring coverage)
  - dependency risk    (offline advisory scan)
  - code structure     (complexity + oversized modules)
  - git stability      (churn and recency of change)
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import List

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import (
    CodeSymbol,
    GitCommit,
    Repository,
    RepositoryDependency,
    RepositoryFile,
)
from app.services.dependency_security import DependencySecurityService
from app.services.test_intelligence import TestIntelligenceService


class HealthDimension(BaseModel):
    name: str
    score: float          # 0-100
    weight: float         # 0-1, sum == 1
    grade: str            # A/B/C/D/F
    findings: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class CodeHealthResponse(BaseModel):
    repository_id: str
    overall_score: float
    grade: str
    dimensions: List[HealthDimension] = Field(default_factory=list)
    summary: str
    top_risks: List[str] = Field(default_factory=list)
    quick_wins: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


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


class CodeHealthService:
    """Compute a composite maintenance health score from indexed repository data."""

    WEIGHTS = {
        "security": 0.25,
        "tests": 0.25,
        "documentation": 0.15,
        "dependencies": 0.15,
        "structure": 0.10,
        "stability": 0.10,
    }

    def __init__(self, db: AsyncSession, repository: Repository):
        self.db = db
        self.repository = repository

    async def analyze(self) -> CodeHealthResponse:
        dimensions: List[HealthDimension] = [
            await self._score_security(),
            await self._score_tests(),
            await self._score_documentation(),
            await self._score_dependencies(),
            await self._score_structure(),
            await self._score_stability(),
        ]

        overall = round(sum(d.score * d.weight for d in dimensions), 1)
        top_risks = [
            f"{d.name}: {d.findings[0]}"
            for d in sorted(dimensions, key=lambda item: item.score)
            if d.score < 60 and d.findings
        ]
        quick_wins = [
            rec
            for d in sorted(dimensions, key=lambda item: -item.score)
            for rec in d.recommendations[:1]
        ][:4]

        if overall >= 75:
            summary = f"Healthy codebase ({overall}/100, grade {_letter(overall)}). Maintain current practices."
        elif overall >= 50:
            summary = f"Moderately healthy ({overall}/100, grade {_letter(overall)}). Address the weakest dimensions below."
        else:
            summary = f"Codebase needs attention ({overall}/100, grade {_letter(overall)}). Prioritize the top risks."

        return CodeHealthResponse(
            repository_id=self.repository.id,
            overall_score=overall,
            grade=_letter(overall),
            dimensions=dimensions,
            summary=summary,
            top_risks=top_risks,
            quick_wins=quick_wins,
            limitations=[
                "Scores are heuristic aggregates of static signals and should guide "
                "attention, not be treated as absolute quality measures.",
                "Documentation scoring measures README presence and docstring "
                "coverage, not factual accuracy of the documentation content.",
                "Test scoring reflects symbol-to-test linkage in the index, not "
                "the behavioral correctness of existing tests.",
            ],
        )

    # ── Dimension scorers ────────────────────────────────────────────────────

    async def _score_security(self) -> HealthDimension:
        weight = self.WEIGHTS["security"]
        try:
            from agents.security_agent import SecurityAgent

            response = await SecurityAgent().analyze_repository(
                self.repository.id, self.repository.local_path
            )
            counts = response.dashboard
            # Severity-weighted penalty: critical=-25, high=-12, medium=-5, low=-2
            penalty = (
                counts.critical * 25
                + counts.high * 12
                + counts.medium * 5
                + counts.low * 2
            )
            score = max(0.0, 100.0 - penalty)
            findings: List[str] = []
            recommendations: List[str] = []
            if counts.critical:
                findings.append(f"{counts.critical} critical security finding(ies).")
                recommendations.append("Remediate critical security findings immediately.")
            elif counts.high:
                findings.append(f"{counts.high} high-severity security finding(ies).")
                recommendations.append("Address high-severity security findings before release.")
            else:
                findings.append("No critical or high-severity security findings.")
            return HealthDimension(
                name="security", score=round(score, 1), weight=weight,
                grade=_letter(score), findings=findings, recommendations=recommendations,
            )
        except Exception as exc:
            return HealthDimension(
                name="security", score=50.0, weight=weight, grade="C",
                findings=[f"Security analysis unavailable: {exc}"],
                recommendations=["Re-run security analysis once scanners are available."],
            )

    async def _score_tests(self) -> HealthDimension:
        weight = self.WEIGHTS["tests"]
        try:
            strength = await TestIntelligenceService(self.db, self.repository).analyze_strength()
            pct = (
                strength.mapped_symbols / strength.analyzed_symbols * 100
                if strength.analyzed_symbols
                else 0.0
            )
            score = min(100.0, pct)
            findings = [f"{strength.mapped_symbols}/{strength.analyzed_symbols} symbols ({pct:.0f}%) are linked to tests."]
            recommendations = []
            if pct < 40:
                recommendations.append("Generate tests for untested symbols via the test pipeline.")
            elif pct < 70:
                recommendations.append("Extend tests to cover more core API routes and models.")
            return HealthDimension(
                name="tests", score=round(score, 1), weight=weight,
                grade=_letter(score), findings=findings, recommendations=recommendations,
            )
        except Exception as exc:
            return HealthDimension(
                name="tests", score=40.0, weight=weight, grade="D",
                findings=[f"Test analysis unavailable: {exc}"],
                recommendations=["Run test-strength analysis to assess coverage."],
            )

    async def _score_documentation(self) -> HealthDimension:
        weight = self.WEIGHTS["documentation"]
        files = (
            await self.db.execute(
                select(RepositoryFile).where(
                    RepositoryFile.repository_id == self.repository.id
                )
            )
        ).scalars().all()
        symbols = (
            await self.db.execute(
                select(CodeSymbol).where(
                    CodeSymbol.repository_id == self.repository.id,
                    CodeSymbol.symbol_type.in_(["function", "method", "class"]),
                )
            )
        ).scalars().all()

        doc_files = [f for f in files if f.is_documentation]
        has_readme = any(
            re.search(r"readme", f.file_name, re.IGNORECASE) for f in doc_files
        )
        documented = sum(1 for s in symbols if (s.docstring or "").strip())
        docstring_pct = documented / len(symbols) * 100 if symbols else 0.0

        # Blend: 40 pts for README presence, 60 pts for docstring coverage.
        score = (40.0 if has_readme else 0.0) + docstring_pct * 0.6
        score = min(100.0, score)

        findings: List[str] = []
        recommendations: List[str] = []
        if not has_readme:
            findings.append("No README documentation file detected.")
            recommendations.append("Generate a README via the documentation agent.")
        findings.append(f"Docstring coverage across {len(symbols)} symbols: {docstring_pct:.0f}%.")
        if docstring_pct < 50:
            recommendations.append("Document public functions and classes with docstrings.")

        return HealthDimension(
            name="documentation", score=round(score, 1), weight=weight,
            grade=_letter(score), findings=findings, recommendations=recommendations,
        )

    async def _score_dependencies(self) -> HealthDimension:
        weight = self.WEIGHTS["dependencies"]
        try:
            result = await DependencySecurityService(self.db, self.repository).analyze()
            penalty = (
                result.critical_count * 25
                + result.high_count * 12
                + result.medium_count * 5
                + result.low_count * 2
            )
            score = max(0.0, 100.0 - penalty)
            findings: List[str] = []
            recommendations: List[str] = []
            if result.risky_dependencies:
                worst = result.risky_dependencies[0]
                findings.append(
                    f"{len(result.risky_dependencies)} known-vulnerable dependency/dependencies "
                    f"(worst: {worst.package_name} {worst.cve})."
                )
                recommendations.append("Upgrade vulnerable dependencies to patched versions.")
            else:
                findings.append(f"No known-vulnerable dependencies across {result.dependencies_scanned} scanned.")
            return HealthDimension(
                name="dependencies", score=round(score, 1), weight=weight,
                grade=_letter(score), findings=findings, recommendations=recommendations,
            )
        except Exception as exc:
            return HealthDimension(
                name="dependencies", score=60.0, weight=weight, grade="C",
                findings=[f"Dependency scan unavailable: {exc}"],
                recommendations=["Re-run the dependency security scan."],
            )

    async def _score_structure(self) -> HealthDimension:
        weight = self.WEIGHTS["structure"]
        symbols = (
            await self.db.execute(
                select(CodeSymbol).where(CodeSymbol.repository_id == self.repository.id)
            )
        ).scalars().all()
        files = (
            await self.db.execute(
                select(RepositoryFile).where(
                    RepositoryFile.repository_id == self.repository.id
                )
            )
        ).scalars().all()

        complex_symbols = [s for s in symbols if (s.complexity_score or 1) >= 10]
        very_complex = [s for s in symbols if (s.complexity_score or 1) >= 20]
        oversized = [f for f in files if not f.is_binary and f.line_count >= 800]

        total = len(symbols) or 1
        complex_pct = len(complex_symbols) / total * 100
        penalty = len(very_complex) * 3 + len(oversized) * 5 + max(0.0, complex_pct - 10)
        score = max(0.0, 100.0 - penalty)

        findings: List[str] = []
        recommendations: List[str] = []
        if very_complex:
            findings.append(f"{len(very_complex)} very complex symbol(s) (score >= 20).")
            recommendations.append("Break down the most complex functions into smaller units.")
        if oversized:
            findings.append(f"{len(oversized)} oversized module(s) (>= 800 lines).")
            recommendations.append("Split oversized modules along cohesive responsibility lines.")
        if not findings:
            findings.append("No significant structural complexity issues detected.")
        return HealthDimension(
            name="structure", score=round(score, 1), weight=weight,
            grade=_letter(score), findings=findings, recommendations=recommendations,
        )

    async def _score_stability(self) -> HealthDimension:
        weight = self.WEIGHTS["stability"]
        commits = (
            await self.db.execute(
                select(GitCommit).where(GitCommit.repository_id == self.repository.id)
            )
        ).scalars().all()

        if not commits:
            return HealthDimension(
                name="stability", score=60.0, weight=weight, grade="C",
                findings=["No Git history indexed; stability cannot be assessed."],
                recommendations=["Ingest a Git-backed repository to enable stability analysis."],
            )

        churn: dict[str, int] = defaultdict(int)
        for commit in commits:
            for path in commit.files_changed or []:
                churn[path] += (commit.insertions or 0) + (commit.deletions or 0)

        high_churn = [path for path, value in churn.items() if value >= 500]
        penalty = min(40.0, len(high_churn) * 4)
        score = max(0.0, 100.0 - penalty)

        findings: List[str] = []
        recommendations: List[str] = []
        if high_churn:
            findings.append(f"{len(high_churn)} high-churn file(s) (>= 500 changed lines in history).")
            recommendations.append("Add or strengthen tests around high-churn files before refactoring.")
        else:
            findings.append("No extreme churn hotspots detected in indexed history.")
        return HealthDimension(
            name="stability", score=round(score, 1), weight=weight,
            grade=_letter(score), findings=findings, recommendations=recommendations,
        )
