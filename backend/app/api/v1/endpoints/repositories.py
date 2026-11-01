"""
Repository REST endpoints
  POST /repositories/upload   — ZIP file upload
  POST /repositories/clone    — GitHub URL clone
  POST /repositories/local    — local path (dev)
  GET  /repositories          — list
  GET  /repositories/{id}     — detail
  DELETE /repositories/{id}   — delete
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.repository import Repository
from app.schemas.repository import (
    ErrorLogResponse,
    RepositoryCloneRequest,
    RepositoryLocalRequest,
    RepositoryResponse,
)
from app.services.ingestion import IngestionService, ValidationError, ArchiveExtractionError

router = APIRouter()


# ──────────────────────────────────────────────────────────────
# Read endpoints
# ──────────────────────────────────────────────────────────────

@router.get("", response_model=List[RepositoryResponse])
async def list_repositories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Repository).order_by(Repository.created_at.desc()))
    return result.scalars().all()


@router.get("/{repo_id}", response_model=RepositoryResponse)
async def get_repository(repo_id: str, db: AsyncSession = Depends(get_db)):
    repo = await _get_or_404(repo_id, db)
    return repo


# ──────────────────────────────────────────────────────────────
# Ingestion endpoints
# ──────────────────────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=RepositoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a ZIP archive of a repository",
)
async def upload_zip_repository(
    file: UploadFile = File(..., description="ZIP archive of the repository"),
    db: AsyncSession = Depends(get_db),
):
    """
    Accept a .zip archive, validate it against security rules (Zip-Slip,
    Zip-Bomb, path traversal), extract it, scan its contents, and build the
    Software Digital Twin.
    """
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=400,
            detail="Only .zip archives are accepted. Please upload a .zip file.",
        )

    # Stream to a temporary file first so we can check the size without loading into RAM
    temp_zip = Path(settings.UPLOADS_DIR) / f"tmp_{file.filename}"
    try:
        with open(temp_zip, "wb") as buf:
            shutil.copyfileobj(file.file, buf)

        svc = IngestionService(db)
        repo = await svc.ingest_from_zip(str(temp_zip), original_filename=file.filename)
        return repo

    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ArchiveExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Upload processing failed: {exc}")
    finally:
        if temp_zip.exists():
            try:
                temp_zip.unlink()
            except Exception:
                pass


@router.post(
    "/clone",
    response_model=RepositoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Clone a GitHub / GitLab / Bitbucket repository",
)
async def clone_repository(
    data: RepositoryCloneRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Clone a remote Git repository (GitHub, GitLab, Bitbucket only).
    URL is validated against an allowlist before any network call.
    Code is never executed during ingestion.
    """
    svc = IngestionService(db)
    try:
        repo = await svc.ingest_from_github(data.url, branch=data.branch, name=data.name)
        return repo
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to clone repository: {exc}",
        )


@router.post(
    "/local",
    response_model=RepositoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a local repository folder (development)",
)
async def ingest_local_repository(
    data: RepositoryLocalRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Scan a local directory that already exists on this machine.
    The directory is validated for existence and path confinement.
    """
    svc = IngestionService(db)
    try:
        repo = await svc.ingest_from_local(data.path, name=data.name)
        return repo
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to ingest local repository: {exc}",
        )


# ──────────────────────────────────────────────────────────────
# Delete
# ──────────────────────────────────────────────────────────────

@router.delete("/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_repository(repo_id: str, db: AsyncSession = Depends(get_db)):
    repo = await _get_or_404(repo_id, db)

    # Only delete workspace if it lives inside our managed REPOS_DIR
    managed_root = str(Path(settings.REPOS_DIR).resolve())
    if str(repo.local_path).startswith(managed_root):
        shutil.rmtree(repo.local_path, ignore_errors=True)

    await db.delete(repo)
    await db.commit()
    return None


# ──────────────────────────────────────────────────────────────
# Error tracking
# ──────────────────────────────────────────────────────────────

@router.post("/{repo_id}/errors", response_model=Dict[str, Any])
async def submit_error(
    repo_id: str,
    error_type: str = Body(..., description="Type of error (e.g. ImportError, SyntaxError, etc.)"),
    error_message: str = Body(..., description="Error message"),
    file_path: Optional[str] = Body(None, description="File path where error occurred"),
    context: Optional[Dict[str, Any]] = Body(None, description="Additional context"),
    db: AsyncSession = Depends(get_db),
):
    """Submit an error that occurred during repository analysis or execution."""
    repo = await _get_or_404(repo_id, db)
    from app.models.repository import ErrorLog
    
    error_log = ErrorLog(
        repository_id=repo_id,
        file_path=file_path,
        error_type=error_type,
        error_message=error_message,
        context=context or {},
    )
    db.add(error_log)
    await db.commit()
    await db.refresh(error_log)
    return {"id": error_log.id, "status": "submitted", "repository_id": repo_id}


@router.get("/{repo_id}/errors", response_model=List[ErrorLogResponse])
async def list_errors(
    repo_id: str,
    resolved: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
):
    """List error logs for a repository, optionally filtered by resolution status."""
    repo = await _get_or_404(repo_id, db)
    from app.models.repository import ErrorLog
    
    query = select(ErrorLog).where(ErrorLog.repository_id == repo_id)
    if resolved is not None:
        query = query.where(ErrorLog.resolved == resolved)
    query = query.order_by(ErrorLog.occurred_at.desc())
    res = await db.execute(query)
    return res.scalars().all()


@router.post("/{repo_id}/errors/{error_id}/resolve", response_model=Dict[str, Any])
async def resolve_error(
    repo_id: str,
    error_id: str,
    resolution_notes: str = Body(..., description="Notes about the resolution"),
    db: AsyncSession = Depends(get_db),
):
    """Mark an error as resolved with notes."""
    repo = await _get_or_404(repo_id, db)
    from app.models.repository import ErrorLog
    
    error_log_res = await db.execute(
        select(ErrorLog).where(
            ErrorLog.id == error_id,
            ErrorLog.repository_id == repo_id,
        )
    )
    error_log = error_log_res.scalar_one_or_none()
    if not error_log:
        raise HTTPException(status_code=404, detail="Error log not found")
    
    error_log.resolved = True
    error_log.resolved_at = datetime.now(timezone.utc)
    error_log.resolution_notes = resolution_notes
    await db.commit()
    await db.refresh(error_log)
    return {"id": error_log.id, "status": "resolved", "resolution_notes": resolution_notes}


# ──────────────────────────────────────────────────────────────
# Code Search Dataset Integration
# ──────────────────────────────────────────────────────────────

@router.post("/{repo_id}/code-search", response_model=Dict[str, Any])
async def search_code_snippets(
    repo_id: str,
    query: str = Body(..., description="Search query for code snippets"),
    language: Optional[str] = Body(None, description="Language filter (e.g., python, javascript)"),
    limit: int = Body(5, description="Maximum number of results"),
    db: AsyncSession = Depends(get_db),
):
    """
    Search for code snippets using CodeSearchNet dataset.
    Returns code examples relevant to the query.
    """
    repo = await _get_or_404(repo_id, db)
    from app.services.code_search_dataset import CodeSearchDatasetService

    service = CodeSearchDatasetService()
    result = await service.search(query=query, language=language, limit=limit)

    return {
        "repository_id": repo_id,
        "query": result.query,
        "results": [
            {
                "language": r.snippet.language,
                "code": r.snippet.code,
                "docstring": r.snippet.docstring,
                "score": r.score,
                "match_reason": r.match_reason,
            }
            for r in result.results
        ],
        "total_results": result.total_results,
        "dataset_source": result.dataset_source,
    }


@router.post("/{repo_id}/code-examples", response_model=Dict[str, Any])
async def get_code_examples(
    repo_id: str,
    concept: str = Body(..., description="Concept to find examples for"),
    language: Optional[str] = Body(None, description="Language filter"),
    limit: int = Body(3, description="Maximum number of examples"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get code examples for a specific concept using CodeSearchNet dataset.
    """
    repo = await _get_or_404(repo_id, db)
    from app.services.code_search_dataset import CodeSearchDatasetService

    service = CodeSearchDatasetService()
    result = await service.get_examples(concept=concept, language=language, limit=limit)

    return {
        "repository_id": repo_id,
        "concept": result.concept,
        "examples": [
            {
                "language": ex.language,
                "code": ex.code,
                "docstring": ex.docstring,
            }
            for ex in result.examples
        ],
        "language_filter": result.language,
    }


# ──────────────────────────────────────────────────────────────
# SWE-bench Verified Integration
# ──────────────────────────────────────────────────────────────

@router.post("/{repo_id}/swebench/search", response_model=Dict[str, Any])
async def search_swebench_fixes(
    repo_id: str,
    query: str = Body(..., description="Query describing the issue or error"),
    repo_filter: Optional[str] = Body(None, description="Optional upstream repository filter"),
    limit: int = Body(5, description="Maximum number of results"),
    db: AsyncSession = Depends(get_db),
):
    """
    Search SWE-bench Verified bug fixes and patches.
    """
    repo = await _get_or_404(repo_id, db)
    from app.services.swebench_service import SWEBenchService

    service = SWEBenchService()
    result = service.search_fixes(query=query, repo_filter=repo_filter, limit=limit)
    return result.model_dump()


@router.get("/{repo_id}/swebench/{instance_id}", response_model=Dict[str, Any])
async def get_swebench_instance(
    repo_id: str,
    instance_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get detailed verified patch and problem statement for a specific SWE-bench instance.
    """
    repo = await _get_or_404(repo_id, db)
    from app.services.swebench_service import SWEBenchService

    service = SWEBenchService()
    instance = service.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="SWE-bench instance not found")
    return instance.model_dump()


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

async def _get_or_404(repo_id: str, db: AsyncSession) -> Repository:
    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo
