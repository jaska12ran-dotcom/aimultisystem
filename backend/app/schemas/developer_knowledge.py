from typing import List, Optional

from pydantic import BaseModel, Field


class SourceReference(BaseModel):
    file: str
    line: Optional[int] = None
    description: str


class OnboardingStep(BaseModel):
    title: str
    level: str
    description: str
    references: List[SourceReference] = Field(default_factory=list)


class OnboardingResponse(BaseModel):
    repository_id: str
    overview: str
    entry_points: List[SourceReference] = Field(default_factory=list)
    important_modules: List[SourceReference] = Field(default_factory=list)
    guided_paths: List[OnboardingStep] = Field(default_factory=list)
    learning_tasks: List[OnboardingStep] = Field(default_factory=list)
    testing_instructions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class BusinessRule(BaseModel):
    rule_type: str
    description: str
    confidence: str
    explicit: bool
    source_evidence: List[SourceReference] = Field(default_factory=list)
    related_tests: List[SourceReference] = Field(default_factory=list)
    related_apis: List[SourceReference] = Field(default_factory=list)
    contradictions: List[str] = Field(default_factory=list)


class BusinessRuleResponse(BaseModel):
    repository_id: str
    rules: List[BusinessRule] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class CodeMemoryResponse(BaseModel):
    repository_id: str
    target: str
    matched_files: List[str] = Field(default_factory=list)
    history_available: bool
    commits: List[dict] = Field(default_factory=list)
    documentation_references: List[SourceReference] = Field(default_factory=list)
    summary: str
    limitations: List[str] = Field(default_factory=list)
