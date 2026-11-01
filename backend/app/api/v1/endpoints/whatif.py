"""
What-If Code Change Simulator — API Endpoint
=============================================
POST /repositories/{repo_id}/whatif/simulate

SAFETY: This endpoint is strictly read-only. It NEVER modifies, commits,
merges, or deploys any change to the source repository.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.repository import Repository
from app.schemas.whatif import WhatIfRequest, WhatIfSimulationResult
from app.services.whatif_simulator import WhatIfSimulatorService

router = APIRouter()


async def _get_repo_or_404(repo_id: str, db: AsyncSession) -> Repository:
    repo = await db.get(Repository, repo_id)
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repo_id} not found.",
        )
    return repo


@router.post(
    "/{repo_id}/whatif/simulate",
    response_model=WhatIfSimulationResult,
    summary="What-If Code Change Simulator",
    description=(
        "Simulate the impact of a proposed code change on the indexed repository. "
        "Performs deterministic AST/call-graph analysis and heuristic AI-based checks. "
        "**NEVER modifies, commits, or deploys any change.** All analysis is read-only."
    ),
    tags=["What-If Simulator"],
)
async def simulate_change(
    repo_id: str,
    payload: WhatIfRequest,
    db: AsyncSession = Depends(get_db),
) -> WhatIfSimulationResult:
    repo = await _get_repo_or_404(repo_id, db)
    service = WhatIfSimulatorService(db, repo)
    return await service.simulate(payload)
