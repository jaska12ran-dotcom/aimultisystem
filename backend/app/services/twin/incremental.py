"""Incrementally refresh a repository's persisted digital twin."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import (
    CodeFolder,
    CodeImport,
    CodeRelationship,
    CodeSymbol,
    GitCommit,
    Repository,
    RepositoryDependency,
    RepositoryFile,
    RepositoryIndexState,
    RepositoryLanguage,
    RepositoryVectorChunk,
)
from app.services.ingestion.git_cloner import extract_git_commits
from app.services.ingestion.scanner import parse_project_dependencies, scan_directory
from app.services.parser.polyglot_parser import parse_polyglot_file
from app.services.rag.service import RepositoryIndexer

logger = logging.getLogger("codetwin.twin")

DEPENDENCY_MANIFESTS = {
    "requirements.txt", "requirements-dev.txt", "requirements-test.txt",
    "pyproject.toml", "setup.py", "setup.cfg", "pipfile", "pipfile.lock",
    "package.json", "go.mod", "cargo.toml", "pom.xml", "build.gradle",
    "build.gradle.kts", "gemfile", "composer.json",
}


class RepositoryIndexBusyError(RuntimeError):
    pass


class RepositoryReindexer:
    """Hash-scan the workspace, then parse and refresh only invalidated files."""

    def __init__(self, db: AsyncSession, repository_id: str) -> None:
        self.db = db
        self.repository_id = repository_id

    async def reindex(self) -> dict[str, Any]:
        repo = await self.db.get(Repository, self.repository_id)
        if repo is None:
            raise LookupError(f"Repository {self.repository_id} not found")

        now = datetime.now(timezone.utc)
        claim = await self.db.execute(
            update(Repository)
            .where(
                Repository.id == self.repository_id,
                Repository.status.not_in(("indexing", "analyzing")),
            )
            .values(status="indexing", analysis_phase="scanning", updated_at=now)
        )
        if claim.rowcount != 1:
            await self.db.rollback()
            raise RepositoryIndexBusyError("Repository analysis is already in progress")

        state = await self.db.get(RepositoryIndexState, self.repository_id)
        if state is None:
            state = RepositoryIndexState(repository_id=self.repository_id)
            self.db.add(state)
        state.status = "indexing"
        state.last_started_at = now
        state.last_error = None
        await self.db.commit()

        try:
            return await self._refresh(repo, state)
        except Exception as exc:
            await self.db.rollback()
            failed_repo = await self.db.get(Repository, self.repository_id)
            failed_state = await self.db.get(RepositoryIndexState, self.repository_id)
            if failed_repo is not None:
                failed_repo.status = "failed"
                failed_repo.analysis_phase = "failed"
                failed_repo.error_message = str(exc)[:4000]
            if failed_state is not None:
                failed_state.status = "failed"
                failed_state.last_error = str(exc)[:4000]
            await self.db.commit()
            raise

    async def _refresh(self, repo: Repository, state: RepositoryIndexState) -> dict[str, Any]:
        root = Path(repo.local_path).resolve()
        if not root.is_dir():
            raise ValueError("Repository source path is unavailable")

        scan = scan_directory(str(root))
        scan_by_path = {item["relative_path"].replace("\\", "/"): item for item in scan["files"]}
        old_result = await self.db.execute(
            select(RepositoryFile).where(RepositoryFile.repository_id == self.repository_id)
        )
        old_files = {item.relative_path.replace("\\", "/"): item for item in old_result.scalars().all()}

        added = sorted(set(scan_by_path) - set(old_files))
        deleted = sorted(set(old_files) - set(scan_by_path))
        changed = sorted(
            path for path in set(scan_by_path) & set(old_files)
            if self._file_changed(old_files[path], scan_by_path[path])
        )
        unchanged = sorted(set(scan_by_path) - set(added) - set(changed))
        refreshed_paths = set(added) | set(changed)
        removed_paths = set(deleted)

        old_file_ids = {old_files[path].id for path in refreshed_paths | removed_paths if path in old_files}
        old_symbol_ids: set[str] = set()
        impacted_source_file_ids: set[str] = set()
        if old_file_ids:
            old_symbols_result = await self.db.execute(
                select(CodeSymbol.id).where(CodeSymbol.file_id.in_(old_file_ids))
            )
            old_symbol_ids = set(old_symbols_result.scalars().all())
            if old_symbol_ids:
                incoming_result = await self.db.execute(
                    select(CodeRelationship.source_file_id).where(
                        CodeRelationship.repository_id == self.repository_id,
                        CodeRelationship.target_symbol_id.in_(old_symbol_ids),
                    )
                )
                impacted_source_file_ids = set(incoming_result.scalars().all()) - old_file_ids

        # Remove stale links before their symbol IDs disappear. Reparse changed
        # sources plus unchanged callers whose target symbol was invalidated.
        stale_conditions = []
        if old_file_ids:
            stale_conditions.append(CodeRelationship.source_file_id.in_(old_file_ids))
        if old_symbol_ids:
            stale_conditions.extend((
                CodeRelationship.source_symbol_id.in_(old_symbol_ids),
                CodeRelationship.target_symbol_id.in_(old_symbol_ids),
            ))
        if stale_conditions:
            await self.db.execute(delete(CodeRelationship).where(
                CodeRelationship.repository_id == self.repository_id,
                or_(*stale_conditions),
            ))
        if old_file_ids:
            await self.db.execute(delete(CodeSymbol).where(CodeSymbol.file_id.in_(old_file_ids)))
            await self.db.execute(delete(CodeImport).where(CodeImport.file_id.in_(old_file_ids)))

        if old_file_ids:
            await self.db.execute(
                update(RepositoryFile)
                .where(RepositoryFile.id.in_(old_file_ids))
                .values(sha256_hash=None, ast_parsed=False)
            )

        file_by_path: dict[str, RepositoryFile] = {}
        for path, file_data in scan_by_path.items():
            record = old_files.get(path)
            if record is None:
                record = RepositoryFile(repository_id=self.repository_id, relative_path=path)
                self.db.add(record)
            if path in refreshed_paths:
                self._update_file_record(record, file_data)
            file_by_path[path] = record

        for path in deleted:
            await self.db.delete(old_files[path])
        await self.db.flush()

        pending_relationships: list[dict[str, Any]] = []
        parse_paths = refreshed_paths
        if impacted_source_file_ids:
            impacted_result = await self.db.execute(
                select(RepositoryFile).where(
                    RepositoryFile.repository_id == self.repository_id,
                    RepositoryFile.id.in_(impacted_source_file_ids),
                )
            )
            parse_paths |= {item.relative_path.replace("\\", "/") for item in impacted_result.scalars().all()}

        changed_symbol_names: set[str] = set()
        for path in sorted(parse_paths):
            file_record = file_by_path.get(path)
            if file_record is None or file_record.is_binary or file_record.size_bytes > 2 * 1024 * 1024:
                continue
            full_path = (root / path).resolve()
            try:
                full_path.relative_to(root)
            except ValueError:
                logger.warning("Skipping repository path outside root during reindex: %s", path)
                continue
            if not full_path.is_file():
                continue
            try:
                content = full_path.read_text(encoding="utf-8", errors="ignore")
                parsed = parse_polyglot_file(content, file_record.language)
            except (OSError, ValueError, UnicodeError) as exc:
                logger.warning("Could not parse %s during reindex: %s", path, exc)
                if path in refreshed_paths:
                    file_record.ast_parsed = False
                continue

            if path in refreshed_paths:
                file_record.ast_parsed = bool(parsed.get("ast_parsed", False))
                for symbol in parsed.get("symbols", []):
                    changed_symbol_names.add(symbol.get("name", ""))
                    existing = await self.db.execute(
                        select(CodeSymbol).where(
                            CodeSymbol.repository_id == self.repository_id,
                            CodeSymbol.file_id == file_record.id,
                            CodeSymbol.start_line == symbol["start_line"],
                        )
                    )
                    existing_symbol = existing.scalar_one_or_none()
                    if existing_symbol is not None:
                        for field, value in (
                            ("name", symbol["name"]),
                            ("qualified_name", symbol["qualified_name"]),
                            ("symbol_type", symbol["symbol_type"]),
                            ("end_line", symbol["end_line"]),
                            ("signature", symbol["signature"]),
                            ("docstring", symbol.get("docstring")),
                            ("parameters", symbol.get("parameters", [])),
                            ("return_type", symbol.get("return_type")),
                            ("complexity_score", symbol.get("complexity_score", 1)),
                            ("is_exported", symbol.get("is_exported", True)),
                        ):
                            setattr(existing_symbol, field, value)
                    else:
                        self.db.add(CodeSymbol(
                            repository_id=self.repository_id,
                            file_id=file_record.id,
                            name=symbol["name"],
                            qualified_name=symbol["qualified_name"],
                            symbol_type=symbol["symbol_type"],
                            start_line=symbol["start_line"],
                            end_line=symbol["end_line"],
                            signature=symbol["signature"],
                            docstring=symbol.get("docstring"),
                            parameters=symbol.get("parameters", []),
                            return_type=symbol.get("return_type"),
                            complexity_score=symbol.get("complexity_score", 1),
                            is_exported=symbol.get("is_exported", True),
                        ))
                for imported in parsed.get("imports", []):
                    existing_import = await self.db.execute(
                        select(CodeImport).where(
                            CodeImport.repository_id == self.repository_id,
                            CodeImport.file_id == file_record.id,
                            CodeImport.line_number == imported["line_number"],
                        )
                    )
                    existing_import_row = existing_import.scalar_one_or_none()
                    if existing_import_row is not None:
                        existing_import_row.module_name = imported["module_name"]
                        existing_import_row.imported_symbols = imported.get("imported_symbols", [])
                        existing_import_row.is_standard_lib = imported.get("is_standard_lib", False)
                        existing_import_row.is_third_party = imported.get("is_third_party", True)
                    else:
                        self.db.add(CodeImport(
                            repository_id=self.repository_id,
                            file_id=file_record.id,
                            module_name=imported["module_name"],
                            imported_symbols=imported.get("imported_symbols", []),
                            is_standard_lib=imported.get("is_standard_lib", False),
                            is_third_party=imported.get("is_third_party", True),
                            line_number=imported["line_number"],
                        ))
            for relation in parsed.get("relationships", []):
                pending_relationships.append({"file_id": file_record.id, "relation": relation})

        await self.db.flush()
        symbol_result = await self.db.execute(
            select(CodeSymbol).where(CodeSymbol.repository_id == self.repository_id)
        )
        symbol_registry: dict[str, CodeSymbol] = {}
        for symbol in symbol_result.scalars().all():
            symbol_registry[symbol.qualified_name] = symbol
            symbol_registry[symbol.name] = symbol
        for item in pending_relationships:
            relation = item["relation"]
            source_symbol = symbol_registry.get(relation.get("source_name"))
            target_symbol = symbol_registry.get(relation.get("target_name"))
            self.db.add(CodeRelationship(
                repository_id=self.repository_id,
                source_symbol_id=source_symbol.id if source_symbol else None,
                target_symbol_id=target_symbol.id if target_symbol else None,
                source_file_id=item["file_id"],
                relationship_type=relation.get("relationship_type", "references"),
                evidence_line=relation.get("evidence_line", 1),
                evidence_text=relation.get("evidence_text"),
            ))

        # Folder and language rows are cheap aggregates; refresh them every
        # scan, while source parsing and symbol/index writes remain incremental.
        await self.db.execute(delete(CodeFolder).where(CodeFolder.repository_id == self.repository_id))
        await self.db.execute(delete(RepositoryLanguage).where(RepositoryLanguage.repository_id == self.repository_id))
        for folder in scan["folders"]:
            self.db.add(CodeFolder(
                repository_id=self.repository_id,
                relative_path=folder["relative_path"],
                folder_name=folder["folder_name"],
                parent_path=folder.get("parent_path"),
                depth=folder.get("depth", 0),
                file_count=folder.get("file_count", 0),
                total_size_bytes=folder.get("total_size_bytes", 0),
            ))
        for language in scan["language_details"]:
            self.db.add(RepositoryLanguage(
                repository_id=self.repository_id,
                language=language["language"],
                file_count=language["file_count"],
                line_count=language["line_count"],
                size_bytes=language["size_bytes"],
                percentage=language["percentage"],
            ))

        if any(Path(path).name.lower() in DEPENDENCY_MANIFESTS for path in refreshed_paths | removed_paths):
            await self.db.execute(delete(RepositoryDependency).where(
                RepositoryDependency.repository_id == self.repository_id
            ))
            for dependency in parse_project_dependencies(root):
                self.db.add(RepositoryDependency(
                    repository_id=self.repository_id,
                    package_name=dependency["package_name"],
                    version_spec=dependency.get("version_spec"),
                    ecosystem=dependency["ecosystem"],
                    is_dev=dependency.get("is_dev", False),
                    manifest_file=dependency.get("manifest_file"),
                ))

        git_head = self._git_head(root)
        if git_head != state.indexed_git_head:
            await self.db.execute(delete(GitCommit).where(GitCommit.repository_id == self.repository_id))
            for commit in extract_git_commits(root, max_commits=100):
                self.db.add(GitCommit(
                    repository_id=self.repository_id,
                    commit_hash=commit["commit_hash"],
                    author_name=commit["author_name"],
                    author_email=commit["author_email"],
                    committed_at=commit["committed_at"],
                    message=commit["message"],
                    files_changed=commit["files_changed"],
                    insertions=commit["insertions"],
                    deletions=commit["deletions"],
                ))
        state.indexed_git_head = git_head

        refreshed_rag_files = 0
        chunk_count = await self.db.scalar(
            select(func.count(RepositoryVectorChunk.id)).where(
                RepositoryVectorChunk.repository_id == self.repository_id
            )
        ) or 0
        if chunk_count and (refreshed_paths or removed_paths):
            refreshed_rag_files = await RepositoryIndexer(self.db, self.repository_id).reindex_paths(
                sorted(refreshed_paths | removed_paths)
            )

        symbol_count = await self.db.scalar(
            select(func.count(CodeSymbol.id)).where(CodeSymbol.repository_id == self.repository_id)
        ) or 0
        repo.total_files = scan["total_files"]
        repo.total_lines = scan["total_lines"]
        repo.total_size_bytes = scan["total_size_bytes"]
        repo.file_count_by_language = {item["language"]: item["file_count"] for item in scan["language_details"]}
        repo.total_symbols = symbol_count
        repo.status = "ready"
        repo.analysis_phase = "ready"
        repo.error_message = None
        repo.updated_at = datetime.now(timezone.utc)

        completed = datetime.now(timezone.utc)
        state.status = "ready"
        state.last_successful_at = completed
        state.last_error = None
        state.indexed_file_count = scan["total_files"]
        state.indexed_symbol_count = symbol_count
        state.last_added_files = len(added)
        state.last_updated_files = len(changed)
        state.last_deleted_files = len(deleted)
        state.last_unchanged_files = len(unchanged)
        await self.db.commit()

        return {
            "repository_id": self.repository_id,
            "status": state.status,
            "last_started_at": state.last_started_at,
            "last_successful_at": state.last_successful_at,
            "last_error": state.last_error,
            "indexed_file_count": state.indexed_file_count,
            "indexed_symbol_count": state.indexed_symbol_count,
            "last_added_files": state.last_added_files,
            "last_updated_files": state.last_updated_files,
            "last_deleted_files": state.last_deleted_files,
            "last_unchanged_files": state.last_unchanged_files,
            "indexed_git_head": state.indexed_git_head,
            "added_files": len(added),
            "updated_files": len(changed),
            "deleted_files": len(deleted),
            "unchanged_files": len(unchanged),
            "refreshed_relationship_files": len(parse_paths),
            "refreshed_rag_files": refreshed_rag_files,
        }

    @staticmethod
    def _file_changed(record: RepositoryFile, data: dict[str, Any]) -> bool:
        if record.sha256_hash and data.get("sha256_hash"):
            return record.sha256_hash != data["sha256_hash"]
        return any((
            record.size_bytes != data.get("size_bytes"),
            record.line_count != data.get("line_count"),
            record.language != data.get("language"),
            record.is_binary != data.get("is_binary"),
        ))

    @staticmethod
    def _update_file_record(record: RepositoryFile, data: dict[str, Any]) -> None:
        for field in (
            "relative_path", "file_name", "file_extension", "language", "size_bytes",
            "line_count", "is_binary", "is_test", "is_config", "is_documentation", "sha256_hash",
        ):
            setattr(record, field, data.get(field))
        record.ast_parsed = False

    @staticmethod
    def _git_head(root: Path) -> str | None:
        try:
            from git import Repo

            return Repo(root, search_parent_directories=False).head.commit.hexsha
        except Exception:
            return None
