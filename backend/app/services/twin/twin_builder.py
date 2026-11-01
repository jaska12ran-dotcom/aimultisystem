import os
import shutil
import uuid
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.repository import (
    Repository,
    RepositoryFile,
    CodeFolder,
    CodeSymbol,
    CodeImport,
    Dependency,
    GitCommit,
    CodeRelationship,
)
from app.services.ingestion.scanner import scan_directory, parse_project_dependencies
from app.services.ingestion.archive import extract_zip_safely
from app.services.ingestion.git_cloner import clone_git_repository, extract_git_commits
from app.services.parser.polyglot_parser import parse_polyglot_file

class DigitalTwinBuilder:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_from_local(self, local_path: str, name: Optional[str] = None) -> Repository:
        resolved = Path(local_path).resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError(f"Path does not exist: {local_path}")

        repo_name = name or resolved.name or "local-repo"
        repo = Repository(
            name=repo_name,
            source_type="local",
            source_path=str(resolved),
            local_path=str(resolved),
            status="analyzing",
        )
        self.db.add(repo)
        await self.db.commit()
        await self.db.refresh(repo)

        try:
            await self._build_twin(repo)
        except Exception as e:
            repo.status = "failed"
            repo.error_message = str(e)
            await self.db.commit()
            raise

        return repo

    async def create_from_github(self, github_url: str, branch: Optional[str] = None, name: Optional[str] = None) -> Repository:
        # Determine name from URL
        clean_url = github_url.rstrip("/")
        repo_name = name or clean_url.split("/")[-1].replace(".git", "")
        repo_dir = Path(settings.REPOS_DIR) / f"github_{uuid.uuid4().hex[:8]}_{repo_name}"
        
        repo = Repository(
            name=repo_name,
            source_type="github",
            source_path=github_url,
            local_path=str(repo_dir),
            status="analyzing",
        )
        self.db.add(repo)
        await self.db.commit()
        await self.db.refresh(repo)

        try:
            clone_info = clone_git_repository(github_url, repo_dir, branch=branch)
            repo.default_branch = clone_info["default_branch"]
            await self._build_twin(repo)
        except Exception as e:
            repo.status = "failed"
            repo.error_message = str(e)
            await self.db.commit()
            raise

        return repo

    async def create_from_zip(self, zip_file_path: str, original_filename: str) -> Repository:
        clean_name = Path(original_filename).stem
        target_dir = Path(settings.REPOS_DIR) / f"zip_{uuid.uuid4().hex[:8]}_{clean_name}"
        
        repo = Repository(
            name=clean_name,
            source_type="zip",
            source_path=original_filename,
            local_path=str(target_dir),
            status="analyzing",
        )
        self.db.add(repo)
        await self.db.commit()
        await self.db.refresh(repo)

        try:
            extracted_dir, _ = extract_zip_safely(zip_file_path, target_dir)
            repo.local_path = extracted_dir
            await self._build_twin(repo)
        except Exception as e:
            repo.status = "failed"
            repo.error_message = str(e)
            await self.db.commit()
            raise

        return repo

    async def _build_twin(self, repo: Repository) -> None:
        local_dir = Path(repo.local_path)

        # 1. Scan filesystem for files & folders
        scan_result = scan_directory(local_dir)
        repo.languages = scan_result["languages"]
        repo.total_files = scan_result["total_files"]
        repo.total_lines = scan_result["total_lines"]

        # Persist folders
        for folder_data in scan_result["folders"]:
            cf = CodeFolder(
                repository_id=repo.id,
                relative_path=folder_data["relative_path"],
                folder_name=folder_data["folder_name"],
                parent_path=folder_data["parent_path"],
                file_count=folder_data["file_count"],
            )
            self.db.add(cf)

        # Persist files & track file mapping
        file_map: Dict[str, RepositoryFile] = {}
        for f_data in scan_result["files"]:
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
                sha256_hash=f_data["sha256_hash"],
            )
            self.db.add(rf)
            file_map[f_data["relative_path"]] = rf

        await self.db.flush()

        # 2. Extract declared dependencies
        deps_data = parse_project_dependencies(local_dir)
        for dep in deps_data:
            d = Dependency(
                repository_id=repo.id,
                package_name=dep["package_name"],
                version_spec=dep["version_spec"],
                ecosystem=dep["ecosystem"],
                is_dev=dep["is_dev"],
            )
            self.db.add(d)

        # 3. Extract Git commits if git history is present
        commits = extract_git_commits(local_dir)
        for c_data in commits:
            c = GitCommit(
                repository_id=repo.id,
                commit_hash=c_data["commit_hash"],
                author_name=c_data["author_name"],
                author_email=c_data["author_email"],
                committed_at=c_data["committed_at"],
                message=c_data["message"],
                files_changed=c_data["files_changed"],
                insertions=c_data["insertions"],
                deletions=c_data["deletions"],
            )
            self.db.add(c)

        # 4. AST and Static parsing of source code files
        total_symbols_count = 0
        symbol_registry: Dict[str, CodeSymbol] = {}  # symbol name -> persisted symbol
        pending_relationships = []

        for rel_path, rf in file_map.items():
            if rf.is_binary or rf.size_bytes > 2 * 1024 * 1024:  # Skip binaries and >2MB files
                continue

            full_path = local_dir / rel_path
            if not full_path.exists():
                continue

            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                parsed = parse_polyglot_file(content, rf.language)
                rf.ast_parsed = parsed.get("ast_parsed", False)

                # Persist symbols
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
                        docstring=sym["docstring"],
                        parameters=sym.get("parameters", []),
                        return_type=sym.get("return_type"),
                        complexity_score=sym.get("complexity_score", 1),
                        is_exported=sym.get("is_exported", True),
                    )
                    self.db.add(cs)
                    total_symbols_count += 1
                    symbol_registry[sym["qualified_name"]] = cs
                    symbol_registry[sym["name"]] = cs

                # Persist imports
                for imp in parsed.get("imports", []):
                    ci = CodeImport(
                        repository_id=repo.id,
                        file_id=rf.id,
                        module_name=imp["module_name"],
                        imported_symbols=imp["imported_symbols"],
                        is_standard_lib=imp["is_standard_lib"],
                        is_third_party=imp["is_third_party"],
                        line_number=imp["line_number"],
                    )
                    self.db.add(ci)

                # Collect file-level relationships
                for rel in parsed.get("relationships", []):
                    pending_relationships.append({
                        "file_id": rf.id,
                        "rel": rel,
                    })

            except Exception as e:
                # Log parser error on individual file without failing whole repo
                rf.ast_parsed = False

        await self.db.flush()

        # 5. Link relationships
        await self.db.flush()
        for item in pending_relationships:
            rf_id = item["file_id"]
            rel_info = item["rel"]
            source_symbol = symbol_registry.get(rel_info.get("source_name"))
            target_symbol = symbol_registry.get(rel_info.get("target_name"))

            cr = CodeRelationship(
                repository_id=repo.id,
                source_symbol_id=source_symbol.id if source_symbol else None,
                target_symbol_id=target_symbol.id if target_symbol else None,
                source_file_id=rf_id,
                relationship_type=rel_info.get("relationship_type", "references"),
                evidence_line=rel_info.get("evidence_line", 1),
                evidence_text=rel_info.get("evidence_text"),
            )
            self.db.add(cr)

        repo.total_symbols = total_symbols_count
        repo.status = "ready"
        repo.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(repo)
