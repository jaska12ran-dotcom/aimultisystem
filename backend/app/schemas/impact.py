from typing import List, Optional

from pydantic import BaseModel, Field


class ImpactAnalysisRequest(BaseModel):
    symbol: Optional[str] = Field(default="", description="File path or symbol name/qualified name")
    file_path: Optional[str] = Field(default=None, description="Path of the modified file")
    changed_code: Optional[str] = Field(default=None, description="New or modified code content")
    diff: Optional[str] = Field(default=None, description="Git diff or patch text")


class ImpactEvidence(BaseModel):
    source: str
    file: str
    line: Optional[int] = None
    description: str


class ImpactComponent(BaseModel):
    symbol: str
    symbol_type: str
    file: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    relationship: str
    evidence: List[ImpactEvidence] = Field(default_factory=list)


class ImpactRisk(BaseModel):
    severity: str
    description: str
    evidence: List[ImpactEvidence] = Field(default_factory=list)


class ImpactGraphNode(BaseModel):
    id: str
    symbol: str
    file: str
    category: str
    line: Optional[int] = None


class ImpactGraphEdge(BaseModel):
    source: str
    target: str
    relationship: str
    evidence: ImpactEvidence


class ImpactAnalysisResponse(BaseModel):
    repository_id: str
    symbol: str
    affected_files: List[str] = Field(default_factory=list, description="Unique list of all files effected by this change")
    changed_symbols: List[str] = Field(default_factory=list, description="Symbols detected as modified in the code change")
    target: List[ImpactComponent] = Field(default_factory=list)
    direct_impact: List[ImpactComponent] = Field(default_factory=list)
    indirect_impact: List[ImpactComponent] = Field(default_factory=list)
    affected_apis: List[ImpactComponent] = Field(default_factory=list)
    affected_modules: List[ImpactComponent] = Field(default_factory=list)
    affected_tests: List[ImpactComponent] = Field(default_factory=list)
    potential_risks: List[ImpactRisk] = Field(default_factory=list)
    graph_nodes: List[ImpactGraphNode] = Field(default_factory=list)
    graph_edges: List[ImpactGraphEdge] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_reasons: List[str] = Field(default_factory=list)
    caveat: str = "This is a repository-evidence-based risk estimate, not a guarantee."
