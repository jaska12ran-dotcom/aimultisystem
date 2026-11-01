import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Integer,
    BigInteger,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    JSON,
    Float,
    Index,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


def generate_id() -> str:
    return str(uuid.uuid4())


class Repository(Base):
    """Core repository digital twin record."""
    __tablename__ = "repositories"

    id = Column(String(36), primary_key=True, default=generate_id)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)

    # Source information
    source_type = Column(String(50), nullable=False, index=True)   # github | zip | local
    source_url = Column(String(2048), nullable=True)               # GitHub URL if cloned
    source_path = Column(String(2048), nullable=False)             # Original user-supplied input
    local_path = Column(String(2048), nullable=False)              # Internal workspace on disk

    # Git metadata
    default_branch = Column(String(100), default="main")
    clone_depth = Column(Integer, default=0)                       # 0 = full clone

    # Statistics
    total_files = Column(Integer, default=0)
    total_lines = Column(Integer, default=0)
    total_symbols = Column(Integer, default=0)
    total_size_bytes = Column(BigInteger, default=0)               # total uncompressed size
    file_count_by_language = Column(JSON, default=dict)            # {"python": 12, "ts": 8}

    # Analysis state
    status = Column(String(50), default="created", index=True)
    # created → cloning/extracting → scanning → analyzing → ready | failed
    analysis_phase = Column(String(50), default="created")
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    files = relationship(
        "RepositoryFile", back_populates="repository", cascade="all, delete-orphan"
    )
    languages = relationship(
        "RepositoryLanguage", back_populates="repository", cascade="all, delete-orphan"
    )
    folders = relationship(
        "CodeFolder", back_populates="repository", cascade="all, delete-orphan"
    )
    symbols = relationship(
        "CodeSymbol", back_populates="repository", cascade="all, delete-orphan"
    )
    imports = relationship(
        "CodeImport", back_populates="repository", cascade="all, delete-orphan"
    )
    dependencies = relationship(
        "RepositoryDependency", back_populates="repository", cascade="all, delete-orphan"
    )
    commits = relationship(
        "GitCommit", back_populates="repository", cascade="all, delete-orphan"
    )
    relationships = relationship(
        "CodeRelationship", back_populates="repository", cascade="all, delete-orphan"
    )
    error_logs = relationship(
        "ErrorLog", back_populates="repository", cascade="all, delete-orphan"
    )
    vector_chunks = relationship(
        "RepositoryVectorChunk", back_populates="repository", cascade="all, delete-orphan"
    )
    index_state = relationship(
        "RepositoryIndexState",
        back_populates="repository",
        uselist=False,
        cascade="all, delete-orphan",
    )


class RepositoryIndexState(Base):
    """Freshness and last-run summary for a repository's persisted twin."""

    __tablename__ = "repository_index_states"

    repository_id = Column(
        String(36),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        primary_key=True,
    )
    status = Column(String(30), nullable=False, default="not_indexed")
    last_started_at = Column(DateTime(timezone=True), nullable=True)
    last_successful_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    indexed_git_head = Column(String(64), nullable=True)
    indexed_file_count = Column(Integer, nullable=False, default=0)
    indexed_symbol_count = Column(Integer, nullable=False, default=0)
    last_added_files = Column(Integer, nullable=False, default=0)
    last_updated_files = Column(Integer, nullable=False, default=0)
    last_deleted_files = Column(Integer, nullable=False, default=0)
    last_unchanged_files = Column(Integer, nullable=False, default=0)

    repository = relationship("Repository", back_populates="index_state")


class RepositoryLanguage(Base):
    """Per-language breakdown for a repository."""
    __tablename__ = "repository_languages"

    id = Column(String(36), primary_key=True, default=generate_id)
    repository_id = Column(
        String(36),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    language = Column(String(100), nullable=False, index=True)
    file_count = Column(Integer, default=0)
    line_count = Column(Integer, default=0)
    size_bytes = Column(BigInteger, default=0)
    percentage = Column(Float, default=0.0)   # 0-100 by line share

    repository = relationship("Repository", back_populates="languages")

    __table_args__ = (
        Index("ix_repo_lang_repo_lang", "repository_id", "language", unique=True),
    )


class RepositoryFile(Base):
    """Individual file entry inside the digital twin."""
    __tablename__ = "repository_files"

    id = Column(String(36), primary_key=True, default=generate_id)
    repository_id = Column(
        String(36),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relative_path = Column(String(2048), nullable=False, index=True)
    file_name = Column(String(512), nullable=False)
    file_extension = Column(String(50), nullable=False)
    language = Column(String(50), default="unknown")
    size_bytes = Column(BigInteger, default=0)
    line_count = Column(Integer, default=0)
    is_binary = Column(Boolean, default=False)
    is_test = Column(Boolean, default=False)
    is_config = Column(Boolean, default=False)
    is_documentation = Column(Boolean, default=False)
    sha256_hash = Column(String(64), nullable=True)
    ast_parsed = Column(Boolean, default=False)

    repository = relationship("Repository", back_populates="files")
    symbols = relationship("CodeSymbol", back_populates="file", cascade="all, delete-orphan")
    imports = relationship("CodeImport", back_populates="file", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_repo_files_repo_path", "repository_id", "relative_path"),
    )


class RepositoryDependency(Base):
    """Dependency declared in package manifests (requirements.txt, package.json, etc.)."""
    __tablename__ = "repository_dependencies"

    id = Column(String(36), primary_key=True, default=generate_id)
    repository_id = Column(
        String(36),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    package_name = Column(String(255), nullable=False, index=True)
    version_spec = Column(String(100), nullable=True)
    resolved_version = Column(String(100), nullable=True)
    ecosystem = Column(String(50), nullable=False)   # pip | npm | cargo | maven | go | gem
    is_dev = Column(Boolean, default=False)
    manifest_file = Column(String(512), nullable=True)   # relative path to manifest

    repository = relationship("Repository", back_populates="dependencies")

    __table_args__ = (
        Index("ix_repo_dep_repo_pkg", "repository_id", "package_name"),
    )


class RepositoryVectorChunk(Base):
    """Repository-aware vector chunk for retrieval-augmented code search."""
    __tablename__ = "repository_vector_chunks"

    id = Column(String(36), primary_key=True, default=generate_id)
    repository_id = Column(
        String(36),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path = Column(String(2048), nullable=False, index=True)
    symbol = Column(String(255), nullable=True)
    language = Column(String(50), nullable=False, index=True)
    start_line = Column(Integer, nullable=False, default=1)
    end_line = Column(Integer, nullable=False, default=1)
    content_type = Column(String(100), nullable=False, index=True)
    content = Column(Text, nullable=False)
    embedding = Column(JSON, default=list)
    embedding_model = Column(String(128), default="deterministic-hash")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    repository = relationship("Repository", back_populates="vector_chunks")

    __table_args__ = (
        Index("ix_repo_vector_repo_file", "repository_id", "file_path"),
    )


# Backward-compatible alias used by the ingestion / twin builders.
Dependency = RepositoryDependency


class CodeFolder(Base):
    __tablename__ = "code_folders"

    id = Column(String(36), primary_key=True, default=generate_id)
    repository_id = Column(
        String(36),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relative_path = Column(String(2048), nullable=False)
    folder_name = Column(String(512), nullable=False)
    parent_path = Column(String(2048), nullable=True)
    depth = Column(Integer, default=0)
    file_count = Column(Integer, default=0)
    total_size_bytes = Column(BigInteger, default=0)

    repository = relationship("Repository", back_populates="folders")


class CodeSymbol(Base):
    __tablename__ = "code_symbols"

    id = Column(String(36), primary_key=True, default=generate_id)
    repository_id = Column(
        String(36),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_id = Column(
        String(36),
        ForeignKey("repository_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False, index=True)
    qualified_name = Column(String(512), nullable=False)
    symbol_type = Column(String(50), nullable=False, index=True)
    start_line = Column(Integer, nullable=False)
    end_line = Column(Integer, nullable=False)
    signature = Column(Text, nullable=False)
    docstring = Column(Text, nullable=True)
    parameters = Column(JSON, default=list)
    return_type = Column(String(255), nullable=True)
    complexity_score = Column(Integer, default=1)
    is_exported = Column(Boolean, default=True)

    repository = relationship("Repository", back_populates="symbols")
    file = relationship("RepositoryFile", back_populates="symbols")

    @property
    def file_path(self) -> str:
        return self.file.relative_path if self.file else ""

    @property
    def line_start(self) -> int:
        return self.start_line

    @property
    def line_end(self) -> int:
        return self.end_line


class CodeImport(Base):
    __tablename__ = "code_imports"

    id = Column(String(36), primary_key=True, default=generate_id)
    repository_id = Column(
        String(36),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_id = Column(
        String(36),
        ForeignKey("repository_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    module_name = Column(String(512), nullable=False)
    imported_symbols = Column(JSON, default=list)
    is_standard_lib = Column(Boolean, default=False)
    is_third_party = Column(Boolean, default=True)
    line_number = Column(Integer, nullable=False)

    repository = relationship("Repository", back_populates="imports")
    file = relationship("RepositoryFile", back_populates="imports")


class GitCommit(Base):
    __tablename__ = "git_commits"

    id = Column(String(36), primary_key=True, default=generate_id)
    repository_id = Column(
        String(36),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    commit_hash = Column(String(64), nullable=False, index=True)
    author_name = Column(String(255), nullable=False)
    author_email = Column(String(255), nullable=False)
    committed_at = Column(DateTime, nullable=False)
    message = Column(Text, nullable=False)
    files_changed = Column(JSON, default=list)
    insertions = Column(Integer, default=0)
    deletions = Column(Integer, default=0)

    repository = relationship("Repository", back_populates="commits")


class ErrorLog(Base):
    """Track errors that occur during repository analysis or execution, with
    file-level attribution and explanation metadata for root-cause analysis."""

    __tablename__ = "error_logs"

    id = Column(String(36), primary_key=True, default=generate_id)
    repository_id = Column(
        String(36),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path = Column(String(2048), nullable=True, index=True)
    error_type = Column(String(100), nullable=False)   # e.g. ImportError, SyntaxError, TimeoutError, etc.
    error_message = Column(Text, nullable=False)
    occurred_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    stack_trace = Column(Text, nullable=True)
    context = Column(JSON, nullable=True)   # arbitrary key/value context (test_name, component, etc.)
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolution_notes = Column(Text, nullable=True)

    repository = relationship("Repository", back_populates="error_logs")


# Update Repository to have error_logs relationship
    # (will be added after CodeRelationship class)


class CodeRelationship(Base):
    __tablename__ = "code_relationships"

    id = Column(String(36), primary_key=True, default=generate_id)
    repository_id = Column(
        String(36),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_symbol_id = Column(String(36), nullable=True, index=True)
    target_symbol_id = Column(String(36), nullable=True, index=True)
    source_file_id = Column(String(36), nullable=False, index=True)
    target_file_id = Column(String(36), nullable=True, index=True)
    relationship_type = Column(String(50), nullable=False)
    evidence_line = Column(Integer, nullable=False)
    evidence_text = Column(Text, nullable=True)

    repository = relationship("Repository", back_populates="relationships")
