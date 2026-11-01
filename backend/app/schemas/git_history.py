from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class GitHistoryEvidence(BaseModel):
    commit_hash: str
    message: str
    author: str
    timestamp: datetime
    files_changed: List[str] = Field(default_factory=list)
    relevance: str


class GitFileHistory(BaseModel):
    file: str
    change_frequency: int
    insertions: int
    deletions: int
    churn: int
    last_modified: Optional[datetime] = None
    recent_commit_count: int = 0
    is_hotspot: bool = False
    hotspot_risk: str = "low"
    abandoned_area_candidate: bool = False
    critical_component: bool = False
    recently_modified_critical: bool = False
    evidence: List[GitHistoryEvidence] = Field(default_factory=list)


class GitHistoryAnalysis(BaseModel):
    repository_id: str
    history_available: bool
    history_scope: str
    commits_analyzed: int
    branches: List[str] = Field(default_factory=list)
    branch_history_available: bool = False
    files: List[GitFileHistory] = Field(default_factory=list)
    frequently_changed_files: List[GitFileHistory] = Field(default_factory=list)
    unstable_modules: List[str] = Field(default_factory=list)
    high_risk_hotspots: List[GitFileHistory] = Field(default_factory=list)
    abandoned_area_candidates: List[GitFileHistory] = Field(default_factory=list)
    recently_modified_critical_components: List[GitFileHistory] = Field(default_factory=list)
    summary: str


class WhyCodeRequest(BaseModel):
    target: str = Field(min_length=1, description="Repository-relative file or indexed symbol")
    limit: int = Field(default=10, ge=1, le=50)


class WhyCodeResponse(BaseModel):
    repository_id: str
    target: str
    answer: str
    sufficient_history: bool
    evidence: List[GitHistoryEvidence] = Field(default_factory=list)
    limitation: str
