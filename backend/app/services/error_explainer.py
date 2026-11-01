"""
Error Explainer Service
---------------------
Maps repository errors to indexed files, classifies them, and provides
human-readable explanations — without executing the failing code.

This service works alongside :class:`test_failure_explainer.TestFailureExplainerService`
which handles pytest/unittest output. This service handles runtime errors,
import failures, and other execution errors that occur during repository
operation, mapping them back to the indexed source files and symbols.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import CodeSymbol, Repository, RepositoryFile, ErrorLog
from app.services.code_search_dataset import CodeSearchDatasetService, CodeSnippet


# ── Schemas ───────────────────────────────────────────────────────────────────


class FailureEvidence(BaseModel):
    """A file location + optional line number extracted from an error trace."""
    file: str = ""
    line: Optional[int] = None
    snippet: str = ""


class ErrorExplanation(BaseModel):
    """Explanation of a single error occurrence."""

    error_type: str
    error_message: str
    summary: str
    likely_cause: str
    suggested_fix: str
    confidence: str = "medium"  # low | medium | high
    evidence: List[FailureEvidence] = Field(default_factory=list)
    source_symbol: Optional[str] = None
    source_symbol_file: Optional[str] = None
    code_example: Optional[CodeSnippet] = None


class ErrorHistoryEntry(BaseModel):
    """A single error entry from the history view."""

    id: str
    occurred_at: str
    error_type: str
    error_message: str
    file_path: Optional[str]
    resolved: bool
    resolution_notes: Optional[str] = None


class RepositoryErrorSummary(BaseModel):
    repository_id: str
    total_errors: int
    resolved_errors: int
    unresolved_errors: int
    by_type: Dict[str, int]
    recent_errors: List[ErrorHistoryEntry]
    summary: str



# ── Internals ─────────────────────────────────────────────────────────────────


def _normalize_path(value: str) -> str:
    """Normalize a file path for DB comparison (backslashes → forward, casefold)."""
    return value.replace("\\", "/").strip("/").casefold()


def _classify_error(error_type: str, error_message: str) -> tuple[str, tuple[str, str]]:
    """Classify an error into a category and generate likely cause + suggested fix."""

    text = (error_type + ":" + error_message).lower()

    # Import-related
    if any(kw in text for kw in ["modulenotfounderror", "importerror", "no module named"]):
        return "import", (
            "A required module could not be found.",
            "Verify the import path, install the dependency, or check that the module "
            "exists in the indexed repository.",
        )

    # Syntax-related
    if any(kw in text for kw in ["syntaxerror", "indentationerror", "unexpected indent"]):
        return "syntax", (
            "A Python syntax error prevents parsing the file.",
            "Fix the reported syntax error at the cited line and re-run.",
        )

    # Timeout-related
    if "timeout" in text:
        return "timeout", (
            "The operation exceeded its time budget.",
            "Check for blocking I/O, unbounded loops, or recursive calls without a base case.",
        )

    # Permission-related
    if any(kw in text for kw in ["permissionerror", "access is denied", "not authorized"]):
        return "permission", (
            "The execution lacks filesystem or network permission.",
            "Adjust sandbox permissions or use a temporary directory the process can write to.",
        )

    # Name error (undefined variable)
    if "nameerror" in text or "undefined name" in text:
        return "name", (
            "An undefined name or variable was referenced.",
            "Verify the variable is defined in the current scope or imported correctly.",
        )

    # Attribute error
    if "attributeerror" in text:
        return "attribute", (
            "An object does not have the expected attribute or method.",
            "Check the object type and ensure the attribute/method exists before access.",
        )

    # Key error
    if "keyerror" in text:
        return "key", (
            "A dictionary key was not found.",
            "Verify the key exists before accessing it, or use .get() with a default.",
        )

    # Value error
    if "valueerror" in text:
        return "value", (
            "An invalid value was passed to a function or constructor.",
            "Validate input before passing it; check expected types and ranges.",
        )

    # Runtime/other
    return "runtime", (
        "A runtime error occurred.",
        "Review the full stack trace and fix the underlying issue in the cited file/line.",
    )


# ── Service ───────────────────────────────────────────────────────────────────


class ErrorExplainerService:
    """Explain repository errors and map them to indexed source files."""

    def __init__(self, db: AsyncSession, repository: Repository):
        self.db = db
        self.repository = repository
        self.code_search = CodeSearchDatasetService()

    async def explain_error(
        self, error_type: str, error_message: str, file_path: Optional[str] = None, context: Optional[Dict[str, Any]] = None
    ) -> ErrorExplanation:
        """Explain a single error and map evidence to indexed symbols."""

        _category, (likely_cause, suggested_fix) = _classify_error(error_type, error_message or "")

        # Extract evidence (file locations) from the error message / traceback
        evidence = self._extract_evidence(error_message or "", file_path)

        # Map first evidence location back to an indexed symbol
        source_symbol, source_symbol_file = await self._map_to_symbol(evidence)

        # Get a code example for this error type from the dataset
        code_example = None
        try:
            code_example = await self.code_search.get_error_fix_example(
                error_type=error_type,
                file_path=file_path,
            )
        except Exception:
            pass  # Dataset unavailable, skip example

        # Build a summary
        summary = f"Error [{error_type}]: {likely_cause}"

        return ErrorExplanation(
            error_type=error_type,
            error_message=error_message or "",
            summary=summary,
            likely_cause=likely_cause,
            suggested_fix=suggested_fix,
            confidence="high" if evidence else "medium",
            evidence=evidence,
            source_symbol=source_symbol,
            source_symbol_file=source_symbol_file,
            code_example=code_example,
        )

    def _extract_evidence(self, error_message: str, explicit_file: Optional[str] = None) -> List[FailureEvidence]:
        """Extract file:line evidence from a traceback or error message."""

        evidence: List[FailureEvidence] = []
        seen: set[tuple[str, int]] = set()

        # Regex for "File \"path\", line N" locations
        for match in re.finditer(r'File "(?P<file>[^"]+)",\s+line\s+(?P<line>\d+),\s+in\s+\S+', error_message):
            file_path = match.group("file")
            line_no = int(match.group("line"))
            key = (file_path, line_no)
            if key in seen:
                continue
            seen.add(key)
            evidence.append(FailureEvidence(file=file_path, line=line_no))
            if len(evidence) >= 5:
                break

        # If an explicit file was provided (e.g. from the caller), add it
        if explicit_file and not any(e.file == explicit_file for e in evidence):
            evidence.insert(0, FailureEvidence(file=explicit_file, line=None))

        # Fallback: first line that looks like a file path (contains .py or .js etc.)
        if not evidence:
            for line in error_message.splitlines():
                if line.strip().endswith((".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yml", ".yaml")):
                    evidence.append(FailureEvidence(file=line.strip(), line=None))
                    break

        return evidence

    async def _map_to_symbol(self, evidence: List[FailureEvidence]) -> tuple[Optional[str], Optional[str]]:
        """Map evidence locations to indexed CodeSymbol entries."""
        for item in evidence:
            if not item.file:
                continue
            normalized = item.file.replace("\\", "/")
            # Match by suffix so absolute sandbox paths still resolve
            file_result = await self.db.execute(
                select(RepositoryFile).where(
                    RepositoryFile.repository_id == self.repository.id,
                    RepositoryFile.relative_path.like(f"%{normalized.lstrip('/')}"),
                )
            )
            file_obj = file_result.scalars().first()
            if not file_obj:
                continue
            symbol_result = await self.db.execute(
                select(CodeSymbol).where(
                    CodeSymbol.repository_id == self.repository.id,
                    CodeSymbol.file_id == file_obj.id,
                ).order_by(CodeSymbol.start_line.asc())
            )
            symbols = symbol_result.scalars().all()
            if not symbols:
                continue
            if item.line:
                containing = [
                    s for s in symbols if s.start_line <= item.line <= s.end_line
                ]
                if containing:
                    return containing[0].name, file_obj.relative_path
            # Return the first symbol in the file as fallback
            return symbols[0].name, file_obj.relative_path
        return None, None

    async def log_error(
        self,
        error_type: str,
        error_message: str,
        file_path: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ErrorLog:
        """Persist an error log entry and return the stored record."""
        from app.models.repository import ErrorLog as ErrorLogModel

        error_log = ErrorLogModel(
            repository_id=self.repository.id,
            file_path=file_path,
            error_type=error_type,
            error_message=error_message or "",
            context=context or {},
        )
        self.db.add(error_log)
        await self.db.commit()
        await self.db.refresh(error_log)
        return error_log

    async def get_error_history(
        self,
        resolved: Optional[bool] = None,
    ) -> List[ErrorHistoryEntry]:
        """Retrieve error history for this repository, optionally filtered."""

        query = select(ErrorLog).where(ErrorLog.repository_id == self.repository.id)
        if resolved is not None:
            query = query.where(ErrorLog.resolved == resolved)
        query = query.order_by(ErrorLog.occurred_at.desc())
        res = await self.db.execute(query)
        rows = res.scalars().all()

        result: List[ErrorHistoryEntry] = []
        for row in rows:
            result.append(
                ErrorHistoryEntry(
                    id=row.id,
                    occurred_at=row.occurred_at.isoformat() if row.occurred_at else "",
                    error_type=row.error_type,
                    error_message=row.error_message,
                    file_path=row.file_path,
                    resolved=row.resolved,
                    resolution_notes=row.resolution_notes,
                )
            )
        return result

    async def get_summary(self) -> RepositoryErrorSummary:
        """Generate a repository-level error summary."""

        # Total counts
        total_res = await self.db.scalar(
            select(func.count()).select_from(ErrorLog).where(ErrorLog.repository_id == self.repository.id)
        ) or 0
        resolved_res = await self.db.scalar(
            select(func.count()).select_from(ErrorLog).where(
                ErrorLog.repository_id == self.repository.id, ErrorLog.resolved == True
            )
        ) or 0
        unresolved = total_res - resolved_res

        # By type
        by_type_res = await self.db.execute(
            select(ErrorLog.error_type, func.count(ErrorLog.id))
            .where(ErrorLog.repository_id == self.repository.id)
            .group_by(ErrorLog.error_type)
        )
        by_type: Dict[str, int] = {row[0]: row[1] for row in by_type_res.all()}

        # Recent errors (last 10)
        recent = await self.get_error_history(resolved=None)
        recent_entries = [
            ErrorHistoryEntry(
                id=entry.id,
                occurred_at=entry.occurred_at,
                error_type=entry.error_type,
                error_message=entry.error_message[:200] if entry.error_message else "",
                file_path=entry.file_path,
                resolved=entry.resolved,
                resolution_notes=entry.resolution_notes,
            )
            for entry in recent[:10]
        ]

        # Summary text
        if total_res == 0:
            summary = "No errors have been logged for this repository."
        elif unresolved == 0:
            summary = f"All {total_res} error(s) have been resolved."
        elif resolved_res == 1:
            summary = f"1 error resolved, {unresolved} unresolved out of {total_res} total."
        else:
            summary = f"{resolved_res} errors resolved, {unresolved} unresolved out of {total_res} total."

        return RepositoryErrorSummary(
            repository_id=self.repository.id,
            total_errors=total_res,
            resolved_errors=resolved_res,
            unresolved_errors=unresolved,
            by_type=by_type,
            recent_errors=recent_entries,
            summary=summary,
        )