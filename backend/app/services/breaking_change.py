"""
API Breaking Change Detector
------------------------------
Detects breaking changes in public APIs by comparing:
  - Current indexed symbol signatures against a previous snapshot (diff-based)
  - Route parameter additions / removals
  - Return type / schema changes (inferred from docstrings + signatures)
  - Removed or renamed public symbols

Classification:
  BREAKING   — removed or renamed symbol, added required parameter, changed return type
  COMPATIBLE — added optional parameter, added new symbol, doc-only change
  UNKNOWN    — signature changed but details unclear
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import CodeSymbol, Repository, RepositoryFile


# ── Output schema ──────────────────────────────────────────────────────────────


class BreakingChangeItem(BaseModel):
    symbol: str
    file: str
    line: Optional[int] = None
    change_type: str          # breaking | compatible | unknown
    category: str             # removed | renamed | signature | return_type | new_param_required | new_param_optional | new_symbol
    description: str
    before: Optional[str] = None   # old signature / value
    after: Optional[str] = None    # new signature / value
    severity: str = "high"         # high | medium | low


class BreakingChangeResponse(BaseModel):
    repository_id: str
    breaking_changes: List[BreakingChangeItem] = Field(default_factory=list)
    compatible_changes: List[BreakingChangeItem] = Field(default_factory=list)
    unknown_changes: List[BreakingChangeItem] = Field(default_factory=list)
    total_breaking: int = 0
    total_compatible: int = 0
    summary: str
    limitations: List[str] = Field(default_factory=list)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _parse_params(signature: str) -> List[str]:
    """Extract parameter names from a function signature string."""
    match = re.search(r"\(([^)]*)\)", signature)
    if not match:
        return []
    raw = match.group(1)
    params = []
    for part in raw.split(","):
        part = part.strip()
        if not part or part in {"self", "cls", "*", "**kwargs", "*args"}:
            continue
        # Strip type annotations and defaults
        name = part.split(":")[0].split("=")[0].strip().lstrip("*")
        if name:
            params.append(name)
    return params


def _has_default(signature: str, param: str) -> bool:
    """Return True if param appears with a default value in the signature."""
    pattern = rf"\b{re.escape(param)}\s*(?::[^,)=]+)?\s*="
    return bool(re.search(pattern, signature))


def _extract_return_type(signature: str) -> Optional[str]:
    """Extract return type annotation from a signature, e.g. `-> str`."""
    match = re.search(r"->\s*([^\n:]+)", signature)
    return match.group(1).strip() if match else None


# ── Service ────────────────────────────────────────────────────────────────────


class BreakingChangeService:
    """
    Compare a previous symbol snapshot against the current indexed state.

    The ``previous_snapshot`` argument is a list of dicts with keys:
      name, qualified_name, signature, return_type, parameters
    These should come from a prior index run (e.g. stored in the DB or diff).

    If no snapshot is provided, the service falls back to analysing the current
    diff text for heuristic breaking-change indicators.
    """

    def __init__(self, db: AsyncSession, repository: Repository):
        self.db = db
        self.repository = repository

    async def analyze(
        self,
        previous_snapshot: Optional[List[Dict[str, Any]]] = None,
        diff: Optional[str] = None,
        focus_files: Optional[List[str]] = None,
    ) -> BreakingChangeResponse:
        # Load current symbols
        stmt = select(CodeSymbol, RepositoryFile.relative_path).join(
            RepositoryFile, CodeSymbol.file_id == RepositoryFile.id
        ).where(CodeSymbol.repository_id == self.repository.id)

        if focus_files:
            stmt = stmt.where(
                RepositoryFile.relative_path.in_(focus_files)
            )

        res = await self.db.execute(stmt)
        current_symbols: Dict[str, Dict[str, Any]] = {}
        for sym, rel_path in res.all():
            current_symbols[sym.qualified_name] = {
                "name": sym.name,
                "qualified_name": sym.qualified_name,
                "signature": sym.signature or "",
                "return_type": sym.return_type,
                "parameters": sym.parameters or [],
                "file": rel_path,
                "line": sym.start_line,
                "is_exported": sym.is_exported,
                "symbol_type": sym.symbol_type,
            }

        breaking: List[BreakingChangeItem] = []
        compatible: List[BreakingChangeItem] = []
        unknown: List[BreakingChangeItem] = []

        if previous_snapshot:
            prev_by_qname = {s["qualified_name"]: s for s in previous_snapshot}

            # Detect removed and changed symbols
            for qname, prev in prev_by_qname.items():
                curr = current_symbols.get(qname)

                if curr is None:
                    # Symbol was removed
                    breaking.append(
                        BreakingChangeItem(
                            symbol=qname,
                            file=prev.get("file", ""),
                            change_type="breaking",
                            category="removed",
                            description=f"`{qname}` was removed from the public API.",
                            before=prev.get("signature"),
                            severity="high",
                        )
                    )
                    continue

                # Compare signatures
                prev_sig = prev.get("signature") or ""
                curr_sig = curr.get("signature") or ""

                if prev_sig and curr_sig and prev_sig != curr_sig:
                    prev_params = _parse_params(prev_sig)
                    curr_params = _parse_params(curr_sig)

                    removed_params = [p for p in prev_params if p not in curr_params]
                    added_params = [p for p in curr_params if p not in prev_params]

                    if removed_params:
                        breaking.append(
                            BreakingChangeItem(
                                symbol=qname,
                                file=curr["file"],
                                line=curr["line"],
                                change_type="breaking",
                                category="signature",
                                description=(
                                    f"Parameter(s) removed: {', '.join(removed_params)}. "
                                    "Callers passing these arguments will break."
                                ),
                                before=prev_sig,
                                after=curr_sig,
                                severity="high",
                            )
                        )
                    elif added_params:
                        # Required new param = breaking; optional = compatible
                        required_new = [p for p in added_params if not _has_default(curr_sig, p)]
                        optional_new = [p for p in added_params if _has_default(curr_sig, p)]
                        if required_new:
                            breaking.append(
                                BreakingChangeItem(
                                    symbol=qname,
                                    file=curr["file"],
                                    line=curr["line"],
                                    change_type="breaking",
                                    category="new_param_required",
                                    description=(
                                        f"New required parameter(s) added: {', '.join(required_new)}. "
                                        "Existing callers without these arguments will break."
                                    ),
                                    before=prev_sig,
                                    after=curr_sig,
                                    severity="high",
                                )
                            )
                        if optional_new:
                            compatible.append(
                                BreakingChangeItem(
                                    symbol=qname,
                                    file=curr["file"],
                                    line=curr["line"],
                                    change_type="compatible",
                                    category="new_param_optional",
                                    description=f"New optional parameter(s) added: {', '.join(optional_new)}.",
                                    before=prev_sig,
                                    after=curr_sig,
                                    severity="low",
                                )
                            )
                    else:
                        unknown.append(
                            BreakingChangeItem(
                                symbol=qname,
                                file=curr["file"],
                                line=curr["line"],
                                change_type="unknown",
                                category="signature",
                                description="Signature changed but param-level diff is unclear.",
                                before=prev_sig,
                                after=curr_sig,
                                severity="medium",
                            )
                        )

                # Return type changes
                prev_rt = prev.get("return_type")
                curr_rt = curr.get("return_type")
                if prev_rt and curr_rt and prev_rt != curr_rt:
                    breaking.append(
                        BreakingChangeItem(
                            symbol=qname,
                            file=curr["file"],
                            line=curr["line"],
                            change_type="breaking",
                            category="return_type",
                            description=f"Return type changed from `{prev_rt}` to `{curr_rt}`.",
                            before=prev_rt,
                            after=curr_rt,
                            severity="medium",
                        )
                    )

            # Newly added symbols — always compatible
            for qname, curr in current_symbols.items():
                if qname not in prev_by_qname and curr.get("is_exported"):
                    compatible.append(
                        BreakingChangeItem(
                            symbol=qname,
                            file=curr["file"],
                            line=curr["line"],
                            change_type="compatible",
                            category="new_symbol",
                            description=f"New public symbol `{qname}` added.",
                            after=curr.get("signature"),
                            severity="low",
                        )
                    )

        elif diff:
            # Heuristic diff-based analysis when no snapshot is available
            breaking, compatible, unknown = self._analyze_diff(diff, current_symbols)
        else:
            # No previous snapshot or diff — return info-only findings
            for qname, s in list(current_symbols.items())[:5]:
                unknown.append(
                    BreakingChangeItem(
                        symbol=qname,
                        file=s["file"],
                        line=s["line"],
                        change_type="unknown",
                        category="signature",
                        description="No previous snapshot provided; provide diff or snapshot for accurate detection.",
                        severity="low",
                    )
                )

        total_breaking = len(breaking)
        summary = (
            f"Detected {total_breaking} breaking change(s) and {len(compatible)} compatible change(s)."
            if total_breaking
            else f"No breaking changes detected. {len(compatible)} compatible change(s) found."
        )

        return BreakingChangeResponse(
            repository_id=self.repository.id,
            breaking_changes=breaking,
            compatible_changes=compatible,
            unknown_changes=unknown,
            total_breaking=total_breaking,
            total_compatible=len(compatible),
            summary=summary,
            limitations=[
                "Comparison requires a previous symbol snapshot; provide it via the request body for accurate results.",
                "Heuristic diff analysis may miss signature changes in complex or multi-line definitions.",
                "Return-type inference is based on type annotation strings only; structural types are not deeply compared.",
            ],
        )

    @staticmethod
    def _analyze_diff(
        diff: str, current_symbols: Dict[str, Dict[str, Any]]
    ) -> tuple[List[BreakingChangeItem], List[BreakingChangeItem], List[BreakingChangeItem]]:
        """Heuristic analysis when only a diff is available (no previous snapshot)."""
        breaking: List[BreakingChangeItem] = []
        compatible: List[BreakingChangeItem] = []
        unknown: List[BreakingChangeItem] = []

        # Removed def / class lines
        removed_defs = re.findall(r"^-\s*(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)", diff, re.MULTILINE)
        added_defs = re.findall(r"^\+\s*(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)", diff, re.MULTILINE)
        added_names = {n for n, _ in added_defs}

        for name, params in removed_defs:
            if name.startswith("_"):
                continue
            curr = next((s for s in current_symbols.values() if s["name"] == name), None)
            if name not in added_names:
                breaking.append(
                    BreakingChangeItem(
                        symbol=name,
                        file=curr["file"] if curr else "",
                        line=curr["line"] if curr else None,
                        change_type="breaking",
                        category="removed",
                        description=f"Public function/method `{name}` was removed from the diff.",
                        before=f"def {name}({params})",
                        severity="high",
                    )
                )
            else:
                unknown.append(
                    BreakingChangeItem(
                        symbol=name,
                        file=curr["file"] if curr else "",
                        line=curr["line"] if curr else None,
                        change_type="unknown",
                        category="signature",
                        description=f"`{name}` signature was changed in the diff.",
                        severity="medium",
                    )
                )

        for name, params in added_defs:
            if name.startswith("_"):
                continue
            curr = next((s for s in current_symbols.values() if s["name"] == name), None)
            if name not in {n for n, _ in removed_defs}:
                compatible.append(
                    BreakingChangeItem(
                        symbol=name,
                        file=curr["file"] if curr else "",
                        line=curr["line"] if curr else None,
                        change_type="compatible",
                        category="new_symbol",
                        description=f"New public function `{name}` added.",
                        after=f"def {name}({params})",
                        severity="low",
                    )
                )

        return breaking, compatible, unknown
