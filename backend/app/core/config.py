import os
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    PROJECT_NAME: str = "CodeTwin — AI Software Repository Intelligence & Verification Platform"
    API_V1_STR: str = "/api/v1"
    
    # Database
    # Defaults to SQLite with aiosqlite for zero-config local startup, supports PostgreSQL+asyncpg in prod
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        f"sqlite+aiosqlite:///{BASE_DIR.as_posix()}/codetwin.db"
    )
    
    # Storage & Uploads
    STORAGE_DIR: str = os.getenv("STORAGE_DIR", str(BASE_DIR / "storage"))
    REPOS_DIR: str = os.getenv("REPOS_DIR", str(BASE_DIR / "storage" / "repos"))
    UPLOADS_DIR: str = os.getenv("UPLOADS_DIR", str(BASE_DIR / "storage" / "uploads"))
    
    # Sandboxing & Execution
    DOCKER_SANDBOX_ENABLED: bool = os.getenv("DOCKER_SANDBOX_ENABLED", "false").lower() == "true"
    EXECUTION_TIMEOUT_SECONDS: int = 120
    
    # AI / LLM Defaults
    OPENAI_API_BASE: str = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OLLAMA_API_BASE: str = os.getenv("OLLAMA_API_BASE", "http://localhost:11434")
    DEFAULT_LLM_PROVIDER: str = os.getenv("DEFAULT_LLM_PROVIDER", "mock")
    
    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

settings = Settings()

# Ensure storage directories exist
os.makedirs(settings.STORAGE_DIR, exist_ok=True)
os.makedirs(settings.REPOS_DIR, exist_ok=True)
os.makedirs(settings.UPLOADS_DIR, exist_ok=True)
