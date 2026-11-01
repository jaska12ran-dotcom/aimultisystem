from typing import List, Optional

from pydantic import BaseModel, Field


class DebtEvidence(BaseModel):
    source: str
    file: str
    line: Optional[int] = None
    description: str


class TechnicalDebtFinding(BaseModel):
    category: str
    severity: str
    title: str
    details: str
    confidence: str
    estimated_effort: str
    affected_components: List[str] = Field(default_factory=list)
    evidence: List[DebtEvidence] = Field(default_factory=list)
    remediation: str
    measured: bool


class TechnicalDebtResponse(BaseModel):
    repository_id: str
    findings: List[TechnicalDebtFinding] = Field(default_factory=list)
    summary: str
    limitations: List[str] = Field(default_factory=list)
