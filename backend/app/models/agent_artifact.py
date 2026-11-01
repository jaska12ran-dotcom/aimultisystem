import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, JSON, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class GeneratedDoc(Base):
    __tablename__ = "generated_docs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    repository_id: Mapped[str] = mapped_column(String(36), ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False) # architecture, api, models, module, custom
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    grounded_symbols: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list) # symbol names used as evidence
    grounded_files: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list) # file paths used as evidence
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow_naive)

    # Relationships
    repository = relationship("Repository", backref="generated_docs")


class GeneratedTestSuite(Base):
    __tablename__ = "generated_test_suites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    repository_id: Mapped[str] = mapped_column(String(36), ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    target_file: Mapped[str] = mapped_column(String(500), nullable=False)
    target_symbol: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    test_framework: Mapped[str] = mapped_column(String(50), default="pytest") # pytest, unittest, jest, vitest
    test_file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True) # relative path to test file
    test_code: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Execution status & metrics
    status: Mapped[str] = mapped_column(String(50), default="pending") # pending, running, passed, failed, error
    execution_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tests_run: Mapped[int] = mapped_column(Integer, default=0)
    tests_passed: Mapped[int] = mapped_column(Integer, default=0)
    tests_failed: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow_naive)

    # Relationships
    repository = relationship("Repository", backref="generated_test_suites")


class AgentChatMessage(Base):
    __tablename__ = "agent_chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    repository_id: Mapped[str] = mapped_column(String(36), ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False) # user, assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, default=list) # [{symbol, file, line_start, line_end}]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow_naive)

    # Relationships
    repository = relationship("Repository", backref="chat_messages")
