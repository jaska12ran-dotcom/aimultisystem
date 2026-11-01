"""
Pydantic schemas for the What-If Code Change Simulator.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Request ───────────────────────────────────────────────────────────────────

class WhatIfRequest(BaseModel):
    """User-supplied simulation request."""

    # Target selection (at least one required)
    file_path: Optional[str] = Field(
        default=None,
        description="Repository-relative path of the file to change.",
    )
    symbol: Optional[str] = Field(
        default=None,
        description="Qualified name of the function / class / API route to change.",
    )
    branch: Optional[str] = Field(
        default=None,
        description="Branch context (informational; no git checkout is performed).",
    )

    # Change description
    natural_language_description: str = Field(
        description="Plain-English description of the proposed change.",
    )

    # Optional explicit patch
    proposed_code: Optional[str] = Field(
        default=None,
        description="Proposed replacement source code (full file or relevant snippet).",
    )
    proposed_diff: Optional[str] = Field(
        default=None,
        description="Unified diff / patch representing the change.",
    )

    # Alternative proposals
    alternatives: Optional[List[str]] = Field(
        default=None,
        description="Alternative natural-language proposals to compare against the primary.",
    )

    # Analysis depth controls
    include_security: bool = True
    include_performance: bool = True
    include_migration: bool = True
    include_regression_tests: bool = True


# ── Evidence & findings shared types ─────────────────────────────────────────

class SourceLocation(BaseModel):
    file: str
    line: Optional[int] = None
    end_line: Optional[int] = None
    symbol: Optional[str] = None
    url: Optional[str] = None   # optional deep-link / file URI


class VerifiedFinding(BaseModel):
    """A finding backed by deterministic / AST-based analysis."""
    category: str
    severity: str   # critical | high | medium | low | info
    title: str
    detail: str
    method: str     # ast_analysis | import_graph | signature_diff | call_graph | …
    locations: List[SourceLocation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class PredictedFinding(BaseModel):
    """A finding produced by AI reasoning / heuristics — NOT deterministic."""
    category: str
    severity: str
    title: str
    detail: str
    assumption: str          # what the AI assumes to be true
    locations: List[SourceLocation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


# ── Structured result sub-sections ───────────────────────────────────────────

class AffectedFile(BaseModel):
    file: str
    reason: str
    relationship: str   # direct_import | call_graph | api_consumer | test | schema_dependent
    confidence: float = Field(ge=0.0, le=1.0)
    locations: List[SourceLocation] = Field(default_factory=list)


class ImpactedFunction(BaseModel):
    symbol: str
    file: str
    line: Optional[int] = None
    relationship: str   # calls | inherits | implements | imports | tests
    impact_type: str    # signature_break | behavioral | indirect | test_failure_risk
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[SourceLocation] = Field(default_factory=list)


class BreakingChangeEntry(BaseModel):
    symbol: str
    file: str
    line: Optional[int] = None
    category: str       # removed | renamed | signature | return_type | new_required_param
    severity: str       # critical | high | medium
    before: Optional[str] = None
    after: Optional[str] = None
    description: str
    verified: bool      # True = deterministic, False = AI-predicted


class TestFailureRisk(BaseModel):
    test_file: str
    test_function: Optional[str] = None
    line: Optional[int] = None
    risk_level: str     # high | medium | low
    reason: str
    verified: bool


class SecurityImplication(BaseModel):
    severity: str       # critical | high | medium | low
    category: str       # injection | auth | pii_exposure | timing | …
    description: str
    verified: bool
    locations: List[SourceLocation] = Field(default_factory=list)
    remediation: str = ""


class PerformanceConcern(BaseModel):
    severity: str       # high | medium | low
    category: str       # n_plus_1 | lock_contention | complexity | memory | io_blocking | …
    description: str
    verified: bool
    locations: List[SourceLocation] = Field(default_factory=list)


class MigrationRequirement(BaseModel):
    category: str       # db_schema | api_contract | config | dependency | data_transform
    severity: str
    description: str
    action_required: str
    locations: List[SourceLocation] = Field(default_factory=list)


class RegressionTestRecommendation(BaseModel):
    test_name: str
    description: str
    target_symbol: Optional[str] = None
    target_file: Optional[str] = None
    priority: str       # critical | high | medium | low
    rationale: str


class AlternativeProposal(BaseModel):
    description: str
    patch_hint: Optional[str] = None   # a minimal diff sketch
    tradeoffs: str
    estimated_risk: str   # low | medium | high


class WhatIfPatch(BaseModel):
    """The simulated patch in the isolated workspace (never merged)."""
    file_path: str
    original_snippet: Optional[str] = None
    proposed_snippet: Optional[str] = None
    unified_diff: Optional[str] = None
    rollback_diff: Optional[str] = None    # inverse diff to undo
    workspace_note: str = (
        "This patch was generated in an isolated simulation workspace. "
        "It has NOT been applied to the source repository."
    )


# ── Top-level response ────────────────────────────────────────────────────────

class WhatIfSimulationResult(BaseModel):
    repository_id: str
    simulation_id: str = ""          # UUID assigned at runtime
    target_file: Optional[str] = None
    target_symbol: Optional[str] = None
    branch_context: Optional[str] = None

    # The simulated patch (read-only; never merged)
    patch: Optional[WhatIfPatch] = None

    # --- Deterministic / verified analysis ---
    affected_files: List[AffectedFile] = Field(default_factory=list)
    impacted_functions: List[ImpactedFunction] = Field(default_factory=list)
    breaking_changes: List[BreakingChangeEntry] = Field(default_factory=list)
    test_failure_risks: List[TestFailureRisk] = Field(default_factory=list)

    # --- AI-predicted analysis ---
    security_implications: List[SecurityImplication] = Field(default_factory=list)
    performance_concerns: List[PerformanceConcern] = Field(default_factory=list)
    migration_requirements: List[MigrationRequirement] = Field(default_factory=list)
    regression_test_recommendations: List[RegressionTestRecommendation] = Field(default_factory=list)

    # --- Alternative proposals ---
    alternatives: List[AlternativeProposal] = Field(default_factory=list)

    # --- Meta ---
    overall_risk: str = "medium"        # low | medium | high | critical
    overall_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    verified_finding_count: int = 0
    predicted_finding_count: int = 0
    summary: str = ""
    assumptions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    simulation_note: str = (
        "This is a simulation only. No changes have been applied to the repository. "
        "Verified findings use deterministic AST/graph analysis. "
        "Predicted findings are AI-estimated and require human review."
    )
