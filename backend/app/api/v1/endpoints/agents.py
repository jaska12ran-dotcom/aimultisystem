import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.database import get_db
from app.models.repository import Repository
from app.models.agent_artifact import GeneratedDoc, GeneratedTestSuite, AgentChatMessage
from app.schemas.agent import (
    DocGenerateRequest,
    DocResponse,
    TestPlanRequest,
    TestPlanResponse,
    TestGenerateRequest,
    TestSuiteResponse,
    TestExecuteResponse,
    TestPipelineRequest,
    TestPipelineResult,
    ChatRequest,
    ChatResponse,
    DocumentationVerificationResponse,
    DocumentationDriftResponse,
    SecurityAnalysisResponse,
    SecurityDashboard,
)
from app.schemas.test_intelligence import RegressionSelectionRequest, RegressionSelectionResponse, TestStrengthResponse
from app.schemas.technical_debt import TechnicalDebtResponse
from agents.documentation_agent import DocumentationAgent, DocumentationDriftDetector
from agents.security_agent import SecurityAgent
from agents.test_pipeline import TestGenerationPipeline
from app.services.test_intelligence import TestIntelligenceService
from app.services.technical_debt import TechnicalDebtService
from agents.test_agent import TestAgent
from agents.qa_agent import QAAgent
from intelligence.retriever import ASTRetriever
from sandbox.runner import sandbox_runner

router = APIRouter()

doc_agent = DocumentationAgent()
test_agent = TestAgent()
qa_agent = QAAgent()
security_agent = SecurityAgent()

# Helper
async def _get_repo_or_404(repo_id: str, db: AsyncSession) -> Repository:
    repo = await db.get(Repository, repo_id)
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repo_id} not found."
        )
    return repo


# ──────────────────────────────────────────────────────────────
# Documentation Endpoints
# ──────────────────────────────────────────────────────────────

@router.post("/{repo_id}/docs/generate", response_model=DocResponse, status_code=status.HTTP_201_CREATED)
async def generate_doc(
    repo_id: str,
    payload: DocGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    await _get_repo_or_404(repo_id, db)

    title, markdown, symbols, files = await doc_agent.generate_documentation(
        db=db,
        repo_id=repo_id,
        doc_type=payload.doc_type,
        title=payload.title,
        target_file=payload.target_file,
        custom_prompt=payload.custom_prompt,
    )

    doc_obj = GeneratedDoc(
        repository_id=repo_id,
        doc_type=payload.doc_type,
        title=title,
        content_markdown=markdown,
        grounded_symbols=symbols,
        grounded_files=files,
    )
    db.add(doc_obj)
    await db.commit()
    await db.refresh(doc_obj)

    return DocResponse.model_validate(doc_obj)


@router.get("/{repo_id}/docs", response_model=List[DocResponse])
async def list_docs(
    repo_id: str,
    limit: int = Query(50, le=100),
    db: AsyncSession = Depends(get_db),
):
    await _get_repo_or_404(repo_id, db)
    res = await db.execute(
        select(GeneratedDoc)
        .where(GeneratedDoc.repository_id == repo_id)
        .order_by(desc(GeneratedDoc.created_at))
        .limit(limit)
    )
    return [DocResponse.model_validate(d) for d in res.scalars().all()]


@router.get("/{repo_id}/docs/{doc_id}", response_model=DocResponse)
async def get_doc(
    repo_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
):
    await _get_repo_or_404(repo_id, db)
    doc_obj = await db.get(GeneratedDoc, doc_id)
    if not doc_obj or doc_obj.repository_id != repo_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocResponse.model_validate(doc_obj)


@router.post("/{repo_id}/docs/verify", response_model=DocumentationVerificationResponse)
async def verify_docs(
    repo_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    await _get_repo_or_404(repo_id, db)
    sections = payload.get("sections")
    if not sections:
        sections = await doc_agent.generate_repository_sections(db, repo_id)
    return await doc_agent.verify_documentation(db, repo_id, sections)


@router.post("/{repo_id}/docs/drift", response_model=DocumentationDriftResponse)
async def detect_docs_drift(
    repo_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    await _get_repo_or_404(repo_id, db)
    documentation = payload.get("existing_documentation") or payload.get("content") or ""
    return await DocumentationDriftDetector.detect_drift(db, repo_id, documentation)


# ──────────────────────────────────────────────────────────────
# Security Intelligence Endpoints
# ──────────────────────────────────────────────────────────────

@router.post("/{repo_id}/security/analyze", response_model=SecurityAnalysisResponse)
async def analyze_security(
    repo_id: str,
    db: AsyncSession = Depends(get_db),
):
    repo = await _get_repo_or_404(repo_id, db)
    response = await security_agent.analyze_repository(repo_id=repo_id, repo_path=repo.local_path)
    return response


@router.get("/{repo_id}/security/dashboard", response_model=SecurityDashboard)
async def get_security_dashboard(
    repo_id: str,
    db: AsyncSession = Depends(get_db),
):
    repo = await _get_repo_or_404(repo_id, db)
    response = await security_agent.analyze_repository(repo_id=repo_id, repo_path=repo.local_path)
    return response.dashboard


@router.get("/{repo_id}/technical-debt", response_model=TechnicalDebtResponse)
async def analyze_technical_debt(repo_id: str, db: AsyncSession = Depends(get_db)):
    repo = await _get_repo_or_404(repo_id, db)
    return await TechnicalDebtService(db, repo).analyze()


# ──────────────────────────────────────────────────────────────
# Test Generation & Sandbox Execution Endpoints
# ──────────────────────────────────────────────────────────────

@router.post("/{repo_id}/tests/plan", response_model=TestPlanResponse)
async def plan_tests_endpoint(
    repo_id: str,
    payload: TestPlanRequest,
    db: AsyncSession = Depends(get_db),
):
    await _get_repo_or_404(repo_id, db)
    file_ctx = await ASTRetriever.get_file_context(db, repo_id, payload.target_file)
    if not file_ctx:
        raise HTTPException(status_code=404, detail=f"Target file {payload.target_file} not found in repository")

    return await test_agent.plan_tests(
        file_ctx=file_ctx,
        target_symbol=payload.target_symbol,
        framework=payload.test_framework,
    )


@router.post("/{repo_id}/tests/generate", response_model=TestSuiteResponse, status_code=status.HTTP_201_CREATED)
async def generate_tests_endpoint(
    repo_id: str,
    payload: TestGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    repo = await _get_repo_or_404(repo_id, db)
    file_ctx = await ASTRetriever.get_file_context(db, repo_id, payload.target_file)
    if not file_ctx:
        raise HTTPException(status_code=404, detail=f"Target file {payload.target_file} not found in repository")

    test_code = await test_agent.generate_tests(
        file_ctx=file_ctx,
        target_symbol=payload.target_symbol,
        framework=payload.test_framework,
        custom_instructions=payload.custom_instructions,
    )

    test_file_name = f"test_{payload.target_file.replace('/', '_').replace('\\', '_')}"
    if not test_file_name.endswith(".py"):
        test_file_name += ".py"

    suite = GeneratedTestSuite(
        repository_id=repo_id,
        target_file=payload.target_file,
        target_symbol=payload.target_symbol,
        test_framework=payload.test_framework,
        test_file_path=test_file_name,
        test_code=test_code,
        status="pending",
    )
    db.add(suite)
    await db.commit()
    await db.refresh(suite)

    # Optional immediate execution
    if payload.execute_immediately:
        result = await sandbox_runner.execute_python_test(
            repo_workspace=repo.local_path,
            test_code=test_code,
            test_filename=test_file_name,
            framework=payload.test_framework,
        )
        suite.status = result.status
        suite.execution_output = result.execution_output
        suite.tests_run = result.tests_run
        suite.tests_passed = result.tests_passed
        suite.tests_failed = result.tests_failed
        suite.duration_ms = result.duration_ms
        suite.executed_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        await db.commit()
        await db.refresh(suite)

    return TestSuiteResponse.model_validate(suite)


@router.post("/{repo_id}/tests/pipeline", response_model=TestPipelineResult)
async def run_test_generation_pipeline(
    repo_id: str,
    payload: TestPipelineRequest,
    db: AsyncSession = Depends(get_db),
):
    await _get_repo_or_404(repo_id, db)
    pipeline = TestGenerationPipeline(db, repo_id)
    result = await pipeline.run(target_file=payload.target_file, framework=payload.framework, include_mutation=payload.include_mutation)
    return TestPipelineResult(
        repository_id=result["repository_id"],
        inspection=result["inspection"],
        plan=result["plan"],
        generated_tests=result["generated_tests"],
        verification=result["verification"],
        coverage=result["coverage"],
        mutation=result["mutation"],
        quality_score=result["quality_score"],
    )


@router.get("/{repo_id}/tests/strength", response_model=TestStrengthResponse)
async def analyze_test_strength(repo_id: str, db: AsyncSession = Depends(get_db)):
    repo = await _get_repo_or_404(repo_id, db)
    return await TestIntelligenceService(db, repo).analyze_strength()


@router.post("/{repo_id}/tests/select", response_model=RegressionSelectionResponse)
async def select_regression_tests(
    repo_id: str,
    payload: RegressionSelectionRequest,
    db: AsyncSession = Depends(get_db),
):
    repo = await _get_repo_or_404(repo_id, db)
    return await TestIntelligenceService(db, repo).select_regression_tests(
        payload.changed_files,
        payload.changed_symbols,
    )


@router.post("/{repo_id}/tests/{test_id}/execute", response_model=TestExecuteResponse)
async def execute_test_suite_endpoint(
    repo_id: str,
    test_id: str,
    db: AsyncSession = Depends(get_db),
):
    repo = await _get_repo_or_404(repo_id, db)
    suite = await db.get(GeneratedTestSuite, test_id)
    if not suite or suite.repository_id != repo_id:
        raise HTTPException(status_code=404, detail="Test suite not found")

    suite.status = "running"
    await db.commit()

    result = await sandbox_runner.execute_python_test(
        repo_workspace=repo.local_path,
        test_code=suite.test_code,
        test_filename=suite.test_file_path or "test_generated.py",
        framework=suite.test_framework,
    )

    suite.status = result.status
    suite.execution_output = result.execution_output
    suite.tests_run = result.tests_run
    suite.tests_passed = result.tests_passed
    suite.tests_failed = result.tests_failed
    suite.duration_ms = result.duration_ms
    suite.executed_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    await db.commit()

    return TestExecuteResponse(
        test_id=suite.id,
        status=result.status,
        execution_output=result.execution_output,
        tests_run=result.tests_run,
        tests_passed=result.tests_passed,
        tests_failed=result.tests_failed,
        duration_ms=result.duration_ms,
        success=result.success,
    )


@router.get("/{repo_id}/tests", response_model=List[TestSuiteResponse])
async def list_test_suites(
    repo_id: str,
    limit: int = Query(50, le=100),
    db: AsyncSession = Depends(get_db),
):
    await _get_repo_or_404(repo_id, db)
    res = await db.execute(
        select(GeneratedTestSuite)
        .where(GeneratedTestSuite.repository_id == repo_id)
        .order_by(desc(GeneratedTestSuite.created_at))
        .limit(limit)
    )
    return [TestSuiteResponse.model_validate(s) for s in res.scalars().all()]


# ──────────────────────────────────────────────────────────────
# Interactive Codebase Q&A Agent Endpoints
# ──────────────────────────────────────────────────────────────

@router.post("/{repo_id}/chat", response_model=ChatResponse)
async def chat_with_codebase(
    repo_id: str,
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    await _get_repo_or_404(repo_id, db)

    # Store user query in history
    user_msg = AgentChatMessage(
        repository_id=repo_id,
        role="user",
        content=payload.message,
    )
    db.add(user_msg)

    reply, citations, meta = await qa_agent.answer(
        db=db,
        repo_id=repo_id,
        question=payload.message,
        history=payload.history,
    )

    # Store assistant reply in history
    assistant_msg = AgentChatMessage(
        repository_id=repo_id,
        role="assistant",
        content=reply,
        citations=[c.model_dump() for c in citations],
    )
    db.add(assistant_msg)
    await db.commit()

    # Extract confidence from meta for the response
    confidence = meta.get("confidence", "medium") if meta else "medium"
    confidence_reasons = meta.get("reasoning", [f"{len(citations)} matching AST symbol definition(s) were retrieved from the indexed repository."] if citations else ["No AST symbol matches were retrieved for this question."]) if meta else (
        [f"{len(citations)} matching AST symbol definition(s) were retrieved from the indexed repository."] if citations else ["No AST symbol matches were retrieved for this question."]
    )

    return ChatResponse(
        reply=reply,
        citations=citations,
        confidence=confidence,
        confidence_reasons=confidence_reasons,
        limitations=(
            "Confidence describes the availability of matching indexed evidence, not factual validation of every generated claim. "
            "Dynamic behavior, omitted files, and unindexed content may be missing."
        ),
        agent_name="CodeTwin Repository Agent",
    )


# Additional imports needed for new endpoints
from app.schemas.agent import (
    SelfHealRequest, SelfHealResponse,
    TestFailureExplainRequest,
    BugInvestigateRequest, BugInvestigationResult,
    ProductionReadinessResult,
    PRDescribeRequest, PRDescribeResponse,
    BreakingChangeRequest, BreakingChangeResult,
    SensitiveDataFlowResult,
    OrchestratorRequest, OrchestratorResult, OrchestratorStepResponse,
)


# ──────────────────────────────────────────────────────────────
# Self-Healing Test Agent
# ──────────────────────────────────────────────────────────────

@router.post("/{repo_id}/tests/heal", response_model=SelfHealResponse)
async def heal_failing_tests(
    repo_id: str,
    payload: SelfHealRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Automatically diagnose and repair a failing test suite.

    Pass the original test code and the execution output (stderr/stdout) from
    a failed run.  The agent performs up to ``max_passes`` healing passes
    (import fix → signature fix → assertion fix) and returns the corrected code.
    """
    repo = await _get_repo_or_404(repo_id, db)
    from agents.self_healing_agent import SelfHealingAgent
    result = await SelfHealingAgent().heal(
        db=db,
        repo=repo,
        test_code=payload.test_code,
        execution_output=payload.execution_output,
        framework=payload.framework,
        max_passes=payload.max_passes,
    )
    return SelfHealResponse(**result)


# ──────────────────────────────────────────────────────────────
# Test Failure Explainer
# ──────────────────────────────────────────────────────────────

@router.post("/{repo_id}/tests/explain-failures")
async def explain_test_failures(
    repo_id: str,
    payload: TestFailureExplainRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Explain failing tests from raw pytest/unittest output.

    Deterministic parsing classifies each failure (assertion, import, syntax,
    timeout, fixture, collection, permission), cites traceback evidence, and
    maps failures back to indexed source symbols. No LLM or code execution
    is involved.
    """
    repo = await _get_repo_or_404(repo_id, db)
    from app.services.test_failure_explainer import TestFailureExplainerService
    return await TestFailureExplainerService(db, repo).explain(payload.execution_output)


# ──────────────────────────────────────────────────────────────
# AI Bug Detective
# ──────────────────────────────────────────────────────────────

@router.post("/{repo_id}/bugs/investigate", response_model=BugInvestigationResult)
async def investigate_bug(
    repo_id: str,
    payload: BugInvestigateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Investigate a bug report against the indexed repository.

    Provide a free-text bug description and (optionally) a stack trace.
    Returns ranked suspect locations, related commits, a root-cause hypothesis,
    and an optional minimal-reproducible-example sketch.
    """
    repo = await _get_repo_or_404(repo_id, db)
    from agents.bug_detective import BugDetectiveAgent
    result = await BugDetectiveAgent().investigate(
        db=db,
        repo=repo,
        bug_description=payload.bug_description,
        stack_trace=payload.stack_trace,
        generate_mre=payload.generate_mre,
    )
    return BugInvestigationResult(**result.dict())


# ──────────────────────────────────────────────────────────────
# Production Readiness Score
# ──────────────────────────────────────────────────────────────

@router.get("/{repo_id}/readiness", response_model=ProductionReadinessResult)
async def get_production_readiness(
    repo_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Compute a composite production-readiness score (0-100) with a letter grade.

    Aggregates: security (35%), test coverage (25%), technical debt (20%),
    documentation (10%), git stability (10%).
    """
    repo = await _get_repo_or_404(repo_id, db)
    from app.services.production_readiness import ProductionReadinessService
    result = await ProductionReadinessService(db, repo).analyze()
    return ProductionReadinessResult(**result.dict())


# ──────────────────────────────────────────────────────────────
# PR Description Generator
# ──────────────────────────────────────────────────────────────

@router.post("/{repo_id}/pr/describe", response_model=PRDescribeResponse)
async def generate_pr_description(
    repo_id: str,
    payload: PRDescribeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a structured pull-request description from changed files / diff.

    Returns a Markdown PR description including summary, what changed, risk level,
    testing guidance, and areas-to-review — grounded in repository evidence.
    """
    repo = await _get_repo_or_404(repo_id, db)
    from app.services.pr_description import PRDescriptionService
    result = await PRDescriptionService(db, repo).generate(
        changed_files=payload.changed_files or [],
        changed_symbols=payload.changed_symbols,
        diff=payload.diff,
        user_context=payload.user_context,
        branch_name=payload.branch_name,
    )
    return PRDescribeResponse(**result.dict())


# ──────────────────────────────────────────────────────────────
# API Breaking Change Detector
# ──────────────────────────────────────────────────────────────

@router.post("/{repo_id}/breaking-changes", response_model=BreakingChangeResult)
async def detect_breaking_changes(
    repo_id: str,
    payload: BreakingChangeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Detect breaking API changes between a previous symbol snapshot and the current index.

    Supply a ``previous_snapshot`` list (qualified_name, signature, return_type) to
    compare against the current indexed symbols, or supply a raw ``diff`` for heuristic
    analysis.  Returns breaking, compatible, and unknown-impact changes.
    """
    repo = await _get_repo_or_404(repo_id, db)
    from app.services.breaking_change import BreakingChangeService
    result = await BreakingChangeService(db, repo).analyze(
        previous_snapshot=payload.previous_snapshot,
        diff=payload.diff,
        focus_files=payload.focus_files,
    )
    return BreakingChangeResult(**result.dict())


# ──────────────────────────────────────────────────────────────
# Sensitive Data Flow Analyzer
# ──────────────────────────────────────────────────────────────

@router.get("/{repo_id}/security/data-flow", response_model=SensitiveDataFlowResult)
async def analyze_sensitive_data_flow(
    repo_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Perform taint-style sensitive data flow analysis over the indexed codebase.

    Identifies where sensitive data (passwords, PII, tokens) originates and
    whether it flows into risky sinks (logs, HTTP responses, file writes).
    All analysis is static — no code is executed.
    """
    repo = await _get_repo_or_404(repo_id, db)
    from app.services.sensitive_data_flow import SensitiveDataFlowService
    result = await SensitiveDataFlowService(db, repo).analyze()
    return SensitiveDataFlowResult(**result.dict())


# ──────────────────────────────────────────────────────────────
# General Orchestrator / Supervisor Agent
# ──────────────────────────────────────────────────────────────

@router.post("/{repo_id}/ask/orchestrate", response_model=OrchestratorResult)
async def orchestrate_developer_query(
    repo_id: str,
    payload: OrchestratorRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Route any developer question to the appropriate specialist agent.

    The orchestrator classifies your query (bug investigation, test analysis,
    security, impact, debt, history, PR description, etc.) and dispatches it
    to the right agent, returning a unified synthesised answer.

    Optional fields:
      - ``stack_trace``       — for bug investigation
      - ``changed_files``     — for impact / PR description
      - ``diff``              — for impact / breaking change / PR description
      - ``test_code`` + ``execution_output`` — for self-healing
      - ``previous_snapshot`` — for breaking change detection
    """
    repo = await _get_repo_or_404(repo_id, db)
    from agents.orchestrator import OrchestratorAgent
    result = await OrchestratorAgent().run(
        db=db,
        repo=repo,
        query=payload.query,
        stack_trace=payload.stack_trace,
        changed_files=payload.changed_files or [],
        diff=payload.diff,
        test_code=payload.test_code,
        execution_output=payload.execution_output,
        generate_mre=payload.generate_mre,
        previous_snapshot=payload.previous_snapshot,
    )
    return OrchestratorResult(
        repository_id=result.repository_id,
        intent=result.intent,
        steps=[
            OrchestratorStepResponse(
                agent=s.agent,
                status=s.status,
                result_summary=s.result_summary,
            )
            for s in result.steps
        ],
        answer=result.answer,
        confidence=result.confidence,
        limitations=result.limitations,
    )


# ──────────────────────────────────────────────────────────────
# Code Health Score (maintenance-focused composite)
# ──────────────────────────────────────────────────────────────

@router.get("/{repo_id}/code-health")
async def get_code_health(repo_id: str, db: AsyncSession = Depends(get_db)):
    """
    Compute a maintenance-focused code-health score (0-100) with a letter grade.

    Aggregates six deterministic dimensions: security posture, test coverage,
    documentation completeness, dependency risk, code structure, and git
    stability. Returns per-dimension findings, recommendations, top risks,
    and quick wins.
    """
    repo = await _get_repo_or_404(repo_id, db)
    from app.services.code_health import CodeHealthService
    return await CodeHealthService(db, repo).analyze()


# ──────────────────────────────────────────────────────────────
# Dependency Security Analyzer (offline advisory scan)
# ──────────────────────────────────────────────────────────────

@router.get("/{repo_id}/security/dependencies")
async def analyze_dependency_security(repo_id: str, db: AsyncSession = Depends(get_db)):
    """
    Scan declared dependencies against a curated offline advisory database.

    Deterministic and network-free: checks pip/npm package version ranges against
    known-vulnerable bounds (CVEs). Returns matched risks grouped by severity.
    """
    repo = await _get_repo_or_404(repo_id, db)
    from app.services.dependency_security import DependencySecurityService
    return await DependencySecurityService(db, repo).analyze()
