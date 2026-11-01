from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class DocGenerateRequest(BaseModel):
    doc_type: str = Field(default="architecture", description="architecture, api, models, module, readme, diagram, custom")
    title: Optional[str] = None
    target_file: Optional[str] = None
    custom_prompt: Optional[str] = None

class DocResponse(BaseModel):
    id: str
    repository_id: str
    doc_type: str
    title: str
    content_markdown: str
    grounded_symbols: List[str] = Field(default_factory=list)
    grounded_files: List[str] = Field(default_factory=list)
    created_at: datetime

    model_config = {"from_attributes": True}


class TestCasePlan(BaseModel):
    name: str
    description: str
    test_type: str = "unit" # unit, integration, edge_case, error_handling
    inputs: str
    expected_output: str

class TestPlanRequest(BaseModel):
    target_file: str
    target_symbol: Optional[str] = None
    test_framework: str = "pytest"

class TestPlanResponse(BaseModel):
    target_file: str
    target_symbol: Optional[str] = None
    test_framework: str
    planned_cases: List[TestCasePlan] = Field(default_factory=list)
    fixtures_needed: List[str] = Field(default_factory=list)
    rationale: str


class TestGenerateRequest(BaseModel):
    target_file: str
    target_symbol: Optional[str] = None
    test_framework: str = "pytest"
    custom_instructions: Optional[str] = None
    execute_immediately: bool = False

class TestSuiteResponse(BaseModel):
    id: str
    repository_id: str
    target_file: str
    target_symbol: Optional[str] = None
    test_framework: str
    test_file_path: Optional[str] = None
    test_code: str
    status: str
    execution_output: Optional[str] = None
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    duration_ms: float = 0.0
    executed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}

class TestExecuteResponse(BaseModel):
    test_id: str
    status: str # passed, failed, error
    execution_output: str
    tests_run: int
    tests_passed: int
    tests_failed: int
    duration_ms: float
    success: bool


class TestPipelineRequest(BaseModel):
    target_file: Optional[str] = None
    framework: str = "pytest"
    include_mutation: bool = False


class TestPipelineQualityScore(BaseModel):
    score: float
    pass_status: float
    coverage_delta: float
    mutation_score: float
    edge_case_score: float
    flaky_risk: float


class TestPipelineResult(BaseModel):
    repository_id: str
    inspection: Dict[str, Any] = Field(default_factory=dict)
    plan: Dict[str, Any] = Field(default_factory=dict)
    generated_tests: Dict[str, Any] = Field(default_factory=dict)
    verification: Dict[str, Any] = Field(default_factory=dict)
    coverage: Dict[str, Any] = Field(default_factory=dict)
    mutation: Dict[str, Any] = Field(default_factory=dict)
    quality_score: TestPipelineQualityScore


class CitationItem(BaseModel):
    file_path: str
    symbol_name: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    snippet: Optional[str] = None

class DocumentationEvidenceItem(BaseModel):
    file: str
    symbol: str
    start_line: int
    end_line: int
    reason: str
    source: str = "repository"

class DocumentationVerificationSection(BaseModel):
    title: str
    section_type: str
    content: Optional[str] = None
    evidence: List[DocumentationEvidenceItem] = Field(default_factory=list)
    confidence: str = "medium"
    unsupported_statements: List[str] = Field(default_factory=list)
    verified: bool = False

class DocumentationVerificationResponse(BaseModel):
    sections: List[DocumentationVerificationSection] = Field(default_factory=list)
    verified: bool = True

class DocumentationDriftIssue(BaseModel):
    issue_type: str
    severity: str
    title: str
    details: str
    evidence: Dict[str, Any] = Field(default_factory=dict)
    suggested_correction: Optional[str] = None

class DocumentationDriftResponse(BaseModel):
    has_drift: bool
    issues: List[DocumentationDriftIssue] = Field(default_factory=list)
    summary: str
    doc_was_not_overwritten: bool = True


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
    generated_at: datetime = Field(default_factory=datetime.now)


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[Dict[str, str]]] = Field(default_factory=list)

class ChatResponse(BaseModel):
    reply: str
    citations: List[CitationItem] = Field(default_factory=list)
    confidence: str = "low"
    confidence_reasons: List[str] = Field(default_factory=list)
    limitations: str = "Citations identify retrieved repository evidence; they do not verify every statement in the answer."
    agent_name: str = "CodeTwin Assistant"


# ── Self-Healing Test Agent ──────────────────────────────────────────────────

class SelfHealRequest(BaseModel):
    test_code: str
    execution_output: str
    framework: str = "pytest"
    max_passes: int = 3

class TestFailureExplainRequest(BaseModel):
    execution_output: str = Field(min_length=1, description="Raw pytest/unittest console output including tracebacks.")

class SelfHealPassResult(BaseModel):
    pass_num: int = Field(alias="pass")
    changes: List[str] = Field(default_factory=list)
    status: str
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    execution_output: Optional[str] = None

    model_config = {"populate_by_name": True}

class SelfHealResponse(BaseModel):
    healed_code: str
    passes_attempted: int
    success: bool
    diagnosis: str
    failure_categories: List[str] = Field(default_factory=list)
    pass_results: List[Dict[str, Any]] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


# ── Bug Detective Agent ──────────────────────────────────────────────────────

class BugInvestigateRequest(BaseModel):
    bug_description: str
    stack_trace: Optional[str] = None
    generate_mre: bool = False

class BugSuspectItem(BaseModel):
    file: str
    symbol: Optional[str] = None
    line: Optional[int] = None
    confidence: str = "medium"
    reason: str
    evidence_type: str

class BugInvestigationResult(BaseModel):
    repository_id: str
    query: str
    suspects: List[BugSuspectItem] = Field(default_factory=list)
    related_commits: List[Dict[str, Any]] = Field(default_factory=list)
    mre_sketch: Optional[str] = None
    root_cause_hypothesis: str = ""
    limitations: List[str] = Field(default_factory=list)


# ── Production Readiness Score ───────────────────────────────────────────────

class ReadinessDimensionResponse(BaseModel):
    name: str
    score: float
    weight: float
    grade: str
    findings: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)

class ProductionReadinessResult(BaseModel):
    repository_id: str
    overall_score: float
    grade: str
    dimensions: List[ReadinessDimensionResponse] = Field(default_factory=list)
    summary: str
    blockers: List[str] = Field(default_factory=list)
    quick_wins: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


# ── PR Description Generator ─────────────────────────────────────────────────

class PRDescribeRequest(BaseModel):
    changed_files: List[str] = Field(default_factory=list)
    changed_symbols: Optional[List[str]] = Field(default_factory=list)
    diff: Optional[str] = None
    user_context: Optional[str] = None
    branch_name: Optional[str] = None

class PRDescribeResponse(BaseModel):
    repository_id: str
    title: str
    description_markdown: str
    changed_symbols: List[str] = Field(default_factory=list)
    affected_files: List[str] = Field(default_factory=list)
    risk_level: str = "medium"
    suggested_reviewers_rationale: str = ""
    limitations: List[str] = Field(default_factory=list)


# ── API Breaking Change Detector ─────────────────────────────────────────────

class BreakingChangeRequest(BaseModel):
    previous_snapshot: Optional[List[Dict[str, Any]]] = None
    diff: Optional[str] = None
    focus_files: Optional[List[str]] = None

class BreakingChangeItemResponse(BaseModel):
    symbol: str
    file: str
    line: Optional[int] = None
    change_type: str
    category: str
    description: str
    before: Optional[str] = None
    after: Optional[str] = None
    severity: str = "high"

class BreakingChangeResult(BaseModel):
    repository_id: str
    breaking_changes: List[BreakingChangeItemResponse] = Field(default_factory=list)
    compatible_changes: List[BreakingChangeItemResponse] = Field(default_factory=list)
    unknown_changes: List[BreakingChangeItemResponse] = Field(default_factory=list)
    total_breaking: int = 0
    total_compatible: int = 0
    summary: str
    limitations: List[str] = Field(default_factory=list)


# ── Sensitive Data Flow Analyzer ─────────────────────────────────────────────

class DataFlowPathResponse(BaseModel):
    source_symbol: str
    source_file: str
    sink_symbol: str
    sink_file: str
    path_length: int
    severity: str
    risk_description: str
    path_symbols: List[str] = Field(default_factory=list)

class SensitiveDataFlowResult(BaseModel):
    repository_id: str
    source_count: int
    sink_count: int
    flow_paths: List[DataFlowPathResponse] = Field(default_factory=list)
    unprotected_sources: List[Dict[str, Any]] = Field(default_factory=list)
    summary: str
    limitations: List[str] = Field(default_factory=list)


# ── General Orchestrator ─────────────────────────────────────────────────────

class OrchestratorRequest(BaseModel):
    query: str
    stack_trace: Optional[str] = None
    changed_files: Optional[List[str]] = Field(default_factory=list)
    diff: Optional[str] = None
    test_code: Optional[str] = None
    execution_output: Optional[str] = None
    generate_mre: bool = False
    previous_snapshot: Optional[List[Dict[str, Any]]] = None

class OrchestratorStepResponse(BaseModel):
    agent: str
    status: str
    result_summary: str

class OrchestratorResult(BaseModel):
    repository_id: str
    intent: str
    steps: List[OrchestratorStepResponse] = Field(default_factory=list)
    answer: str
    confidence: str = "medium"
    limitations: List[str] = Field(default_factory=list)
