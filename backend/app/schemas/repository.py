from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
import re

# ──────────────────────────────────────────────────────────────
# Request schemas
# ──────────────────────────────────────────────────────────────

class RepositoryCloneRequest(BaseModel):
    """POST /repositories/clone"""
    url: str = Field(..., description="GitHub / GitLab / Bitbucket HTTPS URL")
    branch: Optional[str] = Field(None, description="Branch to clone (default: repo default)")
    name: Optional[str] = Field(None, max_length=128, description="Custom display name")

    @field_validator("url")
    @classmethod
    def _url_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("url must not be empty")
        return v.strip()


class RepositoryLocalRequest(BaseModel):
    """POST /repositories/local  (dev/internal use)"""
    path: str = Field(..., description="Absolute path to a local repository folder")
    name: Optional[str] = Field(None, max_length=128, description="Custom display name")


# Keep backward-compatible aliases
RepositoryCreateGitHub = RepositoryCloneRequest
RepositoryCreateLocal = RepositoryLocalRequest


# ──────────────────────────────────────────────────────────────
# Language breakdown
# ──────────────────────────────────────────────────────────────

class LanguageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    language: str
    file_count: int
    line_count: int
    size_bytes: int
    percentage: float


# ──────────────────────────────────────────────────────────────
# Repository
# ──────────────────────────────────────────────────────────────

class ErrorLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    repository_id: str
    file_path: Optional[str] = None
    error_type: str
    error_message: str
    occurred_at: datetime
    stack_trace: Optional[str] = None
    context: Dict[str, Any] = {}
    resolved: bool
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None


class RepositoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = None
    source_type: str
    source_url: Optional[str] = None
    source_path: str
    default_branch: str
    file_count_by_language: Dict[str, Any] = {}
    total_files: int
    total_lines: int
    total_symbols: int
    total_size_bytes: int = 0
    status: str
    analysis_phase: str = "created"
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class RepositoryIndexStatusResponse(BaseModel):
    repository_id: str
    status: str
    last_started_at: Optional[datetime] = None
    last_successful_at: Optional[datetime] = None
    last_error: Optional[str] = None
    indexed_file_count: int = 0
    indexed_symbol_count: int = 0
    last_added_files: int = 0
    last_updated_files: int = 0
    last_deleted_files: int = 0
    last_unchanged_files: int = 0
    indexed_git_head: Optional[str] = None
    hours_since_last_analysis: Optional[float] = None
    indexing_health: Optional[str] = None


class RepositoryReindexResponse(RepositoryIndexStatusResponse):
    added_files: int = 0
    updated_files: int = 0
    deleted_files: int = 0
    unchanged_files: int = 0
    refreshed_relationship_files: int = 0
    refreshed_rag_files: int = 0


class RepositoryListResponse(BaseModel):
    items: List[RepositoryResponse]
    total: int


# ──────────────────────────────────────────────────────────────
# Files
# ──────────────────────────────────────────────────────────────

class FileItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    relative_path: str
    file_name: str
    file_extension: str
    language: str
    size_bytes: int
    line_count: int
    is_test: bool
    is_binary: bool
    is_config: bool = False
    is_documentation: bool = False


class FolderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    relative_path: str
    folder_name: str
    parent_path: Optional[str] = None
    depth: int = 0
    file_count: int
    total_size_bytes: int = 0


# ──────────────────────────────────────────────────────────────
# Directory Tree
# ──────────────────────────────────────────────────────────────

class TreeNode(BaseModel):
    """Recursive tree node for directory explorer."""
    name: str
    path: str
    type: str   # "file" | "directory"
    language: Optional[str] = None
    size_bytes: Optional[int] = None
    line_count: Optional[int] = None
    is_test: Optional[bool] = None
    is_config: Optional[bool] = None
    is_documentation: Optional[bool] = None
    children: Optional[List["TreeNode"]] = None


TreeNode.model_rebuild()   # Required for self-referential model


class DirectoryTreeResponse(BaseModel):
    repository_id: str
    repository_name: str
    tree: TreeNode
    total_files: int
    total_lines: int
    important_files: List[str] = []


# ──────────────────────────────────────────────────────────────
# Symbols
# ──────────────────────────────────────────────────────────────

class SymbolItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    file_id: str
    relative_path: Optional[str] = None
    name: str
    qualified_name: str
    symbol_type: str
    start_line: int
    end_line: int
    signature: str
    docstring: Optional[str] = None
    parameters: List[Any] = []
    return_type: Optional[str] = None
    complexity_score: int
    is_exported: bool


class ImportItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    file_id: str
    module_name: str
    imported_symbols: List[str] = []
    is_standard_lib: bool
    is_third_party: bool
    line_number: int


# ──────────────────────────────────────────────────────────────
# Dependencies
# ──────────────────────────────────────────────────────────────

class DependencyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    package_name: str
    version_spec: Optional[str] = None
    resolved_version: Optional[str] = None
    ecosystem: str
    is_dev: bool
    manifest_file: Optional[str] = None


# ──────────────────────────────────────────────────────────────
# Git
# ──────────────────────────────────────────────────────────────

class CommitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    commit_hash: str
    author_name: str
    author_email: str
    committed_at: datetime
    message: str
    files_changed: List[str] = []
    insertions: int
    deletions: int


# ──────────────────────────────────────────────────────────────
# Digital Twin Summary
# ──────────────────────────────────────────────────────────────

class RelationshipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_symbol_id: Optional[str] = None
    target_symbol_id: Optional[str] = None
    source_file_id: str
    target_file_id: Optional[str] = None
    relationship_type: str
    evidence_line: int
    evidence_text: Optional[str] = None


class DigitalTwinSummary(BaseModel):
    repository: RepositoryResponse
    total_files: int
    total_lines: int
    total_symbols: int
    total_relationships: int
    total_commits: int
    total_size_bytes: int = 0
    languages: List[LanguageResponse]
    symbol_types_breakdown: Dict[str, int]
    api_routes: List[SymbolItemResponse]
    db_models: List[SymbolItemResponse]
    recent_commits: List[CommitResponse]
    important_files: List[str] = []


# ──────────────────────────────────────────────────────────────
# File content (Monaco editor)
# ──────────────────────────────────────────────────────────────

class FileContentResponse(BaseModel):
    file_id: str
    relative_path: str
    language: str
    line_count: int
    content: str
    symbols: List[SymbolItemResponse]
    imports: List[ImportItemResponse]


class RepositoryRagIndexRequest(BaseModel):
    force: bool = False


class RepositoryRagSearchRequest(BaseModel):
    query: str
    limit: int = 5


class RepositoryRagAskRequest(BaseModel):
    question: str
    limit: int = 5


class RepositoryRagEvidence(BaseModel):
    file: str
    start_line: int
    end_line: int
    reason: str


class RepositoryRagAnswer(BaseModel):
    answer: str
    evidence: List[RepositoryRagEvidence] = []
    confidence: str


class RepositoryRagSearchResult(BaseModel):
    id: str
    repository_id: str
    file: str
    symbol: Optional[str] = None
    language: str
    start_line: int
    end_line: int
    content_type: str
    content: str
    score: float
