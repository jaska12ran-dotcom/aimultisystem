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
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.repository import Repository
from app.schemas.repository import (
    RepositoryCloneRequest,
    RepositoryLocalRequest,
    RepositoryResponse,
)
from app.services.ingestion import IngestionService, ValidationError, ArchiveExtractionError
from app.services.error_explainer import ErrorExplainerService

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
    from sqlalchemy import select
    
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
    from sqlalchemy import select
    
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
    from sqlalchemy import select
    
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
# Helpers
# ──────────────────────────────────────────────────────────────

async def _get_or_404(repo_id: str, db: AsyncSession) -> Repository:
    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo
