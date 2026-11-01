import os
import sys
import tempfile
from pathlib import Path
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Add backend directory to sys.path
backend_path = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_path))

# Temporary test database file so tables persist across connections during test
_test_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_test_db_file.close()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_test_db_file.name).as_posix()}"

from app.main import app
from app.core.database import Base, engine

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
