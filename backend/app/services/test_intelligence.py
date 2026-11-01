from __future__ import annotations

import ast
from bisect import bisect_left, bisect_right
from collections import defaultdict, deque
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import CodeImport, CodeRelationship, CodeSymbol, Repository, RepositoryFile
from app.schemas.test_intelligence import (
    RegressionSelectionResponse,
    RegressionTestCandidate,
    TestEvidence,
    TestStrengthResponse,
    TestStrengthSymbol,
)
from app.schemas.technical_debt import DebtEvidence


PRODUCTION_SYMBOL_TYPES = {"function", "method", "api_route", "class", "db_model"}
RELATION_TYPES = {"calls", "references", "tests", "accesses"}
MAX_ANALYSIS_FILE_BYTES = 1_000_000

# Mutation testing availability — check at runtime; if the tool is installed
# the service can optionally invoke it. Absence does not break anything.
try:
    import mutmut  # type: ignore
    MUTMUT_AVAILABLE = True
except ImportError:
    MUTMUT_AVAILABLE = False


PRODUCTION_SYMBOL_TYPES = {"function", "method", "api_route", "class", "db_model"}
RELATION_TYPES = {"calls", "references", "tests", "accesses"}
MAX_ANALYSIS_FILE_BYTES = 1_000_000


def _path_key(path: str) -> str:
    return path.replace("\\", "/").strip("/").casefold()


def _module_key(path: str) -> str:
    parts = list(PurePosixPath(path.replace("\\", "/")).with_suffix("").parts)
    if parts and parts[-1].casefold() == "__init__":
        parts.pop()
    return ".".join(parts).casefold()


class TestIntelligenceService:
    """Deterministic test inventory and test selection from the persisted twin."""

    def __init__(self, db: AsyncSession, repository: Repository):
        self.db = db
        self.repository = repository
        self.files_by_id: dict[str, RepositoryFile] = {}
        self.symbols_by_id: dict[str, CodeSymbol] = {}
        self.file_symbols: dict[str, list[CodeSymbol]] = defaultdict(list)
        self.imports_by_file: dict[str, list[CodeImport]] = defaultdict(list)
        self.relationships: list[CodeRelationship] = []
        self.test_ast: dict[str, dict[str, Any]] = {}
        self.test_function_names: dict[str, set[str]] = {}
        self.source_control_flow: dict[str, tuple[list[int] | None, list[int] | None]] = {}
        self.test_relationship_evidence: dict[str, list[TestEvidence]] = defaultdict(list)

    async def _load(self) -> None:
        file_result = await self.db.execute(
            select(RepositoryFile).where(RepositoryFile.repository_id == self.repository.id)
        )
        files = file_result.scalars().all()
        self.files_by_id = {item.id: item for item in files}

        symbol_result = await self.db.execute(
            select(CodeSymbol).where(CodeSymbol.repository_id == self.repository.id)
        )
        symbols = symbol_result.scalars().all()
        self.symbols_by_id = {item.id: item for item in symbols}
        self.file_symbols = defaultdict(list)
        for item in symbols:
            self.file_symbols[item.file_id].append(item)

        import_result = await self.db.execute(
            select(CodeImport).where(CodeImport.repository_id == self.repository.id)
        )
        self.imports_by_file = defaultdict(list)
        for item in import_result.scalars().all():
            self.imports_by_file[item.file_id].append(item)

        relation_result = await self.db.execute(
            select(CodeRelationship).where(CodeRelationship.repository_id == self.repository.id)
        )
        self.relationships = relation_result.scalars().all()

        self.test_ast = {}
        self.test_function_names = {}
        self.source_control_flow = {}
        root = Path(self.repository.local_path).resolve()
        for file in files:
            if not file.is_test or file.file_extension.casefold() != ".py" or file.size_bytes > MAX_ANALYSIS_FILE_BYTES:
                continue
            parsed = self._read_test_ast(root, file)
            if parsed is not None:
                self.test_ast[file.id] = parsed
                self.test_function_names[file.id] = parsed["test_function_names"]

        self.test_relationship_evidence = defaultdict(list)
        for relation in self.relationships:
            test_file = self.files_by_id.get(relation.source_file_id)
            if (
                test_file and test_file.is_test and relation.target_symbol_id
                and relation.relationship_type in RELATION_TYPES
            ):
                self.test_relationship_evidence[relation.target_symbol_id].append(TestEvidence(
                    source="indexed_call_relationship",
                    file=test_file.relative_path,
                    line=relation.evidence_line,
                    description=relation.evidence_text or f"Indexed {relation.relationship_type} relationship to a repository symbol.",
                ))

    @staticmethod
    def _read_test_ast(root: Path, file: RepositoryFile) -> dict[str, Any] | None:
        full_path = (root / file.relative_path).resolve()
        try:
            full_path.relative_to(root)
            if not full_path.is_file() or full_path.stat().st_size > MAX_ANALYSIS_FILE_BYTES:
                return None
            source = full_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=file.relative_path)
        except (OSError, UnicodeError, SyntaxError, ValueError):
            return None

        test_functions = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
        ]
        assertion_calls = 0
        risky_calls: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                assertion_calls += 1
            elif isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                leaf = name.rsplit(".", 1)[-1]
                if leaf in {"assertEqual", "assertTrue", "assertFalse", "assertRaises", "assertIsNone", "assertIsNotNone"} or leaf.startswith("assert_") or name.endswith(".raises"):
                    assertion_calls += 1
                if any(token in name.casefold() for token in ("time.sleep", "random.", "requests.", "httpx.", "socket.")):
                    risky_calls.add(name)
        return {
            "test_functions": len(test_functions),
            "test_function_names": {node.name.casefold() for node in test_functions},
            "assertions": assertion_calls,
            "risky_calls": sorted(risky_calls),
            "tree": tree,
        }

    def _relationship_test_evidence(self, symbol: CodeSymbol) -> list[TestEvidence]:
        return self.test_relationship_evidence.get(symbol.id, [])

    def _test_import_evidence(self, symbol: CodeSymbol) -> list[TestEvidence]:
        production_file = self.files_by_id.get(symbol.file_id)
        if production_file is None:
            return []
        target_module = _module_key(production_file.relative_path)
        evidence = []
        for test_file_id, imports in self.imports_by_file.items():
            test_file = self.files_by_id.get(test_file_id)
            if not test_file or not test_file.is_test:
                continue
            for imported in imports:
                module = imported.module_name.replace("\\", ".").strip(".").casefold()
                module_match = bool(module and (module == target_module or module.endswith(f".{target_module}") or target_module.endswith(f".{module}")))
                named_match = symbol.name.casefold() in {str(value).casefold() for value in (imported.imported_symbols or [])}
                if module_match and (named_match or not imported.imported_symbols):
                    evidence.append(TestEvidence(
                        source="test_import",
                        file=test_file.relative_path,
                        line=imported.line_number,
                        description=f"Test file imports module {imported.module_name}; symbol-level coverage is not established by this import alone.",
                    ))
                    break
        return evidence

    def _source_branch_counts(self, root: Path, file: RepositoryFile, symbol: CodeSymbol) -> tuple[int | None, int | None]:
        if file.file_extension.casefold() != ".py" or file.size_bytes > MAX_ANALYSIS_FILE_BYTES:
            return None, None
        if file.id not in self.source_control_flow:
            full_path = (root / file.relative_path).resolve()
            try:
                full_path.relative_to(root)
                source = full_path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=file.relative_path)
                self.source_control_flow[file.id] = (
                    sorted(
                        getattr(node, "lineno", -1) for node in ast.walk(tree)
                        if isinstance(node, (ast.If, ast.IfExp, ast.Match, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler))
                    ),
                    sorted(getattr(node, "lineno", -1) for node in ast.walk(tree) if isinstance(node, ast.Raise)),
                )
            except (OSError, UnicodeError, SyntaxError, ValueError):
                self.source_control_flow[file.id] = (None, None)
        branch_lines, raise_lines = self.source_control_flow[file.id]
        if branch_lines is None or raise_lines is None:
            return None, None
        branches = bisect_right(branch_lines, symbol.end_line) - bisect_left(branch_lines, symbol.start_line)
        raises = bisect_right(raise_lines, symbol.end_line) - bisect_left(raise_lines, symbol.start_line)
        return branches, raises

    async def analyze_strength(self) -> TestStrengthResponse:
        await self._load()
        test_files = [item for item in self.files_by_id.values() if item.is_test]
        production = [
            symbol for symbol in self.symbols_by_id.values()
            if symbol.symbol_type in PRODUCTION_SYMBOL_TYPES
            and self.files_by_id.get(symbol.file_id)
            and not self.files_by_id[symbol.file_id].is_test
        ]
        root = Path(self.repository.local_path).resolve()
        symbol_rows: list[TestStrengthSymbol] = []
        for symbol in sorted(production, key=lambda item: (self.files_by_id[item.file_id].relative_path.casefold(), item.start_line)):
            file = self.files_by_id[symbol.file_id]
            linked = self._relationship_test_evidence(symbol)
            imported = self._test_import_evidence(symbol)
            candidates = self._name_test_evidence(symbol, test_files)
            evidence = linked or imported or candidates
            if linked:
                status = "linked"
            elif imported or candidates:
                status = "candidate"
            else:
                status = "unmatched"
            branches, raises = self._source_branch_counts(root, file, symbol)
            gaps: list[str] = []
            if not evidence:
                gaps.append("No indexed test relationship, matching test import, or test-name match was found.")
            if branches:
                gaps.append(f"Candidate gap: review {branches} branch/control-flow point(s) for decision and boundary tests.")
            if raises:
                gaps.append(f"Candidate gap: review {raises} raise point(s) for exception-path tests.")
            if symbol.complexity_score and symbol.complexity_score >= 5:
                gaps.append("Candidate gap: higher indexed complexity suggests reviewing additional path combinations.")
            # Mutation testing gap (informational only; mutmut not installed by default)
            if not MUTMUT_AVAILABLE:
                gaps.append("Mutation testing: install 'mutmut' to compute mutation-score change and verify test adequacy.")
            symbol_rows.append(TestStrengthSymbol(
                symbol=symbol.qualified_name,
                symbol_type=symbol.symbol_type,
                file=file.relative_path,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                complexity=symbol.complexity_score or 1,
                mapping_status=status,
                linked_tests=sorted({item.file for item in linked}),
                candidate_tests=sorted({item.file for item in imported + candidates}),
                branch_count=branches,
                raise_count=raises,
                potential_gaps=gaps,
                evidence=evidence,
            ))

        python_test_ids = [item.id for item in test_files if item.id in self.test_ast]
        function_count = sum(self.test_ast[item]["test_functions"] for item in python_test_ids)
        with_assertions = sum(self.test_ast[item]["assertions"] > 0 for item in python_test_ids)
        findings: list[str] = []
        unmatched = sum(row.mapping_status == "unmatched" for row in symbol_rows)
        if unmatched:
            findings.append(f"{unmatched} indexed production symbol(s) have no test mapping evidence; this is a candidate coverage gap, not proof that tests are absent.")
        no_assertions = sum(self.test_ast[item]["assertions"] == 0 for item in python_test_ids)
        if no_assertions:
            findings.append(f"{no_assertions} parseable Python test file(s) contain no recognized assertion constructs.")
        flaky = [
            self.files_by_id[item].relative_path
            for item in python_test_ids if self.test_ast[item]["risky_calls"]
        ]
        if flaky:
            findings.append(f"Potential nondeterminism or external dependency patterns were found in {len(flaky)} test file(s): {', '.join(flaky[:8])}.")
        # Mutation testing result summary (informational)
        if MUTMUT_AVAILABLE:
            findings.append("Mutation testing: 'mutmut' is installed; run mutation analysis to compute mutation score and verify test adequacy. "
                          "See the Technical Debt Planner for mutation-score change tracking.")
        else:
            findings.append("Mutation testing: 'mutmut' is not installed; install it to compute mutation-score changes and identify untested error paths.")
        # Estimate coverage based on linked symbols
        linked_count = sum(row.mapping_status == "linked" for row in symbol_rows)
        total_symbols = len(symbol_rows)
        estimated_coverage = round(linked_count / max(total_symbols, 1) * 100, 1) if total_symbols else 0
        findings.append(f"Estimated test coverage (linked symbols): {estimated_coverage}% of {total_symbols} analyzed production symbols.")
        findings.sort()
        return TestStrengthResponse(
            repository_id=self.repository.id,
            test_file_count=len(test_files),
            python_test_file_count=len(python_test_ids),
            discovered_test_function_count=function_count,
            test_files_with_assertions=with_assertions,
            test_files_without_assertions=no_assertions,
            mapped_symbols=linked_count,
            analyzed_symbols=total_symbols,
            symbols=symbol_rows,
            findings=findings,
            limitations=[
                "Test-to-code links are inferred from the persisted graph, imports, and names; dynamic calls and fixtures can be missed.",
                "Assertion counts and control-flow counts are static signals, not execution coverage or proof that assertions verify intended behavior.",
                "Only Python test files are syntax-inspected; other language test files are inventoried but not structurally analyzed.",
                "Flakiness signals are heuristics and are not confirmed flaky-test findings.",
                "Mutation score is not measured by this static analysis; no mutation tests are executed here. "
                "'mutmut' must be installed and run separately for mutation-score changes.",
                "Estimated coverage is based on linked test-to-symbol mappings only; it does not account for data-driven, fixture-driven, or property-based tests.",
            ],
        )

    def _name_test_evidence(self, symbol: CodeSymbol, test_files: list[RepositoryFile]) -> list[TestEvidence]:
        production_file = self.files_by_id.get(symbol.file_id)
        if production_file is None:
            return []
        stem = PurePosixPath(production_file.relative_path).stem.casefold()
        name = symbol.name.casefold()
        output = []
        for test_file in test_files:
            path = test_file.relative_path.casefold()
            function_names = self.test_function_names.get(test_file.id, set())
            if name in function_names or f"test_{name}" in function_names or (stem and stem in path and name in path):
                output.append(TestEvidence(
                    source="test_name_match",
                    file=test_file.relative_path,
                    description=f"Test path or function name resembles {symbol.name}; execution or behavioral coverage is not established.",
                ))
        return output

    async def select_regression_tests(self, changed_files: list[str], changed_symbols: list[str]) -> RegressionSelectionResponse:
        await self._load()
        files_by_path = {_path_key(item.relative_path): item for item in self.files_by_id.values()}
        selected_files: set[str] = set()
        unknown_files = []
        for raw_path in changed_files:
            file = files_by_path.get(_path_key(raw_path))
            if file is None:
                unknown_files.append(raw_path)
            else:
                selected_files.add(file.id)

        symbols_by_qualified: dict[str, list[CodeSymbol]] = defaultdict(list)
        symbols_by_name: dict[str, list[CodeSymbol]] = defaultdict(list)
        for symbol in self.symbols_by_id.values():
            symbols_by_qualified[symbol.qualified_name.casefold()].append(symbol)
            symbols_by_name[symbol.name.casefold()].append(symbol)
        matched_symbols: dict[str, CodeSymbol] = {}
        explicitly_changed_tests: set[str] = set()
        unknown_symbols = []
        for raw_name in changed_symbols:
            matches = symbols_by_qualified.get(raw_name.casefold()) or symbols_by_name.get(raw_name.casefold()) or []
            if matches:
                for symbol in matches:
                    selected_files.add(symbol.file_id)
                    source_file = self.files_by_id.get(symbol.file_id)
                    if source_file and source_file.is_test:
                        explicitly_changed_tests.add(source_file.id)
                    else:
                        matched_symbols[symbol.id] = symbol
            else:
                unknown_symbols.append(raw_name)

        matched_symbols.update({
            symbol.id: symbol for symbol in self.symbols_by_id.values()
            if symbol.file_id in selected_files
            and symbol.symbol_type in PRODUCTION_SYMBOL_TYPES
            and not self.files_by_id[symbol.file_id].is_test
        })
        reverse_edges: dict[str, list[CodeRelationship]] = defaultdict(list)
        for relation in self.relationships:
            if relation.source_symbol_id and relation.target_symbol_id and relation.relationship_type in RELATION_TYPES:
                reverse_edges[relation.target_symbol_id].append(relation)
        impact_depth = {symbol_id: 0 for symbol_id in matched_symbols}
        cause: dict[str, tuple[str, CodeRelationship]] = {}
        queue = deque(matched_symbols)
        while queue:
            target_id = queue.popleft()
            depth = impact_depth[target_id]
            if depth >= 3:
                continue
            for relation in reverse_edges.get(target_id, []):
                source_id = relation.source_symbol_id
                if source_id in impact_depth or source_id not in self.symbols_by_id:
                    continue
                source_file = self.files_by_id.get(self.symbols_by_id[source_id].file_id)
                if source_file and source_file.is_test:
                    continue
                impact_depth[source_id] = depth + 1
                cause[source_id] = (target_id, relation)
                queue.append(source_id)

        impacted = set(impact_depth)
        test_matches: dict[str, dict[str, Any]] = {}
        for test_id in explicitly_changed_tests | {
            file_id for file_id in selected_files
            if file_id in self.files_by_id and self.files_by_id[file_id].is_test
        }:
            test_file = self.files_by_id[test_id]
            test_matches[test_id] = {
                "confidence": "high",
                "reasons": {"This test file is explicitly included among the changed files/symbols."},
                "evidence": [TestEvidence(source="changed_test_file", file=test_file.relative_path, description="The test file itself is part of the requested change set.")],
            }
        for relation in self.relationships:
            if relation.target_symbol_id not in impacted or relation.source_file_id not in self.files_by_id:
                continue
            test_file = self.files_by_id[relation.source_file_id]
            if not test_file.is_test:
                continue
            entry = test_matches.setdefault(test_file.id, {"confidence": "high", "reasons": set(), "evidence": []})
            entry["reasons"].add("A persisted test call/reference relationship reaches an impacted symbol.")
            entry["evidence"].append(TestEvidence(
                source="indexed_call_relationship",
                file=test_file.relative_path,
                line=relation.evidence_line,
                description=relation.evidence_text or "Indexed test relationship reaches an impacted symbol.",
            ))

        impacted_files = {self.symbols_by_id[symbol_id].file_id for symbol_id in impacted}
        for test_file in (item for item in self.files_by_id.values() if item.is_test):
            if test_file.id in test_matches:
                continue
            reasons = set()
            evidence = []
            for imported in self.imports_by_file.get(test_file.id, []):
                module = imported.module_name.replace("\\", ".").strip(".").casefold()
                if any(
                    module == _module_key(self.files_by_id[file_id].relative_path)
                    or module.endswith(f".{_module_key(self.files_by_id[file_id].relative_path)}")
                    or _module_key(self.files_by_id[file_id].relative_path).endswith(f".{module}")
                    for file_id in impacted_files if file_id in self.files_by_id
                ):
                    reasons.add("Test file imports an impacted module; exact runtime coverage is unknown.")
                    evidence.append(TestEvidence(source="test_import", file=test_file.relative_path, line=imported.line_number, description=f"Imports {imported.module_name}."))
            if reasons:
                test_matches[test_file.id] = {"confidence": "medium", "reasons": reasons, "evidence": evidence}

        matched_names = {symbol.name.casefold() for symbol in self.symbols_by_id.values() if symbol.id in impacted}
        for test_file in (item for item in self.files_by_id.values() if item.is_test and item.id not in test_matches):
            path = test_file.relative_path.casefold()
            if any(name in path for name in matched_names if len(name) > 2):
                test_matches[test_file.id] = {
                    "confidence": "low",
                    "reasons": {"Test path matches an impacted symbol name; this is a naming heuristic."},
                    "evidence": [TestEvidence(source="test_path_match", file=test_file.relative_path, description="Path naming suggests a possible relationship; no code link was found.")],
                }

        candidates = [
            RegressionTestCandidate(
                file=self.files_by_id[file_id].relative_path,
                confidence=entry["confidence"],
                reasons=sorted(entry["reasons"]),
                evidence=entry["evidence"],
            )
            for file_id, entry in test_matches.items()
        ]
        candidates.sort(key=lambda item: ({"high": 0, "medium": 1, "low": 2}[item.confidence], item.file.casefold()))
        reasons = []
        if unknown_files:
            reasons.append(f"{len(unknown_files)} changed file path(s) did not match indexed files.")
        if unknown_symbols:
            reasons.append(f"{len(unknown_symbols)} changed symbol name(s) did not match indexed symbols.")
        high_confidence = any(item.confidence == "high" for item in candidates)
        if not candidates:
            reasons.append("No test files were linked to the changed or impacted code; run the broader repository suite.")
        elif not high_confidence:
            reasons.append("No persisted test-to-code relationship was found; selection relies on import or path heuristics.")
        else:
            reasons.append("Static graph matches identify high-relevance candidates, but dynamic or fixture-based dependencies may be omitted; run the broader suite for complete regression coverage.")
        return RegressionSelectionResponse(
            repository_id=self.repository.id,
            changed_files=changed_files,
            changed_symbols=changed_symbols,
            matched_symbols=sorted(symbol.qualified_name for symbol in matched_symbols.values()),
            selected_tests=candidates,
            full_suite_recommended=True,
            recommendation_reasons=reasons,
            limitations=[
                "Selection uses indexed symbols, call/reference edges, imports, and names; it does not execute tests or guarantee complete dependency discovery.",
                "Fixture setup, reflection, generated code, configuration-driven imports, and external service behavior may not appear in the graph.",
            ],
        )
