"""
Test Failure Explainer
----------------------
Deterministic, dependency-free parsing of pytest/unittest output that explains
*why* tests failed and maps each failure back to indexed repository evidence.

No LLM is required: failures are extracted with structured regex parsing, then
classified into actionable categories (assertion / import / syntax / timeout /
collection / fixture / permission). Each explanation cites the failing test and
the traceback evidence rather than speculating.

This complements the self-healing agent: the explainer diagnoses, the healer
repairs.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import CodeSymbol, Repository, RepositoryFile


# ── Schemas ───────────────────────────────────────────────────────────────────


class FailureEvidence(BaseModel):
    file: str = ""
    line: Optional[int] = None
    snippet: str = ""


class TestFailureExplanation(BaseModel):
    test_name: str
    category: str                       # assertion | import | syntax | timeout | collection | fixture | permission | unknown
    summary: str
    likely_cause: str
    suggested_fix: str
    confidence: str = "medium"          # low | medium | high
    evidence: List[FailureEvidence] = Field(default_factory=list)
    source_symbol: Optional[str] = None
    source_symbol_file: Optional[str] = None


class TestFailureExplanationResponse(BaseModel):
    repository_id: str
    failures_found: int = 0
    explanations: List[TestFailureExplanation] = Field(default_factory=list)
    category_counts: Dict[str, int] = Field(default_factory=dict)
    summary: str = ""
    limitations: List[str] = Field(default_factory=list)


# ── Parser ────────────────────────────────────────────────────────────────────


_PYTEST_FAIL_HEADER = re.compile(
    r"^_+\s+(?P<name>.+?)\s+_+$", re.MULTILINE
)
_PYTEST_SHORT_LINE = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+):\s*(?P<kind>Error|Failed|Warning|Exception)(?:\s*[-:]\s*(?P<message>.*))?$",
    re.MULTILINE,
)
_PYTEST_E_LINE = re.compile(r"^(?:E\s+)(?P<message>.+)$", re.MULTILINE)
_TRACEBACK_LOCATION = re.compile(
    r'File "(?P<file>[^"]+)",\s+line\s+(?P<line>\d+),\s+in\s+(?P<func>\S+)'
)
_ASSERTION_LINE = re.compile(r"^E?\s*assert(?:ion)?\s*(?P<detail>.*)$", re.MULTILINE)


def _classify(traceback_text: str, short_kind: Optional[str]) -> str:
    text = traceback_text.lower()
    if "modulenotfounderror" in text or "importerror" in text or "no module named" in text:
        return "import"
    if "syntaxerror" in text or "indentationerror" in text:
        return "syntax"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "fixture" in text:
        return "fixture"
    if "permissionerror" in text or "access is denied" in text:
        return "permission"
    if "failed" in (short_kind or "").lower() or "assert" in text:
        return "assertion"
    if (short_kind or "").lower() == "error":
        return "collection"
    return "unknown"


_LIKELY_CAUSES: Dict[str, tuple[str, str]] = {
    "import": (
        "The test (or the module under test) imports a missing or renamed module.",
        "Verify the import path, install the dependency, or update the test import to the current module name.",
    ),
    "syntax": (
        "Python could not parse the file — likely a syntax or indentation error.",
        "Fix the reported syntax error at the cited line and re-run the test.",
    ),
    "timeout": (
        "The test exceeded its time budget — possibly a hang, deadlock, or unbounded loop.",
        "Add a timeout marker, check for blocking I/O, and bound any loops or waits.",
    ),
    "fixture": (
        "A pytest fixture required by the test could not be constructed.",
        "Check the fixture definition, its scope, and any missing setup/conftest resources.",
    ),
    "permission": (
        "The test execution lacks filesystem or network permission.",
        "Adjust sandbox permissions or use a temporary directory the test can write to.",
    ),
    "assertion": (
        "The tested behavior differs from the expectation encoded in the assert.",
        "Inspect the actual vs. expected values, then decide whether the code or the test is wrong.",
    ),
    "collection": (
        "pytest failed while collecting tests — the test module raised at import time.",
        "Reproduce the collection error directly and fix the module-level failure.",
    ),
    "unknown": (
        "The failure could not be classified from the available output.",
        "Reproduce the test locally and inspect the full traceback.",
    ),
}


class TestFailureExplainerService:
    """Explain failing tests from raw pytest/unittest output."""

    def __init__(self, db: AsyncSession, repository: Repository):
        self.db = db
        self.repository = repository

    async def explain(self, execution_output: str) -> TestFailureExplanationResponse:
        output = execution_output or ""
        blocks = self._split_failure_blocks(output)
        explanations: List[TestFailureExplanation] = []

        for block_name, block_text in blocks:
            category = _classify(block_text, self._short_kind(block_text))
            evidence = self._extract_evidence(block_text)
            cause, fix = _LIKELY_CAUSES[category]

            # Attempt to map the first test-file location back to an indexed symbol.
            source_symbol, source_symbol_file = await self._map_to_symbol(evidence)

            explanations.append(TestFailureExplanation(
                test_name=block_name,
                category=category,
                summary=self._summarize(category, block_name, block_text),
                likely_cause=cause,
                suggested_fix=fix,
                confidence="high" if evidence else "medium",
                evidence=evidence,
                source_symbol=source_symbol,
                source_symbol_file=source_symbol_file,
            ))

        counts: Dict[str, int] = {}
        for item in explanations:
            counts[item.category] = counts.get(item.category, 0) + 1

        if not explanations:
            summary = (
                "No parseable test failures were found in the provided output. "
                "If tests did fail, pass the complete pytest output including tracebacks."
            )
        else:
            breakdown = ", ".join(f"{count} {name}" for name, count in sorted(counts.items()))
            summary = f"Explained {len(explanations)} failing test(s): {breakdown}."

        return TestFailureExplanationResponse(
            repository_id=self.repository.id,
            failures_found=len(explanations),
            explanations=explanations,
            category_counts=counts,
            summary=summary,
            limitations=[
                "Explanations are derived from the provided console output only; "
                "they do not execute the failing tests.",
                "Category classification is heuristic and may misclassify unusual "
                "or custom error types.",
                "Symbol mapping relies on indexed files; failures in unindexed or "
                "generated files cannot be mapped.",
            ],
        )

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _split_failure_blocks(output: str) -> List[tuple[str, str]]:
        """Split pytest output into (test_name, block_text) per failure."""
        blocks: List[tuple[str, str]] = []
        matches = list(_PYTEST_FAIL_HEADER.finditer(output))
        if not matches:
            # unittest style: "FAIL: test_name (module.Class)"
            for match in re.finditer(r"^(?:FAIL|ERROR):\s+(?P<name>\S+).*$", output, re.MULTILINE):
                blocks.append((match.group("name"), output))
            return blocks

        for index, match in enumerate(matches):
            name = match.group("name").strip()
            # Skip pytest's "short test summary" banners.
            if name.lower().startswith("short test summary"):
                continue
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(output)
            blocks.append((name, output[start:end]))

        return blocks

    @staticmethod
    def _short_kind(block_text: str) -> Optional[str]:
        match = _PYTEST_SHORT_LINE.search(block_text)
        return match.group("kind") if match else None

    @staticmethod
    def _extract_evidence(block_text: str) -> List[FailureEvidence]:
        evidence: List[FailureEvidence] = []
        seen: set[tuple[str, int]] = set()

        for match in _TRACEBACK_LOCATION.finditer(block_text):
            file_path = match.group("file")
            line_no = int(match.group("line"))
            key = (file_path, line_no)
            if key in seen:
                continue
            seen.add(key)
            evidence.append(FailureEvidence(file=file_path, line=line_no))
            if len(evidence) >= 5:
                break

        # Capture assertion detail lines as snippet evidence.
        assertion = _ASSERTION_LINE.search(block_text)
        if assertion and evidence:
            evidence[-1].snippet = assertion.group(0).strip()[:200]
        elif assertion:
            evidence.append(FailureEvidence(snippet=assertion.group(0).strip()[:200]))

        # Fallback: first E-line message.
        if not evidence:
            e_line = _PYTEST_E_LINE.search(block_text)
            if e_line:
                evidence.append(FailureEvidence(snippet=e_line.group("message").strip()[:200]))

        return evidence

    async def _map_to_symbol(
        self, evidence: List[FailureEvidence]
    ) -> tuple[Optional[str], Optional[str]]:
        """Map an evidence location to an indexed symbol in that file."""
        for item in evidence:
            if not item.file:
                continue
            normalized = item.file.replace("\\", "/")
            # Match by suffix so absolute sandbox paths still resolve.
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
            return symbols[0].name, file_obj.relative_path
        return None, None

    @staticmethod
    def _summarize(category: str, test_name: str, block_text: str) -> str:
        if category == "assertion":
            assertion = _ASSERTION_LINE.search(block_text)
            detail = assertion.group("detail").strip()[:160] if assertion else ""
            return f"`{test_name}` failed an assertion. {detail}".strip()
        if category == "import":
            missing = re.search(r"No module named '?(?P<mod>[\w.]+)'?", block_text)
            target = f" (missing module: {missing.group('mod')})" if missing else ""
            return f"`{test_name}` could not run due to an import error{target}."
        if category == "syntax":
            return f"`{test_name}` could not run because a file failed to parse."
        if category == "timeout":
            return f"`{test_name}` exceeded its time budget."
        if category == "fixture":
            return f"`{test_name}` could not construct a required fixture."
        if category == "permission":
            return f"`{test_name}` hit a permission error during execution."
        if category == "collection":
            return f"`{test_name}` failed during test collection."
        return f"`{test_name}` failed with an unclassified error."
