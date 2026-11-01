import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from app.models.repository import (
    Repository,
    RepositoryFile,
    CodeSymbol,
    CodeRelationship,
    RepositoryDependency,
    RepositoryLanguage,
)

class ASTRetriever:
    """
    AST-Grounded Context Retriever.
    Provides structured, verified code context with line numbers and file paths.
    Eliminates LLM hallucinations by grounding generation directly in the digital twin database.
    """

    @staticmethod
    async def get_repository_overview(db: AsyncSession, repo_id: str) -> Dict[str, Any]:
        """Fetches full high-level architectural context for a repository."""
        repo = await db.get(Repository, repo_id)
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        # Languages
        lang_res = await db.execute(
            select(RepositoryLanguage)
            .where(RepositoryLanguage.repository_id == repo_id)
            .order_by(RepositoryLanguage.percentage.desc())
        )
        languages = [{"language": l.language, "percentage": l.percentage, "file_count": l.file_count} for l in lang_res.scalars().all()]

        # Dependencies
        dep_res = await db.execute(
            select(RepositoryDependency)
            .where(RepositoryDependency.repository_id == repo_id)
            .limit(50)
        )
        dependencies = [{"name": d.package_name, "version": d.version_spec, "ecosystem": d.ecosystem} for d in dep_res.scalars().all()]

        # Key API routes
        api_res = await db.execute(
            select(CodeSymbol, RepositoryFile.relative_path.label("file_path"))
            .join(RepositoryFile, RepositoryFile.id == CodeSymbol.file_id)
            .where(CodeSymbol.repository_id == repo_id, CodeSymbol.symbol_type == "api_route")
            .limit(30)
        )
        api_routes = [
            {
                "name": symbol.name,
                "file_path": file_path,
                "line_start": symbol.start_line,
                "signature": symbol.signature,
                "docstring": symbol.docstring,
            }
            for symbol, file_path in api_res.all()
        ]

        # Database models
        models_res = await db.execute(
            select(CodeSymbol, RepositoryFile.relative_path.label("file_path"))
            .join(RepositoryFile, RepositoryFile.id == CodeSymbol.file_id)
            .where(CodeSymbol.repository_id == repo_id, CodeSymbol.symbol_type == "db_model")
            .limit(30)
        )
        db_models = [
            {
                "name": symbol.name,
                "file_path": file_path,
                "line_start": symbol.start_line,
                "docstring": symbol.docstring,
            }
            for symbol, file_path in models_res.all()
        ]

        # Top classes & functions
        classes_res = await db.execute(
            select(CodeSymbol, RepositoryFile.relative_path.label("file_path"))
            .join(RepositoryFile, RepositoryFile.id == CodeSymbol.file_id)
            .where(CodeSymbol.repository_id == repo_id, CodeSymbol.symbol_type.in_(["class", "interface"]))
            .limit(30)
        )
        classes = [
            {
                "name": symbol.name,
                "file_path": file_path,
                "line_start": symbol.start_line,
                "signature": symbol.signature,
                "docstring": symbol.docstring,
            }
            for symbol, file_path in classes_res.all()
        ]

        return {
            "repository_name": repo.name,
            "source_type": repo.source_type,
            "total_files": repo.total_files,
            "total_lines": repo.total_lines,
            "languages": languages,
            "dependencies": dependencies,
            "api_routes": api_routes,
            "db_models": db_models,
            "classes": classes,
        }

    @staticmethod
    async def get_file_context(db: AsyncSession, repo_id: str, file_path: str) -> Optional[Dict[str, Any]]:
        """Retrieves exact file content and all AST symbols defined in that file."""
        repo = await db.get(Repository, repo_id)
        if not repo:
            return None

        # Normalize relative path
        norm_path = file_path.replace("\\", "/").strip("/")

        file_res = await db.execute(
            select(RepositoryFile).where(
                RepositoryFile.repository_id == repo_id,
                or_(
                    RepositoryFile.relative_path == norm_path,
                    RepositoryFile.relative_path.like(f"%{norm_path}"),
                )
            )
        )
        file_obj = file_res.scalars().first()
        if not file_obj:
            return None

        # Fetch symbols in this file
        symbols_res = await db.execute(
            select(CodeSymbol).where(
                CodeSymbol.repository_id == repo_id,
                CodeSymbol.file_id == file_obj.id,
            ).order_by(CodeSymbol.start_line.asc())
        )
        symbols = [
            {
                "name": s.name,
                "symbol_type": s.symbol_type,
                "line_start": s.line_start,
                "line_end": s.line_end,
                "signature": s.signature,
                "docstring": s.docstring,
            }
            for s in symbols_res.scalars().all()
        ]

        # Read actual file content safely from local workspace
        full_content = ""
        workspace_path = Path(repo.local_path)
        actual_file_path = workspace_path / file_obj.relative_path
        if actual_file_path.is_file() and str(actual_file_path.resolve()).startswith(str(workspace_path.resolve())):
            try:
                full_content = actual_file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                full_content = ""

        return {
            "relative_path": file_obj.relative_path,
            "language": file_obj.language,
            "lines": file_obj.line_count,
            "symbols": symbols,
            "content": full_content,
        }

    @staticmethod
    async def search_symbols(db: AsyncSession, repo_id: str, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        """Searches symbols matching query across names, docstrings, or signatures."""
        normalized_query = re.sub(r"[^A-Za-z0-9_]+", " ", query or "").strip()
        terms = [term for term in normalized_query.split() if len(term) > 1]
        if not terms:
            return []

        matches = []
        for term in terms[:5]:
            search_term = f"%{term}%"
            res = await db.execute(
                select(CodeSymbol, RepositoryFile.relative_path.label("file_path")).join(
                    RepositoryFile,
                    RepositoryFile.id == CodeSymbol.file_id,
                ).where(
                    CodeSymbol.repository_id == repo_id,
                    or_(
                        CodeSymbol.name.ilike(search_term),
                        CodeSymbol.docstring.ilike(search_term),
                        CodeSymbol.signature.ilike(search_term),
                        RepositoryFile.relative_path.ilike(search_term),
                    )
                ).limit(limit)
            )
            matches.extend(res.all())

        # Deduplicate by symbol identity while keeping the most relevant matches first.
        seen = set()
        results = []
        for symbol, file_path in matches:
            key = (symbol.repository_id, symbol.id)
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "name": symbol.name,
                "symbol_type": symbol.symbol_type,
                "file_path": file_path,
                "line_start": symbol.start_line,
                "line_end": symbol.end_line,
                "signature": symbol.signature,
                "docstring": symbol.docstring,
            })
            if len(results) >= limit:
                break
        return results
        return [
            {
                "name": symbol.name,
                "symbol_type": symbol.symbol_type,
                "file_path": file_path,
                "line_start": symbol.start_line,
                "line_end": symbol.end_line,
                "signature": symbol.signature,
                "docstring": symbol.docstring,
            }
            for symbol, file_path in res.all()
        ]
