"""
What-If Code Change Simulator Service
======================================
Orchestrates deterministic (AST + graph) and AI-predicted analysis
for a proposed code change, in an isolated simulation workspace.

SAFETY GUARANTEE: This service NEVER writes to or modifies the
original repository. All mutations happen in-memory or in a
temporary copy. No git commits, merges, or deployments are triggered.
"""
from __future__ import annotations

import ast
import difflib
import re
import textwrap
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import (
    CodeImport,
    CodeRelationship,
    CodeSymbol,
    Repository,
    RepositoryFile,
)
from app.schemas.whatif import (
    AffectedFile,
    AlternativeProposal,
    BreakingChangeEntry,
    ImpactedFunction,
    MigrationRequirement,
    PerformanceConcern,
    PredictedFinding,
    RegressionTestRecommendation,
    SecurityImplication,
    SourceLocation,
    TestFailureRisk,
    VerifiedFinding,
    WhatIfPatch,
    WhatIfRequest,
    WhatIfSimulationResult,
)

# ── Constants ──────────────────────────────────────────────────────────────────

CALL_RELS = {"calls", "inherits", "implements", "accesses", "references"}
TEST_RELS = {"tests"}

_SECURITY_PATTERNS: List[Tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"\beval\s*\(", re.I), "code_injection", "high",
     "eval() called with potentially user-controlled input — code injection risk."),
    (re.compile(r"\bexec\s*\(", re.I), "code_injection", "high",
     "exec() called — arbitrary code execution risk."),
    (re.compile(r"subprocess\.(run|Popen|call|check_output)", re.I), "command_injection", "high",
     "subprocess call detected — verify shell=False and input sanitisation."),
    (re.compile(r"password|secret|token|api_key|private_key", re.I), "secret_exposure", "medium",
     "Sensitive identifier detected in proposed code — avoid hardcoded secrets."),
    (re.compile(r"sql\s*=.*%s|f\"|f'.*select.*from", re.I), "sql_injection", "high",
     "Possible string-formatted SQL query — use parameterised queries."),
    (re.compile(r"pickle\.(load|loads)", re.I), "deserialization", "high",
     "pickle.load() deserializes arbitrary objects — dangerous with untrusted data."),
    (re.compile(r"random\.(random|randint|choice)", re.I), "weak_randomness", "low",
     "Non-cryptographic random used — use secrets module for security-sensitive values."),
    (re.compile(r"hashlib\.(md5|sha1)\b", re.I), "weak_hash", "medium",
     "Weak hash algorithm (MD5/SHA-1) — prefer SHA-256 or bcrypt for passwords."),
    (re.compile(r"open\s*\(.*['\"]w['\"]", re.I), "file_write", "low",
     "File opened for writing — ensure the path is not user-controlled."),
]

_PERF_PATTERNS: List[Tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"for\s+\w+\s+in\s+\w+.*:\s*\n.*\.query\(|\.filter\(|\.get\(", re.I | re.M),
     "n_plus_1", "high", "Database query inside a loop — N+1 query risk."),
    (re.compile(r"time\.sleep\s*\(", re.I), "io_blocking", "medium",
     "Synchronous sleep in async context or hot path — prefer asyncio.sleep."),
    (re.compile(r"\.append\(\)|list\(\)|sum\(\).*for.*in", re.I),
     "list_rebuild", "low", "Repeated list construction in loop — consider generator or pre-allocation."),
    (re.compile(r"global\s+\w+", re.I), "global_state", "medium",
     "Global variable mutation — concurrency and caching risks."),
    (re.compile(r"import\s+(numpy|pandas|torch|tensorflow)", re.I),
     "heavy_import", "low", "Heavy library import at module level — consider lazy import."),
]

_MIGRATION_PATTERNS: List[Tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"__tablename__|Column\s*\(|sa\.(Column|Table|Integer|String)", re.I),
     "db_schema", "high", "Database schema change detected — migration script likely required."),
    (re.compile(r"AlembicConfig|alembic\.(op|util)", re.I),
     "db_schema", "high", "Alembic migration reference — ensure upgrade/downgrade scripts are updated."),
    (re.compile(r"BaseModel|pydantic|from_orm|model_validate", re.I),
     "api_contract", "medium", "Pydantic model change — review serialisation compatibility."),
    (re.compile(r"settings\.|os\.environ\[|getenv\(", re.I),
     "config", "medium", "Environment/config reference — ensure deployment config is updated."),
    (re.compile(r"requirements\.txt|pyproject\.toml|setup\.py|poetry\.lock", re.I),
     "dependency", "low", "Dependency file referenced — pip install / lockfile update may be needed."),
]


def _parse_params(signature: str) -> List[str]:
    match = re.search(r"\(([^)]*)\)", signature)
    if not match:
        return []
    raw = match.group(1)
    params = []
    for part in raw.split(","):
        part = part.strip()
        if not part or part in {"self", "cls", "*", "**kwargs", "*args"}:
            continue
        name = part.split(":")[0].split("=")[0].strip().lstrip("*")
        if name:
            params.append(name)
    return params


def _path_key(v: str) -> str:
    return v.replace("\\", "/").strip("/").casefold()


def _make_unified_diff(
    original: str,
    proposed: str,
    fromfile: str = "original",
    tofile: str = "proposed",
) -> str:
    diff_lines = list(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            proposed.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
            lineterm="",
        )
    )
    return "".join(diff_lines) if diff_lines else "(no textual difference)"


def _make_rollback_diff(unified_diff: str) -> str:
    """Invert a unified diff (swap + / -)."""
    lines = []
    for line in unified_diff.splitlines(keepends=True):
        if line.startswith("+") and not line.startswith("+++"):
            lines.append("-" + line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            lines.append("+" + line[1:])
        elif line.startswith("---"):
            lines.append("+++ " + line[4:])
        elif line.startswith("+++"):
            lines.append("--- " + line[4:])
        else:
            lines.append(line)
    return "".join(lines)


class WhatIfSimulatorService:
    """
    Orchestrates deterministic + AI-augmented what-if analysis.

    IMPORTANT: This service is read-only with respect to the original
    repository. It never modifies files, commits, or deploys anything.
    """

    def __init__(self, db: AsyncSession, repository: Repository):
        self.db = db
        self.repository = repository
        self._sim_id = str(uuid.uuid4())[:8]

    # ── Public entry point ────────────────────────────────────────────────────

    async def simulate(self, request: WhatIfRequest) -> WhatIfSimulationResult:
        # 1. Load repository evidence
        files, files_by_id = await self._load_files()
        symbols, symbols_by_id = await self._load_symbols()
        relationships = await self._load_relationships()
        imports = await self._load_imports()

        # 2. Resolve target file & symbol
        target_file_obj = self._resolve_file(request.file_path, files)
        target_symbol_obj = self._resolve_symbol(
            request.symbol, target_file_obj, symbols, files_by_id
        )

        # 3. Extract current code snippet for the target
        current_snippet = self._extract_current_snippet(
            target_file_obj, target_symbol_obj, files_by_id
        )

        # 4. Build simulated patch (in-memory, never written to disk)
        patch = self._build_patch(
            request, target_file_obj, target_symbol_obj, current_snippet
        )

        # 5. Determine the effective "proposed code" for pattern analysis
        proposed_code = (
            request.proposed_code
            or patch.proposed_snippet
            or request.natural_language_description
        )

        # 6. Deterministic analysis
        affected_files = self._compute_affected_files(
            target_file_obj, target_symbol_obj, symbols, files, imports,
            relationships, files_by_id, symbols_by_id
        )
        impacted_functions = self._compute_impacted_functions(
            target_symbol_obj, relationships, symbols_by_id, files_by_id
        )
        breaking_changes = self._compute_breaking_changes(
            target_symbol_obj, target_file_obj, symbols, request, files_by_id
        )
        test_failure_risks = self._compute_test_failure_risks(
            target_file_obj, target_symbol_obj, symbols, files, relationships,
            symbols_by_id, files_by_id
        )

        # 7. Pattern-based AI analysis
        security_implications = self._analyze_security(proposed_code, target_file_obj)
        performance_concerns = self._analyze_performance(proposed_code, target_file_obj)
        migration_requirements = self._analyze_migration(proposed_code, target_file_obj)
        regression_tests = self._recommend_regression_tests(
            target_file_obj, target_symbol_obj, affected_files, test_failure_risks
        )

        # 8. Alternative proposals
        alternatives = self._build_alternatives(request)

        # 9. Overall risk & confidence
        overall_risk, overall_confidence = self._compute_overall_risk(
            breaking_changes, security_implications, test_failure_risks,
            performance_concerns, migration_requirements
        )

        verified_count = (
            len([f for f in affected_files]) +
            len(breaking_changes) +
            len(test_failure_risks)
        )
        predicted_count = (
            len(security_implications) +
            len(performance_concerns) +
            len(migration_requirements)
        )

        summary = self._build_summary(
            target_file_obj, target_symbol_obj, affected_files,
            breaking_changes, overall_risk, request
        )

        limitations = [
            "Analysis is based on the indexed repository snapshot; dynamically generated "
            "code, runtime-only imports, and unindexed files are not covered.",
            "Proposed code analysis uses static pattern matching, not full program execution.",
            "Security and performance findings are heuristic estimates — manual review required.",
            "No code has been executed, merged, or deployed as part of this simulation.",
        ]
        if not request.proposed_code and not request.proposed_diff:
            limitations.append(
                "No explicit proposed_code or proposed_diff was provided; "
                "analysis targets the currently indexed version of the target."
            )

        assumptions = [
            f"Target repository: {self.repository.name} (id={self.repository.id})",
            f"Simulation workspace: in-memory only (id={self._sim_id})",
        ]
        if request.branch:
            assumptions.append(f"Branch context: {request.branch} (informational only; no checkout performed)")

        return WhatIfSimulationResult(
            repository_id=self.repository.id,
            simulation_id=self._sim_id,
            target_file=target_file_obj.relative_path if target_file_obj else request.file_path,
            target_symbol=target_symbol_obj.qualified_name if target_symbol_obj else request.symbol,
            branch_context=request.branch,
            patch=patch,
            affected_files=affected_files,
            impacted_functions=impacted_functions,
            breaking_changes=breaking_changes,
            test_failure_risks=test_failure_risks,
            security_implications=security_implications if request.include_security else [],
            performance_concerns=performance_concerns if request.include_performance else [],
            migration_requirements=migration_requirements if request.include_migration else [],
            regression_test_recommendations=regression_tests if request.include_regression_tests else [],
            alternatives=alternatives,
            overall_risk=overall_risk,
            overall_confidence=overall_confidence,
            verified_finding_count=verified_count,
            predicted_finding_count=predicted_count,
            summary=summary,
            assumptions=assumptions,
            limitations=limitations,
        )

    # ── Data loading helpers ──────────────────────────────────────────────────

    async def _load_files(self):
        res = await self.db.execute(
            select(RepositoryFile).where(
                RepositoryFile.repository_id == self.repository.id
            )
        )
        files = list(res.scalars().all())
        return files, {f.id: f for f in files}

    async def _load_symbols(self):
        res = await self.db.execute(
            select(CodeSymbol).where(
                CodeSymbol.repository_id == self.repository.id
            )
        )
        symbols = list(res.scalars().all())
        return symbols, {s.id: s for s in symbols}

    async def _load_relationships(self):
        res = await self.db.execute(
            select(CodeRelationship).where(
                CodeRelationship.repository_id == self.repository.id
            )
        )
        return list(res.scalars().all())

    async def _load_imports(self):
        res = await self.db.execute(
            select(CodeImport).where(
                CodeImport.repository_id == self.repository.id
            )
        )
        return list(res.scalars().all())

    # ── Target resolution ─────────────────────────────────────────────────────

    def _resolve_file(
        self, file_path: Optional[str], files: List[RepositoryFile]
    ) -> Optional[RepositoryFile]:
        if not file_path:
            return None
        key = _path_key(file_path)
        for f in files:
            if _path_key(f.relative_path) == key:
                return f
            if _path_key(f.relative_path).endswith(key):
                return f
        return None

    def _resolve_symbol(
        self,
        symbol: Optional[str],
        target_file: Optional[RepositoryFile],
        symbols: List[CodeSymbol],
        files_by_id: Dict[str, RepositoryFile],
    ) -> Optional[CodeSymbol]:
        if not symbol:
            return None
        lower_sym = symbol.casefold()
        leaf = lower_sym.split(".")[-1]
        candidates = symbols
        if target_file:
            candidates = [s for s in symbols if s.file_id == target_file.id]

        # 1. Exact qualified name match
        for s in candidates:
            if (s.qualified_name or "").casefold() == lower_sym:
                return s
        # 2. Exact name match
        for s in candidates:
            if s.name.casefold() == lower_sym or s.name.casefold() == leaf:
                return s
        # 3. Suffix / prefix matches
        for s in candidates:
            q = (s.qualified_name or "").casefold()
            if q.endswith(f".{leaf}") or lower_sym.endswith(f".{s.name.casefold()}"):
                return s
        # 4. Fallback across all symbols
        for s in symbols:
            q = (s.qualified_name or "").casefold()
            if q == lower_sym or s.name.casefold() == leaf or q.endswith(f".{leaf}"):
                return s
        return None

    def _extract_current_snippet(
        self,
        target_file: Optional[RepositoryFile],
        target_symbol: Optional[CodeSymbol],
        files_by_id: Dict[str, RepositoryFile],
    ) -> str:
        if target_symbol and target_symbol.signature:
            return target_symbol.signature
        return ""

    # ── Patch builder (in-memory only) ────────────────────────────────────────

    def _build_patch(
        self,
        request: WhatIfRequest,
        target_file: Optional[RepositoryFile],
        target_symbol: Optional[CodeSymbol],
        current_snippet: str,
    ) -> WhatIfPatch:
        file_path = (
            target_file.relative_path if target_file else (request.file_path or "unknown")
        )
        original = current_snippet or "(current content not available in index)"
        proposed = request.proposed_code or (
            f"# Proposed change based on:\n# {request.natural_language_description}\n"
            + original
        )

        if request.proposed_diff:
            unified = request.proposed_diff
        else:
            unified = _make_unified_diff(original, proposed, fromfile=file_path)

        rollback = _make_rollback_diff(unified)

        return WhatIfPatch(
            file_path=file_path,
            original_snippet=original,
            proposed_snippet=proposed,
            unified_diff=unified,
            rollback_diff=rollback,
        )

    # ── Deterministic: affected files ─────────────────────────────────────────

    def _compute_affected_files(
        self,
        target_file: Optional[RepositoryFile],
        target_symbol: Optional[CodeSymbol],
        symbols: List[CodeSymbol],
        files: List[RepositoryFile],
        imports: List[CodeImport],
        relationships: List[CodeRelationship],
        files_by_id: Dict[str, RepositoryFile],
        symbols_by_id: Dict[str, CodeSymbol],
    ) -> List[AffectedFile]:
        if not target_file and not target_symbol:
            return []

        target_file_id = target_file.id if target_file else (
            symbols_by_id[target_symbol.file_id].id if target_symbol else None
        )
        target_symbol_ids = set()
        if target_symbol:
            target_symbol_ids.add(target_symbol.id)
        elif target_file:
            target_symbol_ids = {s.id for s in symbols if s.file_id == target_file.id}

        affected: Dict[str, AffectedFile] = {}

        # a. Direct import consumers
        target_stem = Path(target_file.relative_path).stem.casefold() if target_file else ""
        target_mod = (
            target_file.relative_path.replace("\\", "/")
            .replace(".py", "")
            .replace("/", ".")
            .casefold()
            if target_file
            else ""
        )

        for imp in imports:
            if not imp.module_name:
                continue
            mod = imp.module_name.casefold()
            matches = False
            if target_file:
                if (
                    mod == target_mod
                    or mod == target_stem
                    or mod.endswith(f".{target_stem}")
                    or target_stem in mod
                ):
                    matches = True

            if matches:
                consumer_file = files_by_id.get(imp.file_id)
                if consumer_file and consumer_file.id != target_file_id:
                    key = consumer_file.relative_path
                    if key not in affected:
                        imported_sym_str = (
                            ", ".join(imp.imported_symbols)
                            if imp.imported_symbols and isinstance(imp.imported_symbols, list)
                            else imp.module_name
                        )
                        affected[key] = AffectedFile(
                            file=key,
                            reason=f"Imports from {target_file.relative_path if target_file else 'target'}",
                            relationship="direct_import",
                            confidence=0.9,
                            locations=[
                                SourceLocation(
                                    file=key,
                                    line=imp.line_number,
                                    symbol=imported_sym_str,
                                )
                            ],
                        )

        # b. Call-graph / relationship consumers
        for rel in relationships:
            if rel.target_symbol_id not in target_symbol_ids:
                continue
            src_sym = symbols_by_id.get(rel.source_symbol_id or "")
            if not src_sym:
                continue
            src_file = files_by_id.get(src_sym.file_id)
            if not src_file or src_file.id == target_file_id:
                continue
            key = src_file.relative_path
            loc = SourceLocation(
                file=key,
                line=src_sym.start_line,
                symbol=src_sym.qualified_name,
            )
            if key not in affected:
                affected[key] = AffectedFile(
                    file=key,
                    reason=f"{rel.relationship_type} → {target_symbol.qualified_name if target_symbol else 'target'}",
                    relationship="call_graph",
                    confidence=0.85,
                    locations=[loc],
                )
            else:
                affected[key].locations.append(loc)

        # c. Test files that reference the target
        for f in files:
            if f.is_test and f.id != target_file_id:
                test_key = f.relative_path
                if test_key not in affected:
                    # Check if any symbol in this test file has a 'tests' relationship to target
                    test_sym_ids = {s.id for s in symbols if s.file_id == f.id}
                    for rel in relationships:
                        if (
                            rel.relationship_type == "tests"
                            and rel.source_symbol_id in test_sym_ids
                            and rel.target_symbol_id in target_symbol_ids
                        ):
                            affected[test_key] = AffectedFile(
                                file=test_key,
                                reason="Test file covering the changed symbol",
                                relationship="test",
                                confidence=0.95,
                                locations=[
                                    SourceLocation(file=test_key, symbol="(test)")
                                ],
                            )
                            break

        return sorted(affected.values(), key=lambda a: -a.confidence)[:50]

    # ── Deterministic: impacted functions ─────────────────────────────────────

    def _compute_impacted_functions(
        self,
        target_symbol: Optional[CodeSymbol],
        relationships: List[CodeRelationship],
        symbols_by_id: Dict[str, CodeSymbol],
        files_by_id: Dict[str, RepositoryFile],
    ) -> List[ImpactedFunction]:
        if not target_symbol:
            return []

        results: List[ImpactedFunction] = []
        seen: set = set()

        for rel in relationships:
            if rel.target_symbol_id != target_symbol.id:
                continue
            src_sym = symbols_by_id.get(rel.source_symbol_id or "")
            if not src_sym or src_sym.id in seen:
                continue
            seen.add(src_sym.id)
            src_file = files_by_id.get(src_sym.file_id)
            file_path = src_file.relative_path if src_file else "unknown"

            rel_type = rel.relationship_type
            if rel_type in ("calls", "accesses", "references"):
                impact_type = "behavioral"
            elif rel_type in ("inherits", "implements"):
                impact_type = "signature_break"
            elif rel_type == "tests":
                impact_type = "test_failure_risk"
            else:
                impact_type = "indirect"

            results.append(
                ImpactedFunction(
                    symbol=src_sym.qualified_name or src_sym.name,
                    file=file_path,
                    line=src_sym.start_line,
                    relationship=rel_type,
                    impact_type=impact_type,
                    confidence=0.85 if rel_type in CALL_RELS else 0.7,
                    evidence=[
                        SourceLocation(
                            file=file_path,
                            line=src_sym.start_line,
                            symbol=src_sym.qualified_name,
                        )
                    ],
                )
            )

        return sorted(results, key=lambda f: -f.confidence)[:60]

    # ── Deterministic: breaking changes ───────────────────────────────────────

    def _compute_breaking_changes(
        self,
        target_symbol: Optional[CodeSymbol],
        target_file: Optional[RepositoryFile],
        symbols: List[CodeSymbol],
        request: WhatIfRequest,
        files_by_id: Dict[str, RepositoryFile],
    ) -> List[BreakingChangeEntry]:
        symbols_to_check: List[CodeSymbol] = []
        if target_symbol:
            symbols_to_check.append(target_symbol)
        elif target_file:
            symbols_to_check.extend([s for s in symbols if s.file_id == target_file.id])

        if not symbols_to_check:
            return []

        results: List[BreakingChangeEntry] = []
        new_code = request.proposed_code or ""
        if not new_code:
            return results

        try:
            tree = ast.parse(textwrap.dedent(new_code))
            new_funcs: Dict[str, ast.AST] = {}
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    new_funcs[node.name] = node

            for sym in symbols_to_check:
                file_obj = files_by_id.get(sym.file_id)
                file_path = file_obj.relative_path if file_obj else "unknown"
                old_sig = sym.signature or ""
                sym_name = sym.name

                if sym_name in new_funcs:
                    node = new_funcs[sym_name]
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        old_params = [
                            p.get("name", "") for p in (sym.parameters or [])
                            if isinstance(p, dict) and p.get("name") not in ("self", "cls")
                        ]
                        if not old_params and old_sig:
                            old_params = _parse_params(old_sig)

                        new_params = [
                            a.arg for a in node.args.args
                            if a.arg not in ("self", "cls")
                        ]
                        removed = [p for p in old_params if p not in new_params]
                        added = [p for p in new_params if p not in old_params]

                        if removed:
                            results.append(BreakingChangeEntry(
                                symbol=sym.qualified_name or sym.name,
                                file=file_path,
                                line=sym.start_line,
                                category="signature",
                                severity="critical",
                                before=old_sig or f"{sym_name}({', '.join(old_params)})",
                                after=f"{sym_name}({', '.join(new_params)})",
                                description=(
                                    f"Required parameter(s) removed: {', '.join(removed)}. "
                                    "All callers passing these arguments will fail."
                                ),
                                verified=True,
                            ))
                        if added:
                            num_args = len(node.args.args)
                            num_defaults = len(node.args.defaults)
                            required_new_args = [
                                node.args.args[i].arg
                                for i in range(num_args - num_defaults)
                                if node.args.args[i].arg not in ("self", "cls")
                            ]
                            breaking_added = [p for p in added if p in required_new_args]
                            if breaking_added:
                                results.append(BreakingChangeEntry(
                                    symbol=sym.qualified_name or sym.name,
                                    file=file_path,
                                    line=sym.start_line,
                                    category="signature",
                                    severity="high",
                                    before=old_sig or f"{sym_name}({', '.join(old_params)})",
                                    after=f"{sym_name}({', '.join(new_params)})",
                                    description=(
                                        f"New required parameter(s) added: {', '.join(breaking_added)}. "
                                        "Existing callers will fail unless updated."
                                    ),
                                    verified=True,
                                ))
                        # Return type change
                        old_ret = sym.return_type or ""
                        new_ret = ""
                        if node.returns:
                            try:
                                new_ret = ast.unparse(node.returns)
                            except Exception:
                                pass
                        if old_ret and new_ret and old_ret.strip() != new_ret.strip():
                            results.append(BreakingChangeEntry(
                                symbol=sym.qualified_name or sym.name,
                                file=file_path,
                                line=sym.start_line,
                                category="return_type",
                                severity="high",
                                before=old_ret,
                                after=new_ret,
                                description=(
                                    f"Return type changed from `{old_ret}` to `{new_ret}`. "
                                    "Callers relying on the old return type may break."
                                ),
                                verified=True,
                            ))
                elif sym.symbol_type in ("function", "method") and new_code.strip():
                    results.append(BreakingChangeEntry(
                        symbol=sym.qualified_name or sym.name,
                        file=file_path,
                        line=sym.start_line,
                        category="removed",
                        severity="critical",
                        before=old_sig or f"{sym_name}(...)",
                        after=None,
                        description=(
                            f"`{sym.qualified_name or sym.name}` is absent from the proposed code. "
                            "All callers will receive a NameError / ImportError."
                        ),
                        verified=True,
                    ))
        except SyntaxError:
            file_path = target_file.relative_path if target_file else "unknown"
            sym_name = target_symbol.qualified_name if target_symbol else "proposed_change"
            results.append(BreakingChangeEntry(
                symbol=sym_name,
                file=file_path,
                line=target_symbol.start_line if target_symbol else None,
                category="signature",
                severity="high",
                before=target_symbol.signature if target_symbol else None,
                after="(parse error)",
                description="Proposed code failed to parse as valid Python AST.",
                verified=True,
            ))

        return results

    # ── Deterministic: test failure risks ────────────────────────────────────

    def _compute_test_failure_risks(
        self,
        target_file: Optional[RepositoryFile],
        target_symbol: Optional[CodeSymbol],
        symbols: List[CodeSymbol],
        files: List[RepositoryFile],
        relationships: List[CodeRelationship],
        symbols_by_id: Dict[str, CodeSymbol],
        files_by_id: Dict[str, RepositoryFile],
    ) -> List[TestFailureRisk]:
        results: List[TestFailureRisk] = []
        seen: set = set()

        target_symbol_ids = (
            {target_symbol.id} if target_symbol else
            {s.id for s in symbols if target_file and s.file_id == target_file.id}
        )

        for rel in relationships:
            if rel.relationship_type != "tests":
                continue
            if rel.target_symbol_id not in target_symbol_ids:
                continue
            src_sym = symbols_by_id.get(rel.source_symbol_id or "")
            if not src_sym or src_sym.id in seen:
                continue
            seen.add(src_sym.id)
            src_file = files_by_id.get(src_sym.file_id)
            if not src_file:
                continue
            results.append(TestFailureRisk(
                test_file=src_file.relative_path,
                test_function=src_sym.qualified_name,
                line=src_sym.start_line,
                risk_level="high",
                reason="This test directly covers the changed symbol via 'tests' relationship.",
                verified=True,
            ))

        # Also flag test files that import the changed file
        for f in files:
            if not f.is_test:
                continue
            key = f.relative_path
            if key in seen:
                continue
            if target_file and (
                target_file.file_name.replace(".py", "") in key
            ):
                results.append(TestFailureRisk(
                    test_file=key,
                    test_function=None,
                    line=None,
                    risk_level="medium",
                    reason="Test file name matches the changed module — likely covers it.",
                    verified=False,
                ))

        return results

    # ── Pattern-based: security ───────────────────────────────────────────────

    def _analyze_security(
        self, proposed_code: str, target_file: Optional[RepositoryFile]
    ) -> List[SecurityImplication]:
        results: List[SecurityImplication] = []
        file_path = target_file.relative_path if target_file else "proposed"
        for pattern, category, severity, desc in _SECURITY_PATTERNS:
            for match in pattern.finditer(proposed_code):
                line = proposed_code[: match.start()].count("\n") + 1
                results.append(SecurityImplication(
                    severity=severity,
                    category=category,
                    description=desc,
                    verified=False,
                    locations=[SourceLocation(file=file_path, line=line)],
                    remediation=f"Review usage of `{match.group()}` and ensure safe handling.",
                ))
                break  # one hit per pattern is enough
        return results

    # ── Pattern-based: performance ────────────────────────────────────────────

    def _analyze_performance(
        self, proposed_code: str, target_file: Optional[RepositoryFile]
    ) -> List[PerformanceConcern]:
        results: List[PerformanceConcern] = []
        file_path = target_file.relative_path if target_file else "proposed"
        for pattern, category, severity, desc in _PERF_PATTERNS:
            match = pattern.search(proposed_code)
            if match:
                line = proposed_code[: match.start()].count("\n") + 1
                results.append(PerformanceConcern(
                    severity=severity,
                    category=category,
                    description=desc,
                    verified=False,
                    locations=[SourceLocation(file=file_path, line=line)],
                ))
        return results

    # ── Pattern-based: migration ──────────────────────────────────────────────

    def _analyze_migration(
        self, proposed_code: str, target_file: Optional[RepositoryFile]
    ) -> List[MigrationRequirement]:
        results: List[MigrationRequirement] = []
        file_path = target_file.relative_path if target_file else "proposed"
        for pattern, category, severity, desc in _MIGRATION_PATTERNS:
            match = pattern.search(proposed_code)
            if match:
                line = proposed_code[: match.start()].count("\n") + 1
                results.append(MigrationRequirement(
                    category=category,
                    severity=severity,
                    description=desc,
                    action_required=f"Review and update {category.replace('_', ' ')} artifacts before deployment.",
                    locations=[SourceLocation(file=file_path, line=line)],
                ))
        return results

    # ── Regression test recommendations ──────────────────────────────────────

    def _recommend_regression_tests(
        self,
        target_file: Optional[RepositoryFile],
        target_symbol: Optional[CodeSymbol],
        affected_files: List[AffectedFile],
        test_risks: List[TestFailureRisk],
    ) -> List[RegressionTestRecommendation]:
        results: List[RegressionTestRecommendation] = []

        # Recommend running existing tests that are at risk
        for risk in test_risks[:10]:
            results.append(RegressionTestRecommendation(
                test_name=risk.test_function or risk.test_file,
                description=f"Run '{risk.test_file}' — it covers the changed symbol.",
                target_symbol=target_symbol.qualified_name if target_symbol else None,
                target_file=risk.test_file,
                priority="critical" if risk.risk_level == "high" else "high",
                rationale=risk.reason,
            ))

        # Recommend tests for directly affected API consumers
        for af in affected_files:
            if af.relationship in ("call_graph", "direct_import"):
                results.append(RegressionTestRecommendation(
                    test_name=f"Integration test covering {af.file}",
                    description=(
                        f"Verify that `{af.file}` still behaves correctly after the change "
                        f"(it {af.reason.lower()})."
                    ),
                    target_file=af.file,
                    priority="high",
                    rationale=af.reason,
                ))
                if len(results) >= 15:
                    break

        if target_symbol:
            results.insert(0, RegressionTestRecommendation(
                test_name=f"Unit tests for {target_symbol.name}",
                description=(
                    f"Write or run unit tests directly for `{target_symbol.qualified_name}` "
                    "to verify the proposed change is correct."
                ),
                target_symbol=target_symbol.qualified_name,
                target_file=target_file.relative_path if target_file else None,
                priority="critical",
                rationale="The changed symbol itself must be covered by focused unit tests.",
            ))

        return results[:15]

    # ── Alternative proposals ─────────────────────────────────────────────────

    def _build_alternatives(self, request: WhatIfRequest) -> List[AlternativeProposal]:
        alts: List[AlternativeProposal] = []
        for alt_desc in (request.alternatives or []):
            alts.append(AlternativeProposal(
                description=alt_desc,
                patch_hint=None,
                tradeoffs="(Not yet analyzed — submit as a separate simulation request.)",
                estimated_risk="unknown",
            ))
        # Always suggest a rollback as an alternative
        alts.append(AlternativeProposal(
            description="Do not apply this change; keep the current implementation.",
            patch_hint=None,
            tradeoffs="No risk introduced, but the described improvement is forgone.",
            estimated_risk="low",
        ))
        return alts

    # ── Risk aggregation ──────────────────────────────────────────────────────

    def _compute_overall_risk(
        self,
        breaking_changes: List[BreakingChangeEntry],
        security_implications: List[SecurityImplication],
        test_failure_risks: List[TestFailureRisk],
        performance_concerns: List[PerformanceConcern],
        migration_requirements: List[MigrationRequirement],
    ) -> Tuple[str, float]:
        critical = any(
            bc.severity == "critical" for bc in breaking_changes
        ) or any(si.severity == "critical" for si in security_implications)

        high_bc = sum(1 for bc in breaking_changes if bc.severity in ("high", "critical"))
        high_sec = sum(1 for si in security_implications if si.severity in ("high", "critical"))
        high_mig = sum(1 for mr in migration_requirements if mr.severity == "high")
        high_test = sum(1 for tr in test_failure_risks if tr.risk_level == "high")
        high_perf = sum(1 for pc in performance_concerns if pc.severity == "high")

        score = (
            high_bc * 3 +
            high_sec * 2.5 +
            high_mig * 2 +
            high_test * 1 +
            high_perf * 1.5 +
            len(performance_concerns) * 0.5
        )

        if critical or score >= 6 or (high_sec >= 1 and (high_perf >= 1 or high_bc >= 1)):
            risk = "critical" if (critical or score >= 6) else "high"
            confidence = min(0.9, 0.6 + high_bc * 0.05 + high_sec * 0.05)
        elif score >= 2.0 or high_sec >= 1:
            risk = "high"
            confidence = 0.65
        elif score >= 1:
            risk = "medium"
            confidence = 0.55
        else:
            risk = "low"
            confidence = 0.5

        return risk, round(confidence, 2)

    # ── Summary text ──────────────────────────────────────────────────────────

    def _build_summary(
        self,
        target_file: Optional[RepositoryFile],
        target_symbol: Optional[CodeSymbol],
        affected_files: List[AffectedFile],
        breaking_changes: List[BreakingChangeEntry],
        overall_risk: str,
        request: WhatIfRequest,
    ) -> str:
        target_desc = (
            f"`{target_symbol.qualified_name}`" if target_symbol
            else (f"`{target_file.relative_path}`" if target_file else "the selected target")
        )
        parts = [
            f"**What-If Simulation** for {target_desc} — "
            f"proposed change: \"{request.natural_language_description[:120]}\".",
            f"Overall risk: **{overall_risk.upper()}**. "
            f"{len(affected_files)} file(s) in the call/import graph are potentially affected.",
        ]
        if breaking_changes:
            parts.append(
                f"{len(breaking_changes)} breaking change(s) detected by deterministic AST analysis."
            )
        else:
            parts.append("No deterministic breaking changes detected.")
        parts.append(
            "⚠ This is a read-only simulation. No changes have been applied to the repository."
        )
        return " ".join(parts)
