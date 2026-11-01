"""
Repository Ingestion Service
-----------------------------
Orchestrates the complete ingestion pipeline:
  1. Validate input (validator.py)
  2. Create isolated workspace
  3. Clone / extract / link source
  4. Scan filesystem (scanner.py)
  5. Parse dependencies
  6. Extract Git history (git_cloner.py)
  7. Persist all artefacts to database
  8. Update repository status

SECURITY: No repository code is executed at any point.
"""
from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.repository import (
    Repository,
    RepositoryFile,
    RepositoryLanguage,
    RepositoryDependency,
    CodeFolder,
    CodeSymbol,
    CodeImport,
    GitCommit,
    CodeRelationship,
    RepositoryIndexState,
)
from app.services.ingestion.archive import extract_zip_safely, ArchiveExtractionError
from app.services.ingestion.git_cloner import clone_git_repository, extract_git_commits
from app.services.ingestion.scanner import scan_directory, parse_project_dependencies
from app.services.ingestion.validator import (
    validate_github_url,
    validate_local_path,
    validate_upload_zip,
    validate_repo_name,
    ValidationError,
)
from app.services.parser.polyglot_parser import parse_polyglot_file
from app.utils.logger import logger


class IngestionService:
    """High-level ingestion facade used by API endpoints."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ──────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────

    async def ingest_from_github(
        self,
        url: str,
        branch: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Repository:
        """Validate → clone → scan → persist."""
        validated_url = validate_github_url(url)
        repo_slug = validated_url.rstrip("/").split("/")[-1].removesuffix(".git")
        display_name = validate_repo_name(name, repo_slug)
        workspace = self._make_workspace(f"github_{repo_slug}")

        repo = await self._create_repo_record(
            name=display_name,
            source_type="github",
            source_url=validated_url,
            source_path=validated_url,
            local_path=str(workspace),
        )

        try:
            await self._update_phase(repo, "cloning")
            clone_info = clone_git_repository(validated_url, workspace, branch=branch)
            repo.default_branch = clone_info["default_branch"]
            await self._build_twin(repo, workspace)
        except (ValidationError, ArchiveExtractionError) as exc:
            await self._fail(repo, str(exc))
            raise
        except Exception as exc:
            await self._fail(repo, f"Unexpected error: {exc}")
            raise

        return repo

    async def ingest_from_zip(
        self, zip_file_path: str, original_filename: str
    ) -> Repository:
        """Validate → extract → scan → persist."""
        safe_name = validate_upload_zip(
            original_filename,
            os.path.getsize(zip_file_path) if os.path.exists(zip_file_path) else 0,
        )
        display_name = validate_repo_name(None, Path(safe_name).stem)
        workspace = self._make_workspace(f"zip_{Path(safe_name).stem}")

        repo = await self._create_repo_record(
            name=display_name,
            source_type="zip",
            source_path=safe_name,
            local_path=str(workspace),
        )

        try:
            await self._update_phase(repo, "extracting")
            extracted_root, _ = extract_zip_safely(zip_file_path, workspace)
            repo.local_path = extracted_root
            await self._build_twin(repo, Path(extracted_root))
        except (ValidationError, ArchiveExtractionError) as exc:
            await self._fail(repo, str(exc))
            raise
        except Exception as exc:
            await self._fail(repo, f"Unexpected error: {exc}")
            raise

        return repo

    async def ingest_from_local(
        self, raw_path: str, name: Optional[str] = None
    ) -> Repository:
        """Validate → reference in-place → scan → persist."""
        validated = validate_local_path(raw_path)
        display_name = validate_repo_name(name, validated.name)

        repo = await self._create_repo_record(
            name=display_name,
            source_type="local",
            source_path=str(validated),
            local_path=str(validated),
        )

        try:
            await self._build_twin(repo, validated)
        except (ValidationError, ArchiveExtractionError) as exc:
            await self._fail(repo, str(exc))
            raise
        except Exception as exc:
            await self._fail(repo, f"Unexpected error: {exc}")
            raise

        return repo

    # ──────────────────────────────────────────────────────────
    # Core twin builder
    # ──────────────────────────────────────────────────────────

    async def _build_twin(self, repo: Repository, local_dir: Path) -> None:
        await self._update_phase(repo, "scanning")

        # ── 1. Filesystem scan ─────────────────────────────────
        scan = scan_directory(str(local_dir))

        repo.total_files = scan["total_files"]
        repo.total_lines = scan["total_lines"]
        repo.total_size_bytes = scan["total_size_bytes"]
        repo.file_count_by_language = {
            ld["language"]: ld["file_count"] for ld in scan["language_details"]
        }

        # ── 2. Folders ─────────────────────────────────────────
        for fd in scan["folders"]:
            self.db.add(CodeFolder(
                repository_id=repo.id,
                relative_path=fd["relative_path"],
                folder_name=fd["folder_name"],
                parent_path=fd["parent_path"],
                depth=fd.get("depth", 0),
                file_count=fd["file_count"],
                total_size_bytes=fd.get("total_size_bytes", 0),
            ))

        # ── 3. Language records ────────────────────────────────
        for ld in scan["language_details"]:
            self.db.add(RepositoryLanguage(
                repository_id=repo.id,
                language=ld["language"],
                file_count=ld["file_count"],
                line_count=ld["line_count"],
                size_bytes=ld["size_bytes"],
                percentage=ld["percentage"],
            ))

        # ── 4. Files + AST symbols ────────────────────────────
        file_map: Dict[str, RepositoryFile] = {}
        await self.db.flush()   # ensure repo.id is in DB for FKs

        for f_data in scan["files"]:
            rf = RepositoryFile(
                repository_id=repo.id,
                relative_path=f_data["relative_path"],
                file_name=f_data["file_name"],
                file_extension=f_data["file_extension"],
                language=f_data["language"],
                size_bytes=f_data["size_bytes"],
                line_count=f_data["line_count"],
                is_binary=f_data["is_binary"],
                is_test=f_data["is_test"],
                is_config=f_data["is_config"],
                is_documentation=f_data["is_documentation"],
                sha256_hash=f_data["sha256_hash"],
            )
            self.db.add(rf)
            file_map[f_data["relative_path"]] = rf

        await self.db.flush()

        # ── 5. Dependencies ───────────────────────────────────
        await self._update_phase(repo, "analyzing")
        raw_deps = parse_project_dependencies(str(local_dir))
        for dep in raw_deps:
            self.db.add(RepositoryDependency(
                repository_id=repo.id,
                package_name=dep["package_name"],
                version_spec=dep.get("version_spec"),
                ecosystem=dep["ecosystem"],
                is_dev=dep.get("is_dev", False),
                manifest_file=dep.get("manifest_file"),
            ))

        # ── 6. Git commits ────────────────────────────────────
        commits_data = extract_git_commits(str(local_dir), max_commits=100)
        for c in commits_data:
            self.db.add(GitCommit(
                repository_id=repo.id,
                commit_hash=c["commit_hash"],
                author_name=c["author_name"],
                author_email=c["author_email"],
                committed_at=c["committed_at"],
                message=c["message"],
                files_changed=c["files_changed"],
                insertions=c["insertions"],
                deletions=c["deletions"],
            ))

        # ── 7. AST parsing ────────────────────────────────────
        total_symbols = 0
        symbol_registry: Dict[str, CodeSymbol] = {}
        pending_rels = []

        for rel_path, rf in file_map.items():
            if rf.is_binary or rf.size_bytes > 2 * 1024 * 1024:
                continue

            full_path = local_dir / rel_path
            try:
                full_path.relative_to(local_dir)
            except ValueError:
                logger.warning("Skipping file outside repository root during ingestion: %s", rel_path)
                continue
            if not full_path.exists():
                continue

            try:
                content = full_path.read_text(encoding="utf-8", errors="ignore")
                parsed = parse_polyglot_file(content, rf.language)
                rf.ast_parsed = parsed.get("ast_parsed", False)

                for sym in parsed.get("symbols", []):
                    cs = CodeSymbol(
                        repository_id=repo.id,
                        file_id=rf.id,
                        name=sym["name"],
                        qualified_name=sym["qualified_name"],
                        symbol_type=sym["symbol_type"],
                        start_line=sym["start_line"],
                        end_line=sym["end_line"],
                        signature=sym["signature"],
                        docstring=sym.get("docstring"),
                        parameters=sym.get("parameters", []),
                        return_type=sym.get("return_type"),
                        complexity_score=sym.get("complexity_score", 1),
                        is_exported=sym.get("is_exported", True),
                    )
                    self.db.add(cs)
                    total_symbols += 1
                    symbol_registry[sym["qualified_name"]] = cs
                    symbol_registry[sym["name"]] = cs

                for imp in parsed.get("imports", []):
                    self.db.add(CodeImport(
                        repository_id=repo.id,
                        file_id=rf.id,
                        module_name=imp["module_name"],
                        imported_symbols=imp.get("imported_symbols", []),
                        is_standard_lib=imp.get("is_standard_lib", False),
                        is_third_party=imp.get("is_third_party", True),
                        line_number=imp["line_number"],
                    ))

                for rel_info in parsed.get("relationships", []):
                    pending_rels.append({"file_id": rf.id, "rel": rel_info})

            except Exception as exc:
                logger.warning("AST parse failed for %s: %s", rel_path, exc)
                rf.ast_parsed = False

        await self.db.flush()

        # ── 8. Relationships ──────────────────────────────────
        await self.db.flush()
        for item in pending_rels:
            rel_info = item["rel"]
            source_symbol = symbol_registry.get(rel_info.get("source_name"))
            target_symbol = symbol_registry.get(rel_info.get("target_name"))
            if source_symbol is None and target_symbol is None:
                logger.warning(
                    "Skipping relationship with no resolvable symbols in %s",
                    item["file_id"],
                )
                continue
            self.db.add(CodeRelationship(
                repository_id=repo.id,
                source_symbol_id=source_symbol.id if source_symbol else None,
                target_symbol_id=target_symbol.id if target_symbol else None,
                source_file_id=item["file_id"],
                relationship_type=rel_info.get("relationship_type", "references"),
                evidence_line=rel_info.get("evidence_line", 1),
                evidence_text=rel_info.get("evidence_text"),
            ))

        repo.total_symbols = total_symbols
        repo.status = "ready"
        repo.analysis_phase = "ready"
        repo.updated_at = datetime.now(timezone.utc)
        state = await self._ensure_index_state(repo)
        completed_at = datetime.now(timezone.utc)
        state.status = "ready"
        state.last_started_at = state.last_started_at or completed_at
        state.last_successful_at = completed_at
        state.last_error = None
        state.indexed_file_count = scan["total_files"]
        state.indexed_symbol_count = total_symbols
        state.last_added_files = scan["total_files"]
        state.last_updated_files = 0
        state.last_deleted_files = 0
        state.last_unchanged_files = 0
        state.indexed_git_head = commits_data[0]["commit_hash"] if commits_data else None
        await self.db.commit()
        await self.db.refresh(repo)
        logger.info("Repository '%s' twin built successfully (%d symbols).", repo.name, total_symbols)

    async def _ensure_index_state(self, repo: Repository) -> RepositoryIndexState:
        """Return the repository's index-state row, inserting it if missing."""
        state = await self.db.get(RepositoryIndexState, repo.id)
        if state is None:
            state = RepositoryIndexState(repository_id=repo.id)
            self.db.add(state)
        return state

    # ──────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────

    def _make_workspace(self, slug: str) -> Path:
        workspace = Path(settings.REPOS_DIR) / f"{slug}_{uuid.uuid4().hex[:8]}"
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    async def _create_repo_record(
        self,
        name: str,
        source_type: str,
        source_path: str,
        local_path: str,
        source_url: Optional[str] = None,
    ) -> Repository:
        repo = Repository(
            name=name,
            source_type=source_type,
            source_url=source_url,
            source_path=source_path,
            local_path=local_path,
            status="created",
            analysis_phase="created",
        )
        self.db.add(repo)
        await self.db.commit()
        await self.db.refresh(repo)
        state = RepositoryIndexState(
            repository_id=repo.id,
            status="indexing",
            last_started_at=datetime.now(timezone.utc),
        )
        self.db.add(state)
        await self.db.commit()
        return repo

    async def _update_phase(self, repo: Repository, phase: str) -> None:
        repo.status = "analyzing"
        repo.analysis_phase = phase
        repo.updated_at = datetime.now(timezone.utc)
        state = await self._ensure_index_state(repo)
        state.status = "indexing"
        state.last_started_at = datetime.now(timezone.utc)
        await self.db.commit()

    async def _fail(self, repo: Repository, message: str) -> None:
        repo.status = "failed"
        repo.analysis_phase = "failed"
        repo.error_message = message
        repo.updated_at = datetime.now(timezone.utc)
        state = await self.db.get(RepositoryIndexState, repo.id)
        if state is not None:
            state.status = "failed"
            state.last_error = message[:4000]
        else:
            state = RepositoryIndexState(repository_id=repo.id, status="failed", last_error=message[:4000])
            self.db.add(state)
        await self.db.commit()
        logger.error("Repository '%s' ingestion failed: %s", repo.name, message)
