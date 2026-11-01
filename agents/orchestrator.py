"""
Supervisor / Orchestrator Agent
---------------------------------
Routes developer requests to the appropriate specialist agent and
assembles a unified response.  Supports both single-task dispatch
and multi-step workflows.

Supported tasks (intent → agent mapping):
  bug / error / crash / stack_trace  → BugDetectiveAgent
  test / coverage / missing tests    → TestGenerationPipeline / TestIntelligenceService
  security / vulnerability / secret  → SecurityAgent
  docs / readme / api docs           → DocumentationAgent
  impact / change / what will break  → ChangeImpactService
  debt / complexity / refactor       → TechnicalDebtService
  why / history / commit             → GitHistoryService
  onboarding / explain / how         → DeveloperKnowledgeService
  pr / pull request / description    → PRDescriptionService
  breaking / api change              → BreakingChangeService
  sensitive / pii / data flow        → SensitiveDataFlowService
  readiness / score / health         → ProductionReadinessService
  heal / fix test / failing          → SelfHealingAgent

Intent classification is keyword-based with LLM refinement when available.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import Repository
from intelligence.llm_client import default_llm_client


# ── Output schema ──────────────────────────────────────────────────────────────


class OrchestratorStep(BaseModel):
    agent: str
    status: str           # dispatched | completed | skipped | failed
    result_summary: str
    result: Optional[Dict[str, Any]] = None


class OrchestratorResponse(BaseModel):
    repository_id: str
    intent: str
    steps: List[OrchestratorStep] = Field(default_factory=list)
    answer: str
    confidence: str = "medium"
    limitations: List[str] = Field(default_factory=list)


# ── Intent classifier ──────────────────────────────────────────────────────────

_INTENT_KEYWORDS: Dict[str, List[str]] = {
    "bug": ["bug", "error", "crash", "exception", "traceback", "stack trace", "not working", "broken"],
    "test": ["test", "coverage", "unit test", "missing test", "test gap", "untested", "write test"],
    "heal_test": ["heal", "fix test", "failing test", "repair test", "self-heal", "fix failing", "broken test", "test is failing"],
    "security": ["security", "vulnerability", "cve", "secret", "api key", "injection", "xss", "csrf"],
    "docs": ["docs", "documentation", "readme", "api doc", "generate doc"],
    "impact": ["impact", "what will break", "change impact", "affected files", "downstream"],
    "debt": ["debt", "complexity", "refactor", "clean up", "technical debt", "circular"],
    "history": ["why", "history", "commit", "when was", "who changed", "git log"],
    "onboarding": ["onboarding", "explain", "how does", "new to", "entry point", "where to start"],
    "pr": ["pr description", "pull request", "pr body", "merge request description"],
    "breaking": ["breaking change", "api change", "backward compat", "removed endpoint", "deprecated"],
    "sensitive": ["sensitive data", "pii", "data flow", "password flow", "taint", "privacy"],
    "readiness": ["production ready", "readiness", "deploy", "health score", "composite score", "release"],
    "health": ["code health", "health score", "maintainability", "healthy", "code quality score"],
    "dependencies": ["dependency vulnerability", "vulnerable dependency", "vulnerable dependencies", "dependency security", "outdated package", "cve"],
}


def _classify_intent(query: str) -> str:
    q = query.lower()
    scores: Dict[str, int] = {}
    for intent, keywords in _INTENT_KEYWORDS.items():
        # Multi-word keywords are more specific and outweigh single tokens, so
        # "vulnerable dependency" beats a bare "cve" tie.
        scores[intent] = sum(
            len(kw.split()) if kw in q else 0 for kw in keywords
        )
    best_intent = max(scores, key=lambda k: (scores[k], k == "heal_test"))
    return best_intent if scores[best_intent] > 0 else "onboarding"


# ── Orchestrator ───────────────────────────────────────────────────────────────


class OrchestratorAgent:
    """Route developer queries to specialist agents and return a unified answer."""

    def __init__(self, llm_client=default_llm_client):
        self.llm = llm_client

    async def run(
        self,
        db: AsyncSession,
        repo: Repository,
        query: str,
        # Optional extra inputs forwarded to specialist agents
        stack_trace: Optional[str] = None,
        changed_files: Optional[List[str]] = None,
        diff: Optional[str] = None,
        test_code: Optional[str] = None,
        execution_output: Optional[str] = None,
        generate_mre: bool = False,
        security_response: Optional[Any] = None,
        previous_snapshot: Optional[List[Dict[str, Any]]] = None,
    ) -> OrchestratorResponse:
        intent = _classify_intent(query)
        steps: List[OrchestratorStep] = []
        answer_parts: List[str] = []
        confidence = "medium"
        limitations: List[str] = []

        # ── Dispatch to specialist agent ───────────────────────────────────────

        if intent == "bug":
            step, text = await self._run_bug_detective(
                db, repo, query, stack_trace, generate_mre
            )
            steps.append(step)
            answer_parts.append(text)
            confidence = "high" if stack_trace else "medium"
            limitations.append("Investigation is over static indexed data only.")

        elif intent in {"test", "heal_test"}:
            if intent == "heal_test" and test_code and execution_output:
                step, text = await self._run_self_healing(
                    db, repo, test_code, execution_output
                )
            else:
                step, text = await self._run_test_gap(db, repo)
            steps.append(step)
            answer_parts.append(text)

        elif intent == "security":
            step, text = await self._run_security(db, repo)
            steps.append(step)
            answer_parts.append(text)
            limitations.append("Requires semgrep/bandit/gitleaks installed for full results.")

        elif intent == "docs":
            step, text = await self._run_docs(db, repo)
            steps.append(step)
            answer_parts.append(text)

        elif intent == "impact":
            step, text = await self._run_impact(db, repo, changed_files or [], diff)
            steps.append(step)
            answer_parts.append(text)

        elif intent == "debt":
            step, text = await self._run_debt(db, repo)
            steps.append(step)
            answer_parts.append(text)

        elif intent == "history":
            step, text = await self._run_history(db, repo, query)
            steps.append(step)
            answer_parts.append(text)

        elif intent == "pr":
            step, text = await self._run_pr_description(db, repo, changed_files or [], diff)
            steps.append(step)
            answer_parts.append(text)

        elif intent == "breaking":
            step, text = await self._run_breaking_change(
                db, repo, diff, previous_snapshot
            )
            steps.append(step)
            answer_parts.append(text)

        elif intent == "sensitive":
            step, text = await self._run_sensitive_flow(db, repo)
            steps.append(step)
            answer_parts.append(text)

        elif intent == "readiness":
            step, text = await self._run_readiness(db, repo, security_response)
            steps.append(step)
            answer_parts.append(text)

        elif intent == "health":
            step, text = await self._run_code_health(db, repo)
            steps.append(step)
            answer_parts.append(text)

        elif intent == "dependencies":
            step, text = await self._run_dependency_security(db, repo)
            steps.append(step)
            answer_parts.append(text)

        else:  # onboarding / explain / fallback
            step, text = await self._run_onboarding(db, repo)
            steps.append(step)
            answer_parts.append(text)

        # ── LLM synthesis ──────────────────────────────────────────────────────
        raw_answer = "\n\n".join(answer_parts)
        synthesized = await self._synthesize(query, intent, raw_answer)

        return OrchestratorResponse(
            repository_id=repo.id,
            intent=intent,
            steps=steps,
            answer=synthesized or raw_answer,
            confidence=confidence,
            limitations=limitations,
        )

    # ── Specialist dispatch helpers ────────────────────────────────────────────

    async def _run_bug_detective(
        self, db, repo, query, stack_trace, generate_mre
    ) -> tuple[OrchestratorStep, str]:
        try:
            from agents.bug_detective import BugDetectiveAgent
            result = await BugDetectiveAgent(self.llm).investigate(
                db, repo, query, stack_trace=stack_trace, generate_mre=generate_mre
            )
            suspects_text = "\n".join(
                f"- {s.file}" + (f" ({s.symbol})" if s.symbol else "")
                + f" [{s.confidence}]: {s.reason}"
                for s in result.suspects[:5]
            )
            text = (
                f"**Root cause hypothesis:** {result.root_cause_hypothesis}\n\n"
                f"**Top suspect locations:**\n{suspects_text}"
            )
            return OrchestratorStep(
                agent="BugDetectiveAgent",
                status="completed",
                result_summary=f"{len(result.suspects)} suspect(s) identified.",
                result=result.model_dump(),
            ), text
        except Exception as exc:
            return OrchestratorStep(agent="BugDetectiveAgent", status="failed", result_summary=str(exc)), f"Bug investigation failed: {exc}"

    async def _run_self_healing(self, db, repo, test_code, execution_output) -> tuple[OrchestratorStep, str]:
        try:
            from agents.self_healing_agent import SelfHealingAgent
            result = await SelfHealingAgent(self.llm).heal(db, repo, test_code, execution_output)
            text = (
                f"**Self-healing {'succeeded' if result['success'] else 'partially applied'}**\n"
                f"Passes attempted: {result['passes_attempted']}\n"
                f"Diagnosis: {result['diagnosis']}"
            )
            return OrchestratorStep(
                agent="SelfHealingAgent",
                status="completed",
                result_summary=f"Healed={result['success']}, passes={result['passes_attempted']}",
                result=result,
            ), text
        except Exception as exc:
            return OrchestratorStep(agent="SelfHealingAgent", status="failed", result_summary=str(exc)), f"Self-healing failed: {exc}"

    async def _run_test_gap(self, db, repo) -> tuple[OrchestratorStep, str]:
        try:
            from app.services.test_intelligence import TestIntelligenceService
            result = await TestIntelligenceService(db, repo).analyze_strength()
            gap_count = sum(1 for s in result.symbols if s.potential_gaps or s.mapping_status != "linked")
            text = (
                f"**Test gap analysis:** {result.mapped_symbols}/{result.analyzed_symbols} symbols tested "
                f"({result.mapped_symbols / max(result.analyzed_symbols, 1) * 100:.0f}%). "
                f"{gap_count} gap(s) detected."
            )
            return OrchestratorStep(
                agent="TestIntelligenceService",
                status="completed",
                result_summary=text,
                result=result.model_dump(),
            ), text
        except Exception as exc:
            return OrchestratorStep(agent="TestIntelligenceService", status="failed", result_summary=str(exc)), str(exc)

    async def _run_security(self, db, repo) -> tuple[OrchestratorStep, str]:
        try:
            from agents.security_agent import SecurityAgent
            result = await SecurityAgent().analyze_repository(repo.id, repo.local_path)
            text = result.summary
            return OrchestratorStep(
                agent="SecurityAgent",
                status="completed",
                result_summary=result.summary,
                result=result.model_dump(),
            ), text
        except Exception as exc:
            return OrchestratorStep(agent="SecurityAgent", status="failed", result_summary=str(exc)), str(exc)

    async def _run_docs(self, db, repo) -> tuple[OrchestratorStep, str]:
        try:
            from agents.documentation_agent import DocumentationAgent
            title, content, syms, files = await DocumentationAgent().generate_documentation(
                db, repo.id, "architecture"
            )
            text = f"**Generated:** {title}\n\n{content[:600]}…"
            return OrchestratorStep(
                agent="DocumentationAgent",
                status="completed",
                result_summary=f"Generated '{title}'",
                result={"title": title, "content": content[:400]},
            ), text
        except Exception as exc:
            return OrchestratorStep(agent="DocumentationAgent", status="failed", result_summary=str(exc)), str(exc)

    async def _run_impact(self, db, repo, changed_files, diff) -> tuple[OrchestratorStep, str]:
        try:
            from app.services.change_impact import ChangeImpactService
            query = changed_files[0] if changed_files else ""
            result = await ChangeImpactService(db, repo).analyze(
                query=query, file_path=query, diff=diff
            )
            text = (
                f"**Change impact for `{result.symbol}`:** "
                f"{len(result.affected_files)} file(s) affected. "
                f"Risk: {result.overall_risk}. Confidence: {result.confidence:.0%}"
            )
            return OrchestratorStep(
                agent="ChangeImpactService",
                status="completed",
                result_summary=text,
                result=result.model_dump(),
            ), text
        except Exception as exc:
            return OrchestratorStep(agent="ChangeImpactService", status="failed", result_summary=str(exc)), str(exc)

    async def _run_debt(self, db, repo) -> tuple[OrchestratorStep, str]:
        try:
            from app.services.technical_debt import TechnicalDebtService
            result = await TechnicalDebtService(db, repo).analyze()
            text = result.summary
            return OrchestratorStep(
                agent="TechnicalDebtService",
                status="completed",
                result_summary=result.summary,
                result=result.model_dump(),
            ), text
        except Exception as exc:
            return OrchestratorStep(agent="TechnicalDebtService", status="failed", result_summary=str(exc)), str(exc)

    async def _run_history(self, db, repo, query) -> tuple[OrchestratorStep, str]:
        try:
            from app.services.git_history import GitHistoryService
            target = re.search(r"[\w/.]+\.\w{2,4}", query)
            if target:
                result = await GitHistoryService(db, repo).why_code_exists(target.group(0))
                text = result.answer
            else:
                result = await GitHistoryService(db, repo).analyze()
                text = result.summary
            return OrchestratorStep(
                agent="GitHistoryService",
                status="completed",
                result_summary=text[:200],
                result=result.model_dump() if hasattr(result, "model_dump") else {},
            ), text
        except Exception as exc:
            return OrchestratorStep(agent="GitHistoryService", status="failed", result_summary=str(exc)), str(exc)

    async def _run_pr_description(self, db, repo, changed_files, diff) -> tuple[OrchestratorStep, str]:
        try:
            from app.services.pr_description import PRDescriptionService
            result = await PRDescriptionService(db, repo, self.llm).generate(
                changed_files=changed_files, diff=diff
            )
            text = f"**PR Title:** {result.title}\n\n{result.description_markdown[:600]}"
            return OrchestratorStep(
                agent="PRDescriptionService",
                status="completed",
                result_summary=f"Title: {result.title}",
                result=result.model_dump(),
            ), text
        except Exception as exc:
            return OrchestratorStep(agent="PRDescriptionService", status="failed", result_summary=str(exc)), str(exc)

    async def _run_breaking_change(self, db, repo, diff, previous_snapshot) -> tuple[OrchestratorStep, str]:
        try:
            from app.services.breaking_change import BreakingChangeService
            result = await BreakingChangeService(db, repo).analyze(
                previous_snapshot=previous_snapshot, diff=diff
            )
            text = result.summary
            return OrchestratorStep(
                agent="BreakingChangeService",
                status="completed",
                result_summary=result.summary,
                result=result.model_dump(),
            ), text
        except Exception as exc:
            return OrchestratorStep(agent="BreakingChangeService", status="failed", result_summary=str(exc)), str(exc)

    async def _run_sensitive_flow(self, db, repo) -> tuple[OrchestratorStep, str]:
        try:
            from app.services.sensitive_data_flow import SensitiveDataFlowService
            result = await SensitiveDataFlowService(db, repo).analyze()
            text = result.summary
            return OrchestratorStep(
                agent="SensitiveDataFlowService",
                status="completed",
                result_summary=result.summary,
                result=result.model_dump(),
            ), text
        except Exception as exc:
            return OrchestratorStep(agent="SensitiveDataFlowService", status="failed", result_summary=str(exc)), str(exc)

    async def _run_readiness(self, db, repo, security_response) -> tuple[OrchestratorStep, str]:
        try:
            from app.services.production_readiness import ProductionReadinessService
            result = await ProductionReadinessService(db, repo).analyze(
                security_response=security_response
            )
            text = f"**Production Readiness: {result.grade} ({result.overall_score}/100)**\n{result.summary}"
            return OrchestratorStep(
                agent="ProductionReadinessService",
                status="completed",
                result_summary=result.summary,
                result=result.model_dump(),
            ), text
        except Exception as exc:
            return OrchestratorStep(agent="ProductionReadinessService", status="failed", result_summary=str(exc)), str(exc)

    async def _run_code_health(self, db, repo) -> tuple[OrchestratorStep, str]:
        try:
            from app.services.code_health import CodeHealthService
            result = await CodeHealthService(db, repo).analyze()
            weakest = min(result.dimensions, key=lambda d: d.score) if result.dimensions else None
            detail = f" Weakest dimension: {weakest.name} ({weakest.score}/100)." if weakest else ""
            text = f"**Code Health: {result.grade} ({result.overall_score}/100)**\n{result.summary}{detail}"
            return OrchestratorStep(
                agent="CodeHealthService",
                status="completed",
                result_summary=result.summary,
                result=result.model_dump(),
            ), text
        except Exception as exc:
            return OrchestratorStep(agent="CodeHealthService", status="failed", result_summary=str(exc)), str(exc)

    async def _run_dependency_security(self, db, repo) -> tuple[OrchestratorStep, str]:
        try:
            from app.services.dependency_security import DependencySecurityService
            result = await DependencySecurityService(db, repo).analyze()
            text = f"**Dependency security:** {result.summary}"
            if result.risky_dependencies:
                worst = result.risky_dependencies[0]
                text += f"\n\nHighest risk: `{worst.package_name}` {worst.declared_version or ''} ({worst.cve}, {worst.severity})."
            return OrchestratorStep(
                agent="DependencySecurityService",
                status="completed",
                result_summary=result.summary,
                result=result.model_dump(),
            ), text
        except Exception as exc:
            return OrchestratorStep(agent="DependencySecurityService", status="failed", result_summary=str(exc)), str(exc)

    async def _run_onboarding(self, db, repo) -> tuple[OrchestratorStep, str]:
        try:
            from app.services.developer_knowledge import DeveloperKnowledgeService
            result = await DeveloperKnowledgeService(db, repo).onboarding()
            text = result.overview
            return OrchestratorStep(
                agent="DeveloperKnowledgeService",
                status="completed",
                result_summary=result.overview[:200],
                result=result.model_dump(),
            ), text
        except Exception as exc:
            return OrchestratorStep(agent="DeveloperKnowledgeService", status="failed", result_summary=str(exc)), str(exc)

    # ── LLM synthesis ──────────────────────────────────────────────────────────

    async def _synthesize(self, query: str, intent: str, raw: str) -> Optional[str]:
        system = (
            "You are a senior engineering assistant. "
            "Given a developer's question and analysis results, write a concise, "
            "accurate response (max 300 words). Use the analysis results only."
        )
        user = f"Question: {query}\n\nAnalysis results:\n{raw[:2000]}"
        try:
            result = await self.llm.generate(system, user, max_tokens=400, temperature=0.2)
            return result.strip() if result and len(result.strip()) > 20 else None
        except Exception:
            return None
