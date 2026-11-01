import sys
import psutil
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_db
from app.core.config import settings

router = APIRouter()

@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    db_status = "connected"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    payload = {
        "status": "healthy" if db_status == "connected" else "unhealthy",
        "service": settings.PROJECT_NAME,
        "database": db_status,
        "runtime": {
            "python_version": sys.version,
            "platform": sys.platform,
            "cpu_percent": psutil.cpu_percent(),
            "memory_usage_mb": round(psutil.Process().memory_info().rss / (1024 * 1024), 2),
        },
    }
    return JSONResponse(
        status_code=200 if db_status == "connected" else 503,
        content=payload,
    )
