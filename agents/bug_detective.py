"""
AI Bug Detective Agent
-----------------------
Given a bug description, error message, or stack trace, this agent:
  1. Searches the repository index for relevant files and symbols
  2. Traces call paths to the suspected root cause
  3. Identifies similar historical failures from Git commit history
  4. Produces a ranked list of suspect locations with evidence
  5. Optionally generates a minimal reproducible example (MRE)

No code is executed during investigation — all reasoning is over indexed data.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import (
    CodeRelationship,
    CodeSymbol,
    GitCommit,
    Repository,
    RepositoryFile,
)
from intelligence.retriever import ASTRetriever
from intelligence.llm_client import default_llm_client


# ── Output schemas ─────────────────────────────────────────────────────────────


class BugSuspect(BaseModel):
    file: str
    symbol: Optional[str] = None
    line: Optional[int] = None
    confidence: str = "medium"   # high | medium | low
    reason: str
    evidence_type: str           # stack_trace | git_history | relationship | keyword


class BugInvestigationResponse(BaseModel):
    repository_id: str
    query: str
    suspects: List[BugSuspect] = Field(default_factory=list)
    related_commits: List[Dict[str, Any]] = Field(default_factory=list)
    mre_sketch: Optional[str] = None
    root_cause_hypothesis: str = ""
    limitations: List[str] = Field(default_factory=list)


# ── Helpers ────────────────────────────────────────────────────────────────────


_RE_FILE_LINE = re.compile(r'File "([^"]+)",\s+line\s+(\d+)', re.MULTILINE)
_RE_AT_LINE = re.compile(r'at\s+\S+\s+\(([^:)]+):(\d+)\)', re.MULTILINE)
_RE_EXCEPTION = re.compile(
    r'((?:Error|Exception|Warning|Failure)[^\n:]*):?\s*([^\n]+)', re.MULTILINE
)


def _extract_stack_files(text: str) -> List[tuple[str, int]]:
    """Pull (filepath, line_number) pairs out of a Python / JS / Java stack trace."""
    hits = _RE_FILE_LINE.findall(text) + _RE_AT_LINE.findall(text)
    results = []
    for path, line in hits:
        try:
            results.append((path.replace("\\", "/"), int(line)))
        except ValueError:
            pass
    return results


def _extract_error_types(text: str) -> List[str]:
    return [m.group(1).strip() for m in _RE_EXCEPTION.finditer(text)]


def _normalize(s: str) -> str:
    return s.replace("\\", "/").strip("/").casefold()


# ── Agent ─────────────────────────────────────────────────────────────────────


class BugDetectiveAgent:
    """Investigate a bug description against an indexed repository."""

    def __init__(self, llm_client=default_llm_client):
        self.llm = llm_client

    async def investigate(
        self,
        db: AsyncSession,
        repo: Repository,
        bug_description: str,
        stack_trace: Optional[str] = None,
        generate_mre: bool = False,
    ) -> BugInvestigationResponse:
        full_text = (bug_description + "\n" + (stack_trace or "")).strip()

        # ── 1. Load indexed data ──────────────────────────────────────────────
        files_res = await db.execute(
            select(RepositoryFile).where(RepositoryFile.repository_id == repo.id)
        )
        files = files_res.scalars().all()
        file_by_id = {f.id: f for f in files}
        file_by_path = {_normalize(f.relative_path): f for f in files}

        symbols_res = await db.execute(
            select(CodeSymbol).where(CodeSymbol.repository_id == repo.id)
        )
        symbols = symbols_res.scalars().all()

        rels_res = await db.execute(
            select(CodeRelationship).where(CodeRelationship.repository_id == repo.id)
        )
        relationships = rels_res.scalars().all()

        commits_res = await db.execute(
            select(GitCommit)
            .where(GitCommit.repository_id == repo.id)
            .order_by(GitCommit.committed_at.desc())
            .limit(300)
        )
        commits = commits_res.scalars().all()

        suspects: List[BugSuspect] = []

        # ── 2. Stack trace analysis ───────────────────────────────────────────
        if stack_trace:
            stack_files = _extract_stack_files(stack_trace)
            for raw_path, line_num in stack_files:
                norm = _normalize(raw_path)
                # Find the best matching indexed file
                matched_file = file_by_path.get(norm)
                if not matched_file:
                    # Try suffix match
                    matched_file = next(
                        (f for k, f in file_by_path.items() if k.endswith(norm) or norm.endswith(k)),
                        None,
                    )
                if matched_file:
                    # Find symbol at this line
                    sym = next(
                        (
                            s for s in symbols
                            if s.file_id == matched_file.id
                            and s.start_line <= line_num <= s.end_line
                        ),
                        None,
                    )
                    suspects.append(
                        BugSuspect(
                            file=matched_file.relative_path,
                            symbol=sym.qualified_name if sym else None,
                            line=line_num,
                            confidence="high",
                            reason=f"Stack trace references this file at line {line_num}.",
                            evidence_type="stack_trace",
                        )
                    )

        # ── 3. Keyword / NL search ────────────────────────────────────────────
        search_terms = self._extract_search_terms(full_text)
        for term in search_terms[:6]:
            matched_syms = await ASTRetriever.search_symbols(db, repo.id, term, limit=5)
            for sym_data in matched_syms:
                file_path = sym_data.get("file_path") or ""
                suspects.append(
                    BugSuspect(
                        file=file_path,
                        symbol=sym_data.get("qualified_name") or sym_data.get("name"),
                        line=sym_data.get("line_start"),
                        confidence="medium",
                        reason=f"Symbol name matches keyword '{term}' extracted from bug description.",
                        evidence_type="keyword",
                    )
                )

        # ── 4. Relationship propagation (callers of suspects) ─────────────────
        suspect_symbol_ids = {
            s.symbol
            for s in suspects
            if s.symbol
        }
        sym_by_qname = {s.qualified_name: s for s in symbols}
        target_ids = {
            sym_by_qname[qn].id for qn in suspect_symbol_ids if qn in sym_by_qname
        }

        caller_count: dict[str, int] = defaultdict(int)
        for rel in relationships:
            if rel.target_symbol_id in target_ids and rel.source_symbol_id:
                caller_count[rel.source_symbol_id] += 1

        for sym_id, cnt in sorted(caller_count.items(), key=lambda x: -x[1])[:5]:
            sym = next((s for s in symbols if s.id == sym_id), None)
            if not sym:
                continue
            f = file_by_id.get(sym.file_id)
            if not f:
                continue
            suspects.append(
                BugSuspect(
                    file=f.relative_path,
                    symbol=sym.qualified_name,
                    line=sym.start_line,
                    confidence="low",
                    reason=f"Calls {cnt} suspect symbol(s); may propagate the bug.",
                    evidence_type="relationship",
                )
            )

        # ── 5. Git history: commits touching suspect files ────────────────────
        suspect_paths = {_normalize(s.file) for s in suspects if s.file}
        related_commits: List[Dict[str, Any]] = []
        for commit in commits:
            changed = {_normalize(str(p)) for p in (commit.files_changed or [])}
            if changed & suspect_paths:
                related_commits.append(
                    {
                        "commit_hash": commit.commit_hash,
                        "author": commit.author_name,
                        "message": (commit.message or "").splitlines()[0][:120],
                        "files_changed": list(commit.files_changed or [])[:10],
                    }
                )
                if len(related_commits) >= 10:
                    break

            # Surface bug-fix commits as additional suspects
            msg_lower = (commit.message or "").lower()
            if any(kw in msg_lower for kw in ("fix", "bug", "error", "crash", "revert")):
                for path in (commit.files_changed or []):
                    npath = _normalize(str(path))
                    f = file_by_path.get(npath)
                    if f and npath not in suspect_paths:
                        suspects.append(
                            BugSuspect(
                                file=f.relative_path,
                                line=None,
                                confidence="low",
                                reason=f"Git commit '{commit.commit_hash[:8]}' is a bug-fix touching this file: \"{(commit.message or '').splitlines()[0][:80]}\"",
                                evidence_type="git_history",
                            )
                        )

        # ── 6. Deduplicate & rank suspects ────────────────────────────────────
        suspects = self._deduplicate(suspects)

        # ── 7. Root cause hypothesis ──────────────────────────────────────────
        hypothesis = await self._hypothesize(full_text, suspects)

        # ── 8. Optional MRE sketch ────────────────────────────────────────────
        mre: Optional[str] = None
        if generate_mre and suspects:
            mre = await self._generate_mre(db, repo, full_text, suspects[:3])

        return BugInvestigationResponse(
            repository_id=repo.id,
            query=bug_description[:300],
            suspects=suspects[:20],
            related_commits=related_commits[:10],
            mre_sketch=mre,
            root_cause_hypothesis=hypothesis,
            limitations=[
                "Investigation is based on static indexed evidence; runtime state and environment variables are not visible.",
                "Stack-trace file paths are matched heuristically and may be wrong if paths differ between environments.",
                "Git history is limited to the commits indexed during ingestion.",
                "MRE sketch is a structural stub, not a guaranteed reproducing example.",
            ],
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _extract_search_terms(text: str) -> List[str]:
        """Pull likely code identifiers from bug text."""
        # CamelCase, snake_case, dotted names
        tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_.]{3,}\b", text)
        # Exclude common English words
        stop = {
            "this", "that", "with", "from", "have", "when", "then", "some",
            "none", "true", "false", "null", "error", "exception", "function",
            "class", "return", "import", "print", "line", "file",
        }
        seen = set()
        result = []
        for t in tokens:
            key = t.casefold()
            if key not in stop and key not in seen:
                seen.add(key)
                result.append(t)
        return result

    @staticmethod
    def _deduplicate(suspects: List[BugSuspect]) -> List[BugSuspect]:
        """Merge suspects with the same file+symbol, keeping the highest confidence."""
        rank = {"high": 3, "medium": 2, "low": 1}
        best: Dict[str, BugSuspect] = {}
        for s in suspects:
            key = f"{_normalize(s.file)}::{(s.symbol or '')}::{(s.line or '')}"
            existing = best.get(key)
            if existing is None or rank.get(s.confidence, 0) > rank.get(existing.confidence, 0):
                best[key] = s
        # Sort: high confidence first, then stack_trace evidence type first
        return sorted(
            best.values(),
            key=lambda s: (-rank.get(s.confidence, 0), s.evidence_type != "stack_trace"),
        )

    async def _hypothesize(
        self, bug_text: str, suspects: List[BugSuspect]
    ) -> str:
        if not suspects:
            return "No matching evidence found in the indexed repository for this bug description."

        top = suspects[:5]
        suspect_summary = "\n".join(
            f"- {s.file}" + (f" ({s.symbol})" if s.symbol else "")
            + f" [{s.confidence} confidence]: {s.reason}"
            for s in top
        )
        system = (
            "You are a senior software engineer doing root-cause analysis. "
            "Be concise. State the most likely root cause in 2-3 sentences."
        )
        user = (
            f"Bug: {bug_text[:600]}\n\n"
            f"Top suspect locations from repository analysis:\n{suspect_summary}\n\n"
            "What is the most likely root cause? Be specific about the code location."
        )
        try:
            result = await self.llm.generate(system, user, max_tokens=300, temperature=0.2)
            if result and result.strip():
                return result.strip()
        except Exception:
            pass

        # Deterministic fallback
        top_s = suspects[0]
        return (
            f"The most likely root cause is in `{top_s.file}`"
            + (f" at `{top_s.symbol}`" if top_s.symbol else "")
            + f" (line {top_s.line})" if top_s.line else ""
            + f". Reason: {top_s.reason}"
        )

    async def _generate_mre(
        self,
        db: AsyncSession,
        repo: Repository,
        bug_text: str,
        suspects: List[BugSuspect],
    ) -> str:
        """Generate a minimal reproducible example sketch."""
        imports: List[str] = []
        calls: List[str] = []

        for s in suspects:
            if s.symbol:
                module = s.file.replace("\\", "/").replace(".py", "").replace("/", ".")
                sym_name = s.symbol.split(".")[-1]
                imports.append(f"from {module} import {sym_name}")
                calls.append(
                    f"    # Call suspect: {s.symbol}\n"
                    f"    result = {sym_name}()  # fill in correct arguments\n"
                    f"    print(result)"
                )

        if not imports:
            return "# MRE could not be generated: no suspect symbols identified."

        mre_lines = [
            "# Minimal Reproducible Example (AI-generated sketch — verify before use)",
            "# This is a structural stub based on indexed repository evidence.",
            "",
        ] + list(dict.fromkeys(imports)) + [
            "",
            "def reproduce():",
        ] + (calls or ["    pass"]) + [
            "",
            "if __name__ == '__main__':",
            "    reproduce()",
        ]
        return "\n".join(mre_lines)
