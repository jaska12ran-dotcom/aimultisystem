"""
Digital Twin read endpoints
  GET /repositories/{id}/tree          — nested directory tree
  GET /repositories/{id}/summary       — full twin summary
  GET /repositories/{id}/files         — file list (with filters)
  GET /repositories/{id}/folders       — folder list
  GET /repositories/{id}/symbols       — code symbols
  GET /repositories/{id}/dependencies  — project dependencies
  GET /repositories/{id}/commits       — git history
  GET /repositories/{id}/relationships — code relationships
  GET /repositories/{id}/file-content  — single file content
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from app.core.database import get_db
from app.models.repository import (
    Repository,
    RepositoryIndexState,
    RepositoryFile,
    RepositoryLanguage,
    RepositoryDependency,
    CodeFolder,
    CodeSymbol,
    CodeImport,
    GitCommit,
    CodeRelationship,
)
from app.schemas.repository import (
    FileItemResponse,
    FolderItemResponse,
    LanguageResponse,
    SymbolItemResponse,
    ImportItemResponse,
    DependencyResponse,
    CommitResponse,
    RelationshipResponse,
    DigitalTwinSummary,
    FileContentResponse,
    RepositoryResponse,
    DirectoryTreeResponse,
    TreeNode,
    RepositoryRagAnswer,
    RepositoryRagAskRequest,
    RepositoryRagSearchRequest,
    RepositoryRagSearchResult,
    RepositoryIndexStatusResponse,
    RepositoryReindexResponse,
)
from app.schemas.impact import ImpactAnalysisRequest, ImpactAnalysisResponse
from app.schemas.git_history import GitHistoryAnalysis, WhyCodeRequest, WhyCodeResponse
from app.schemas.developer_knowledge import BusinessRuleResponse, CodeMemoryResponse, OnboardingResponse
from app.services.graph.service import CodeKnowledgeGraphService
from app.services.change_impact import ChangeImpactService
from app.services.git_history import GitHistoryService
from app.services.developer_knowledge import DeveloperKnowledgeService
from app.services.rag.service import RepositoryIndexer, RepositoryRetriever, VectorSearchService
from app.services.twin.incremental import RepositoryIndexBusyError, RepositoryReindexer
from intelligence.parser import analyze_repository

router = APIRouter()


from datetime import datetime, timezone, timedelta


def _compute_indexing_health(last_successful_at: Optional[datetime]) -> tuple[Optional[float], Optional[str]]:
    """Compute hours since last analysis and health badge.

    Health bands:
      fresh  — within 24 hours
      stale  — within 7 days
      old    — within 30 days
      never  — no successful analysis
    """
    if not last_successful_at:
        return None, "never"
    now = datetime.now(timezone.utc)
    delta = now - last_successful_at.replace(tzinfo=timezone.utc) if last_successful_at.tzinfo is None else now - last_successful_at
    hours = delta.total_seconds() / 3600.0
    if hours <= 24:
        return hours, "fresh"
    if hours <= 7 * 24:
        return hours, "stale"
    if hours <= 30 * 24:
        return hours, "old"
    return hours, "never"


@router.get("/{repo_id}/index-status", response_model=RepositoryIndexStatusResponse)
async def get_repository_index_status(repo_id: str, db: AsyncSession = Depends(get_db)):
    await _get_or_404(repo_id, db)
    state = await db.get(RepositoryIndexState, repo_id)
    if state is None:
        return RepositoryIndexStatusResponse(repository_id=repo_id, status="not_indexed")
    hours, health = _compute_indexing_health(state.last_successful_at)
    return RepositoryIndexStatusResponse(
        repository_id=repo_id,
        status=state.status,
        last_started_at=state.last_started_at,
        last_successful_at=state.last_successful_at,
        last_error=state.last_error,
        indexed_file_count=state.indexed_file_count,
        indexed_symbol_count=state.indexed_symbol_count,
        last_added_files=state.last_added_files,
        last_updated_files=state.last_updated_files,
        last_deleted_files=state.last_deleted_files,
        last_unchanged_files=state.last_unchanged_files,
        indexed_git_head=state.indexed_git_head,
        hours_since_last_analysis=hours,
        indexing_health=health,
    )


@router.post("/{repo_id}/reindex", response_model=RepositoryReindexResponse)
async def reindex_repository(repo_id: str, db: AsyncSession = Depends(get_db)):
    await _get_or_404(repo_id, db)
    try:
        result = await RepositoryReindexer(db, repo_id).reindex()
    except RepositoryIndexBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RepositoryReindexResponse(**result)


# ──────────────────────────────────────────────────────────────
# Directory tree
# ──────────────────────────────────────────────────────────────

@router.get("/{repo_id}/tree", response_model=DirectoryTreeResponse)
async def get_directory_tree(repo_id: str, db: AsyncSession = Depends(get_db)):
    """
    Returns the full nested directory tree for the file explorer.
    Built from the persisted file/folder records — no disk access.
    """
    repo = await _get_or_404(repo_id, db)

    # Load all files and folders
    files_res = await db.execute(
        select(RepositoryFile).where(RepositoryFile.repository_id == repo_id)
    )
    files = files_res.scalars().all()

    folders_res = await db.execute(
        select(CodeFolder).where(CodeFolder.repository_id == repo_id).order_by(CodeFolder.relative_path.asc())
    )
    folders = folders_res.scalars().all()

    # Derive important files from is_documentation / is_config
    important = sorted(
        f.relative_path for f in files if f.is_documentation or f.is_config
    )

    # Build tree
    tree = _build_tree(repo.name, files, folders)

    return DirectoryTreeResponse(
        repository_id=repo_id,
        repository_name=repo.name,
        tree=tree,
        total_files=repo.total_files,
        total_lines=repo.total_lines,
        important_files=important,
    )


def _build_tree(
    repo_name: str,
    files: list,
    folders: list,
) -> TreeNode:
    """Constructs a nested TreeNode from flat file/folder records."""
    # Map folder path → list of child folder paths
    folder_children: Dict[str, List[Any]] = {"": []}
    for fd in folders:
        parent = fd.parent_path or ""
        folder_children.setdefault(parent, []).append(fd)
        folder_children.setdefault(fd.relative_path, [])

    # Map folder path → list of files
    file_children: Dict[str, List[Any]] = {"": []}
    for f in files:
        parent = "/".join(f.relative_path.split("/")[:-1])
        file_children.setdefault(parent, []).append(f)

    def _node(path: str, name: str) -> TreeNode:
        child_dirs = sorted(folder_children.get(path, []), key=lambda x: x.folder_name)
        child_files = sorted(file_children.get(path, []), key=lambda x: x.file_name)
        children = [_node(cd.relative_path, cd.folder_name) for cd in child_dirs] + [
            TreeNode(
                name=f.file_name,
                path=f.relative_path,
                type="file",
                language=f.language,
                size_bytes=f.size_bytes,
                line_count=f.line_count,
                is_test=f.is_test,
                is_config=f.is_config,
                is_documentation=f.is_documentation,
                children=None,
            )
            for f in child_files
        ]
        return TreeNode(name=name, path=path or ".", type="directory", children=children)

    return _node("", repo_name)


# ──────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────

@router.get("/{repo_id}/summary", response_model=DigitalTwinSummary)
async def get_digital_twin_summary(repo_id: str, db: AsyncSession = Depends(get_db)):
    repo = await _get_or_404(repo_id, db)

    files_count = await db.scalar(
        select(func.count(RepositoryFile.id)).where(RepositoryFile.repository_id == repo_id)
    ) or 0
    symbols_count = await db.scalar(
        select(func.count(CodeSymbol.id)).where(CodeSymbol.repository_id == repo_id)
    ) or 0
    rel_count = await db.scalar(
        select(func.count(CodeRelationship.id)).where(CodeRelationship.repository_id == repo_id)
    ) or 0
    commits_count = await db.scalar(
        select(func.count(GitCommit.id)).where(GitCommit.repository_id == repo_id)
    ) or 0

    sym_types_res = await db.execute(
        select(CodeSymbol.symbol_type, func.count(CodeSymbol.id))
        .where(CodeSymbol.repository_id == repo_id)
        .group_by(CodeSymbol.symbol_type)
    )
    symbol_breakdown = {row[0]: row[1] for row in sym_types_res.all()}

    api_routes_res = await db.execute(
        select(CodeSymbol)
        .where(CodeSymbol.repository_id == repo_id, CodeSymbol.symbol_type == "api_route")
        .limit(20)
    )
    db_models_res = await db.execute(
        select(CodeSymbol)
        .where(CodeSymbol.repository_id == repo_id, CodeSymbol.symbol_type == "db_model")
        .limit(20)
    )
    commits_res = await db.execute(
        select(GitCommit)
        .where(GitCommit.repository_id == repo_id)
        .order_by(GitCommit.committed_at.desc())
        .limit(10)
    )

    # Language details from RepositoryLanguage table
    lang_res = await db.execute(
        select(RepositoryLanguage)
        .where(RepositoryLanguage.repository_id == repo_id)
        .order_by(RepositoryLanguage.percentage.desc())
    )
    languages = lang_res.scalars().all()

    return DigitalTwinSummary(
        repository=RepositoryResponse.model_validate(repo),
        total_files=files_count,
        total_lines=repo.total_lines,
        total_symbols=symbols_count,
        total_relationships=rel_count,
        total_commits=commits_count,
        total_size_bytes=repo.total_size_bytes or 0,
        languages=[LanguageResponse.model_validate(l) for l in languages],
        symbol_types_breakdown=symbol_breakdown,
        api_routes=[SymbolItemResponse.model_validate(s) for s in api_routes_res.scalars().all()],
        db_models=[SymbolItemResponse.model_validate(s) for s in db_models_res.scalars().all()],
        recent_commits=[CommitResponse.model_validate(c) for c in commits_res.scalars().all()],
    )


@router.post("/{repo_id}/analyze", response_model=Dict[str, Any])
async def analyze_repository_endpoint(
    repo_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Run static repository analysis and return normalized file/symbol/dependency data."""
    repo = await _get_or_404(repo_id, db)
    local_path = Path(repo.local_path)
    if not local_path.exists():
        raise HTTPException(status_code=404, detail="Repository source path not found on disk")

    analysis = analyze_repository(repo_id, str(local_path))
    repo.status = "ready"
    repo.analysis_phase = "analyzed"
    repo.total_files = analysis.get("total_files", 0)
    repo.total_symbols = analysis.get("symbol_count", 0)
    repo.total_lines = max(repo.total_lines, sum(
        len(str(item.get("content", "")).splitlines()) for item in analysis.get("files", []) if isinstance(item, dict)
    ))
    await db.commit()
    return analysis


@router.get("/{repo_id}/graph", response_model=Dict[str, Any])
async def get_repository_graph(repo_id: str, db: AsyncSession = Depends(get_db)):
    await _get_or_404(repo_id, db)
    service = CodeKnowledgeGraphService(repo_id, db)
    graph = await service.build_repository_graph()
    return {
        "repository_id": repo_id,
        "nodes": [node for node in graph.get("nodes", [])],
        "relationships": [rel for rel in graph.get("relationships", [])],
        "counts": {
            "nodes": len(graph.get("nodes", [])),
            "relationships": len(graph.get("relationships", [])),
        },
    }


@router.get("/{repo_id}/symbols/{symbol}/relationships", response_model=List[Dict[str, Any]])
async def get_symbol_relationships(repo_id: str, symbol: str, db: AsyncSession = Depends(get_db)):
    await _get_or_404(repo_id, db)
    service = CodeKnowledgeGraphService(repo_id, db)
    await service.build_repository_graph()
    return service.find_symbol_relationships(symbol)


@router.get("/{repo_id}/symbols/{symbol}/callers", response_model=List[Dict[str, Any]])
async def get_symbol_callers(repo_id: str, symbol: str, db: AsyncSession = Depends(get_db)):
    await _get_or_404(repo_id, db)
    service = CodeKnowledgeGraphService(repo_id, db)
    await service.build_repository_graph()
    return service.find_symbol_callers(symbol)


@router.get("/{repo_id}/symbols/{symbol}/dependents", response_model=List[Dict[str, Any]])
async def get_symbol_dependents(repo_id: str, symbol: str, db: AsyncSession = Depends(get_db)):
    await _get_or_404(repo_id, db)
    service = CodeKnowledgeGraphService(repo_id, db)
    await service.build_repository_graph()
    return service.find_symbol_dependents(symbol)


@router.post("/{repo_id}/index", response_model=Dict[str, Any])
async def index_repository_for_rag(repo_id: str, db: AsyncSession = Depends(get_db)):
    await _get_or_404(repo_id, db)
    indexer = RepositoryIndexer(db, repo_id)
    count = await indexer.index_repository()
    return {"repository_id": repo_id, "indexed_chunks": count, "status": "indexed"}


@router.post("/{repo_id}/search", response_model=List[RepositoryRagSearchResult])
async def search_repository_index(repo_id: str, payload: RepositoryRagSearchRequest, db: AsyncSession = Depends(get_db)):
    await _get_or_404(repo_id, db)
    service = VectorSearchService(db, repo_id)
    results = await service.search(payload.query, limit=payload.limit)
    return [RepositoryRagSearchResult(**item) for item in results]


@router.post("/{repo_id}/ask", response_model=RepositoryRagAnswer)
async def ask_repository_question(repo_id: str, payload: RepositoryRagAskRequest, db: AsyncSession = Depends(get_db)):
    await _get_or_404(repo_id, db)
    retriever = RepositoryRetriever(db, repo_id)
    answer = await retriever.answer_question(payload.question)
    return RepositoryRagAnswer(**answer)


@router.post("/{repo_id}/impact-analysis", response_model=ImpactAnalysisResponse)
async def analyze_change_impact(
    repo_id: str,
    payload: ImpactAnalysisRequest,
    db: AsyncSession = Depends(get_db),
):
    repo = await _get_or_404(repo_id, db)
    query = payload.symbol or payload.file_path or ""
    return await ChangeImpactService(db, repo).analyze(
        query=query,
        file_path=payload.file_path,
        changed_code=payload.changed_code,
        diff=payload.diff,
    )


# ──────────────────────────────────────────────────────────────
# Files
# ──────────────────────────────────────────────────────────────

@router.get("/{repo_id}/files", response_model=List[FileItemResponse])
async def list_repository_files(
    repo_id: str,
    language: Optional[str] = None,
    is_test: Optional[bool] = None,
    is_config: Optional[bool] = None,
    limit: int = Query(500, le=2000),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    query = select(RepositoryFile).where(RepositoryFile.repository_id == repo_id)
    if language:
        query = query.where(RepositoryFile.language == language.lower())
    if is_test is not None:
        query = query.where(RepositoryFile.is_test == is_test)
    if is_config is not None:
        query = query.where(RepositoryFile.is_config == is_config)
    query = query.order_by(RepositoryFile.relative_path.asc()).offset(offset).limit(limit)
    res = await db.execute(query)
    return res.scalars().all()


# ──────────────────────────────────────────────────────────────
# Folders
# ──────────────────────────────────────────────────────────────

@router.get("/{repo_id}/folders", response_model=List[FolderItemResponse])
async def list_repository_folders(repo_id: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(CodeFolder)
        .where(CodeFolder.repository_id == repo_id)
        .order_by(CodeFolder.relative_path.asc())
    )
    return res.scalars().all()


# ──────────────────────────────────────────────────────────────
# Symbols
# ──────────────────────────────────────────────────────────────

@router.get("/{repo_id}/symbols", response_model=List[SymbolItemResponse])
async def list_repository_symbols(
    repo_id: str,
    symbol_type: Optional[str] = None,
    query_str: Optional[str] = None,
    limit: int = Query(200, le=2000),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(CodeSymbol, RepositoryFile.relative_path)
        .join(RepositoryFile, CodeSymbol.file_id == RepositoryFile.id)
        .where(CodeSymbol.repository_id == repo_id)
    )
    if symbol_type:
        stmt = stmt.where(CodeSymbol.symbol_type == symbol_type)
    if query_str:
        stmt = stmt.where(CodeSymbol.name.ilike(f"%{query_str}%"))

    stmt = stmt.order_by(CodeSymbol.name.asc()).offset(offset).limit(limit)
    res = await db.execute(stmt)

    output = []
    for sym, rel_path in res.all():
        d = SymbolItemResponse.model_validate(sym).model_dump()
        d["relative_path"] = rel_path
        output.append(SymbolItemResponse(**d))
    return output


# ──────────────────────────────────────────────────────────────
# Dependencies
# ──────────────────────────────────────────────────────────────

@router.get("/{repo_id}/dependencies", response_model=List[DependencyResponse])
async def list_repository_dependencies(
    repo_id: str,
    ecosystem: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(RepositoryDependency).where(RepositoryDependency.repository_id == repo_id)
    if ecosystem:
        stmt = stmt.where(RepositoryDependency.ecosystem == ecosystem.lower())
    stmt = stmt.order_by(RepositoryDependency.package_name.asc())
    res = await db.execute(stmt)
    return res.scalars().all()


# ──────────────────────────────────────────────────────────────
# Git commits
# ──────────────────────────────────────────────────────────────

@router.get("/{repo_id}/commits", response_model=List[CommitResponse])
async def list_repository_commits(
    repo_id: str,
    limit: int = Query(50, le=500),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(GitCommit)
        .where(GitCommit.repository_id == repo_id)
        .order_by(GitCommit.committed_at.desc())
        .limit(limit)
    )
    return res.scalars().all()


@router.get("/{repo_id}/history-analysis", response_model=GitHistoryAnalysis)
async def analyze_repository_history(
    repo_id: str,
    limit: int = Query(500, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    repo = await _get_or_404(repo_id, db)
    return await GitHistoryService(db, repo).analyze(limit=limit)


@router.post("/{repo_id}/history/why", response_model=WhyCodeResponse)
async def explain_code_from_history(
    repo_id: str,
    payload: WhyCodeRequest,
    db: AsyncSession = Depends(get_db),
):
    repo = await _get_or_404(repo_id, db)
    return await GitHistoryService(db, repo).why_code_exists(
        payload.target,
        limit=payload.limit,
    )


@router.get("/{repo_id}/onboarding", response_model=OnboardingResponse)
async def get_repository_onboarding(repo_id: str, db: AsyncSession = Depends(get_db)):
    repo = await _get_or_404(repo_id, db)
    return await DeveloperKnowledgeService(db, repo).onboarding()


@router.get("/{repo_id}/business-rules", response_model=BusinessRuleResponse)
async def get_business_rules(repo_id: str, db: AsyncSession = Depends(get_db)):
    repo = await _get_or_404(repo_id, db)
    return await DeveloperKnowledgeService(db, repo).business_rules()


@router.get("/{repo_id}/code-memory", response_model=CodeMemoryResponse)
async def get_code_memory(
    repo_id: str,
    target: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    repo = await _get_or_404(repo_id, db)
    return await DeveloperKnowledgeService(db, repo).code_memory(target)


# ──────────────────────────────────────────────────────────────
# Relationships
# ──────────────────────────────────────────────────────────────

@router.get("/{repo_id}/relationships", response_model=List[RelationshipResponse])
async def list_repository_relationships(
    repo_id: str,
    limit: int = Query(200, le=2000),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(CodeRelationship).where(CodeRelationship.repository_id == repo_id).limit(limit)
    )
    return res.scalars().all()


# ──────────────────────────────────────────────────────────────
# File content
# ──────────────────────────────────────────────────────────────

@router.get("/{repo_id}/file-content", response_model=FileContentResponse)
async def get_file_content(
    repo_id: str,
    path: str = Query(..., description="Relative path of file inside repository"),
    db: AsyncSession = Depends(get_db),
):
    repo = await _get_or_404(repo_id, db)

    normalized = path.replace("\\", "/").lstrip("/")

    file_res = await db.execute(
        select(RepositoryFile).where(
            RepositoryFile.repository_id == repo_id,
            RepositoryFile.relative_path == normalized,
        )
    )
    file_obj = file_res.scalar_one_or_none()
    if not file_obj:
        raise HTTPException(status_code=404, detail="File not found in repository twin")

    full_path = Path(repo.local_path) / normalized
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    # Security: ensure path stays inside local_path
    try:
        full_path.resolve().relative_to(Path(repo.local_path).resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Path traversal attempt detected")

    try:
        content = full_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {exc}")

    symbols_res = await db.execute(
        select(CodeSymbol).where(CodeSymbol.file_id == file_obj.id).order_by(CodeSymbol.start_line.asc())
    )
    imports_res = await db.execute(
        select(CodeImport).where(CodeImport.file_id == file_obj.id).order_by(CodeImport.line_number.asc())
    )

    return FileContentResponse(
        file_id=file_obj.id,
        relative_path=file_obj.relative_path,
        language=file_obj.language,
        line_count=file_obj.line_count,
        content=content,
        symbols=[SymbolItemResponse.model_validate(s) for s in symbols_res.scalars().all()],
        imports=[ImportItemResponse.model_validate(i) for i in imports_res.scalars().all()],
    )


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

async def _get_or_404(repo_id: str, db: AsyncSession) -> Repository:
    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo
