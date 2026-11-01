from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class RegressionSelectionRequest(BaseModel):
    changed_files: List[str] = Field(default_factory=list, max_length=50)
    changed_symbols: List[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def require_change_target(self):
        if not any(value.strip() for value in self.changed_files + self.changed_symbols):
            raise ValueError("Provide at least one changed file or symbol.")
        return self


class TestEvidence(BaseModel):
    source: str
    file: str
    line: Optional[int] = None
    description: str


class TestStrengthSymbol(BaseModel):
    symbol: str
    symbol_type: str
    file: str
    start_line: int
    end_line: int
    complexity: int
    mapping_status: str
    linked_tests: List[str] = Field(default_factory=list)
    candidate_tests: List[str] = Field(default_factory=list)
    branch_count: Optional[int] = None
    raise_count: Optional[int] = None
    potential_gaps: List[str] = Field(default_factory=list)
    evidence: List[TestEvidence] = Field(default_factory=list)


class TestStrengthResponse(BaseModel):
    repository_id: str
    test_file_count: int
    python_test_file_count: int
    discovered_test_function_count: int
    test_files_with_assertions: int
    test_files_without_assertions: int
    mapped_symbols: int
    analyzed_symbols: int
    symbols: List[TestStrengthSymbol] = Field(default_factory=list)
    findings: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class RegressionTestCandidate(BaseModel):
    file: str
    confidence: str
    reasons: List[str] = Field(default_factory=list)
    evidence: List[TestEvidence] = Field(default_factory=list)


class RegressionSelectionResponse(BaseModel):
    repository_id: str
    changed_files: List[str] = Field(default_factory=list)
    changed_symbols: List[str] = Field(default_factory=list)
    matched_symbols: List[str] = Field(default_factory=list)
    selected_tests: List[RegressionTestCandidate] = Field(default_factory=list)
    full_suite_recommended: bool
    recommendation_reasons: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
