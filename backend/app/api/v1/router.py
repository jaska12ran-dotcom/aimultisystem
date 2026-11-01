from fastapi import APIRouter
from app.api.v1.endpoints import health, repositories, twin, agents, whatif

api_router = APIRouter()
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(repositories.router, prefix="/repositories", tags=["Repositories"])
api_router.include_router(twin.router, prefix="/repositories", tags=["Digital Twin"])
api_router.include_router(agents.router, prefix="/repositories", tags=["AI Agents & Verification"])
api_router.include_router(whatif.router, prefix="/repositories", tags=["What-If Simulator"])
