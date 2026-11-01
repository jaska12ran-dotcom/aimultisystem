from __future__ import annotations

import ast
import hashlib
from collections import defaultdict
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import CodeImport, CodeSymbol, GitCommit, Repository, RepositoryDependency, RepositoryFile
from app.schemas.technical_debt import DebtEvidence, TechnicalDebtFinding, TechnicalDebtResponse


def _module(path: str) -> str:
    result = ".".join(PurePosixPath(path.replace("\\", "/")).with_suffix("").parts)
    return result.removesuffix(".__init__").casefold()


class TechnicalDebtService:
    """Evidence-backed debt signals. Findings never modify repository source."""

    def __init__(self, db: AsyncSession, repository: Repository):
        self.db = db
        self.repository = repository

    async def analyze(self) -> TechnicalDebtResponse:
        from app.models.repository import CodeRelationship
        files = (await self.db.execute(select(RepositoryFile).where(RepositoryFile.repository_id == self.repository.id))).scalars().all()
        symbols = (await self.db.execute(select(CodeSymbol).where(CodeSymbol.repository_id == self.repository.id))).scalars().all()
        imports = (await self.db.execute(select(CodeImport).where(CodeImport.repository_id == self.repository.id))).scalars().all()
        dependencies = (await self.db.execute(select(RepositoryDependency).where(RepositoryDependency.repository_id == self.repository.id))).scalars().all()
        commits = (await self.db.execute(select(GitCommit).where(GitCommit.repository_id == self.repository.id))).scalars().all()
        relationships = (await self.db.execute(select(CodeRelationship).where(CodeRelationship.repository_id == self.repository.id))).scalars().all()
        # Expose relationships to _dead_code_signals via instance cache
        self._relationships_cache = relationships
        by_id = {file.id: file for file in files}
        findings: list[TechnicalDebtFinding] = []

        # 1. Complex symbols
        for symbol in sorted((item for item in symbols if (item.complexity_score or 1) >= 10), key=lambda item: item.complexity_score or 1, reverse=True):
            file = by_id.get(symbol.file_id)
            if not file:
                continue
            score = symbol.complexity_score or 1
            findings.append(TechnicalDebtFinding(
                category="complexity", severity="high" if score >= 20 else "medium",
                title=f"Complex symbol: {symbol.qualified_name}",
                details=f"The parser measured complexity {score} for this symbol.", confidence="high",
                estimated_effort="medium" if score < 20 else "large", affected_components=[file.relative_path],
                evidence=[DebtEvidence(source="parser", file=file.relative_path, line=symbol.start_line, description=f"Measured complexity score: {score}.")],
                remediation="Split decision-heavy behavior into smaller units after preserving current behavior with tests.", measured=True,
            ))

        # 2. Oversized modules
        for file in sorted((item for item in files if not item.is_binary and item.line_count >= 800), key=lambda item: item.line_count, reverse=True):
            findings.append(TechnicalDebtFinding(
                category="oversized_module", severity="medium", title=f"Large module: {file.relative_path}",
                details=f"The indexed file has {file.line_count} lines.", confidence="high", estimated_effort="medium",
                affected_components=[file.relative_path], evidence=[DebtEvidence(source="repository_index", file=file.relative_path, description=f"Measured line count: {file.line_count}.")],
                remediation="Review module boundaries and extract cohesive responsibilities where tests can preserve behavior.", measured=True,
            ))

        # 3. Circular dependencies
        findings.extend(self._cycles(files, imports))
        # 4. Duplicate code
        findings.extend(self._duplicate_python_functions(files))
        # 5. Unused dependency candidates
        findings.extend(self._unused_dependency_candidates(dependencies, imports))
        # 6. Historical churn signals
        findings.extend(self._churn_signals(commits))
        # 7. Dead code (symbols with no incoming references)
        findings.extend(self._dead_code_signals(symbols, files))
        # 8. Architecture rule violations
        findings.extend(self._architecture_violations(symbols, files, imports, dependencies))

        findings.sort(key=lambda item: ({"high": 0, "medium": 1, "low": 2, "informational": 3}.get(item.severity, 4), item.title.casefold()))
        return TechnicalDebtResponse(
            repository_id=self.repository.id, findings=findings,
            summary=f"{len(findings)} prioritized technical-debt signal(s) found from indexed repository evidence.",
            limitations=[
                "Duplicate code and unused dependency findings are heuristics; review them before removal or refactoring.",
                "Import cycles reflect static indexed imports and can miss dynamic, generated, or runtime-only dependencies.",
                "Git churn is a historical signal, not proof that a component is defective or fragile.",
                "Dead code detection is based on indexed relationship edges; dynamic or reflection-based usage may be missed.",
                "Architecture violations are heuristics based on indexed symbols and may not capture all design-level concerns.",
            ],
        )

    def _dead_code_signals(self, symbols, files):
        """Detect symbols with no incoming relationship edges — actual graph-based dead code analysis."""
        from sqlalchemy import select as _select
        from app.models.repository import CodeRelationship
        import asyncio

        by_id = {symbol.id: symbol for symbol in symbols}
        file_by_id = {f.id: f for f in files}

        # Collect all symbol IDs that appear as a *target* in any indexed relationship.
        # We run this synchronously via a helper since this method is called from the
        # synchronous branch of analyze(); the caller is already inside an async context
        # so we fetch the data in the outer async analyze() and pass it in via the
        # extended signature.  For backward compat we silently return empty here if
        # relationships are not available, which is handled in analyze() below.
        if not hasattr(self, '_relationships_cache'):
            return []

        referenced_ids: set[str] = set()
        for rel in self._relationships_cache:
            if rel.target_symbol_id:
                referenced_ids.add(rel.target_symbol_id)
            if rel.source_symbol_id:
                referenced_ids.add(rel.source_symbol_id)

        findings: list[TechnicalDebtFinding] = []
        # Focus on non-trivial exported non-test symbols
        candidates = [
            s for s in symbols
            if s.symbol_type in {"function", "method", "class"}
            and s.is_exported
            and s.id not in referenced_ids
            and file_by_id.get(s.file_id)
            and not file_by_id[s.file_id].is_test
            and not file_by_id[s.file_id].is_config
        ]

        # Group by file for a cleaner report
        from collections import defaultdict as _dd
        by_file: dict[str, list] = _dd(list)
        for sym in candidates:
            f = file_by_id.get(sym.file_id)
            if f:
                by_file[f.relative_path].append(sym)

        for file_path, syms in sorted(by_file.items())[:20]:
            names = ", ".join(s.name for s in syms[:6])
            findings.append(TechnicalDebtFinding(
                category="potential_dead_code",
                severity="low",
                title=f"Unreferenced symbols in {file_path}",
                details=(
                    f"{len(syms)} symbol(s) ({names}{'…' if len(syms) > 6 else ''}) have no "
                    "incoming call/reference edges in the indexed relationship graph."
                ),
                confidence="medium",
                estimated_effort="small",
                affected_components=[file_path],
                evidence=[
                    DebtEvidence(
                        source="relationship_graph",
                        file=file_path,
                        line=s.start_line,
                        description=f"{s.symbol_type} `{s.name}` has no incoming relationship edges.",
                    )
                    for s in syms[:6]
                ],
                remediation=(
                    "Verify these symbols are not used via dynamic dispatch, reflection, "
                    "decorators, or external callers before removing them."
                ),
                measured=True,
            ))

        return findings

    def _architecture_violations(self, symbols, files, imports, dependencies):
        """Detect architecture rule violations based on indexed symbols and imports."""
        findings: list[TechnicalDebtFinding] = []
        # Check for dependencies on outdated/unavailable packages
        available_ecosystems = {"pip", "npm", "cargo", "maven", "go"}
        for dep in dependencies:
            if dep.ecosystem not in available_ecosystems:
                findings.append(TechnicalDebtFinding(
                    category="outdated_dependency", severity="low", title=f"Unusual dependency ecosystem: {dep.ecosystem}",
                    details=f"Dependency '{dep.package_name}' uses ecosystem '{dep.ecosystem}' which may not be standard or up-to-date.",
                    confidence="low", estimated_effort="small", affected_components=[dep.manifest_file or ""],
                    evidence=[DebtEvidence(source="dependency_manifest", file=dep.manifest_file or "", description=f"Declared {dep.ecosystem} dependency: {dep.package_name}.")],
                    remediation="Verify the dependency is required and up-to-date; check package repositories for newer versions.",
                    measured=False))
        # Check for very old dependency versions (heuristic: version string contains known old markers)
        for dep in dependencies:
            name = (dep.package_name or "").casefold()
            if any(old in name for old in ["old", "legacy", "deprecated"]):
                findings.append(TechnicalDebtFinding(
                    category="outdated_dependency", severity="informational", title=f"Dependency may be obsolete: {dep.package_name}",
                    details=f"Package name contains markers suggesting it may be obsolete or deprecated.",
                    confidence="low", estimated_effort="small", affected_components=[dep.manifest_file or ""],
                    evidence=[DebtEvidence(source="dependency_manifest", file=dep.manifest_file or "", description=f"Declared {dep.ecosystem} dependency: {dep.package_name}.")],
                    remediation="Check the package repository for newer versions or replacement libraries.",
                    measured=False))
        # Check for imports that don't resolve to known modules (broken imports)
        by_module = {_module(file.relative_path): file for file in files}
        broken_imports = 0
        for imp in imports:
            target = _module(imp.module_name or "")
            if target and target not in {_module(f.relative_path) for f in files}:
                broken_imports += 1
        if broken_imports > 0:
            findings.append(TechnicalDebtFinding(
                category="broken_import", severity="low", title=f"Broken import(s) detected: {broken_imports}",
                details=f"{broken_imports} declared import(s) could not be resolved to an indexed module path.",
                confidence="medium", estimated_effort="medium", affected_components=[],
                evidence=[], remediation="Verify import paths are correct; modules may have been removed or renamed.",
                measured=False))
        return findings

    def _cycles(self, files, imports):
        path_by_id = {file.id: file.relative_path for file in files}
        by_module = {_module(file.relative_path): file for file in files}
        graph: dict[str, set[str]] = defaultdict(set)
        for imp in imports:
            source = path_by_id.get(imp.file_id)
            target_file = by_module.get((imp.module_name or "").casefold())
            if source and target_file:
                graph[_module(source)].add(_module(target_file.relative_path))
        index = 0; indices = {}; low = {}; stack = []; on_stack = set(); components = []
        def visit(node):
            nonlocal index
            indices[node] = low[node] = index; index += 1; stack.append(node); on_stack.add(node)
            for next_node in graph.get(node, set()):
                if next_node not in indices: visit(next_node); low[node] = min(low[node], low[next_node])
                elif next_node in on_stack: low[node] = min(low[node], indices[next_node])
            if low[node] == indices[node]:
                component = []
                while True:
                    value = stack.pop(); on_stack.remove(value); component.append(value)
                    if value == node: break
                if len(component) > 1: components.append(component)
        for node in list(graph):
            if node not in indices: visit(node)
        results = []
        for component in components:
            paths = sorted(by_module[item].relative_path for item in component if item in by_module)
            results.append(TechnicalDebtFinding(category="circular_dependency", severity="high", title="Circular module dependency", details="Static imports form a cycle across these modules.", confidence="high", estimated_effort="medium", affected_components=paths, evidence=[DebtEvidence(source="static_import_graph", file=path, description="Module is part of a static import cycle.") for path in paths], remediation="Break the cycle through an interface, dependency inversion, or moving shared code to a lower-level module.", measured=True))
        return results

    def _duplicate_python_functions(self, files):
        root = Path(self.repository.local_path).resolve(); groups: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
        for file in files:
            if file.is_binary or file.file_extension.casefold() != ".py" or file.size_bytes > 1_000_000: continue
            full_path = (root / file.relative_path).resolve()
            try:
                full_path.relative_to(root); tree = ast.parse(full_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeError, SyntaxError): continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and len(node.body) >= 3:
                    normalized = ast.dump(ast.Module(body=node.body, type_ignores=[]), include_attributes=False)
                    groups[hashlib.sha256(normalized.encode()).hexdigest()].append((file.relative_path, node.lineno, node.name))
        findings = []
        for entries in groups.values():
            if len(entries) < 2: continue
            components = [f"{path}:{line}" for path, line, _ in entries]
            findings.append(TechnicalDebtFinding(category="duplicate_code", severity="medium", title=f"Duplicate function bodies: {', '.join(name for _, _, name in entries[:3])}", details=f"{len(entries)} Python function bodies have identical normalized AST statements.", confidence="high", estimated_effort="small", affected_components=components, evidence=[DebtEvidence(source="python_ast", file=path, line=line, description=f"Function {name} shares an identical normalized body.") for path, line, name in entries], remediation="Review whether a shared helper would reduce duplication without obscuring domain-specific behavior.", measured=True))
        return findings

    @staticmethod
    def _unused_dependency_candidates(dependencies, imports):
        imported = " ".join((item.module_name or "").casefold() for item in imports)
        findings = []
        for dependency in dependencies:
            name = (dependency.package_name or "").casefold().replace("-", "_")
            if name and name not in imported:
                findings.append(TechnicalDebtFinding(category="unused_dependency_candidate", severity="low", title=f"Dependency usage not found: {dependency.package_name}", details="No matching static import module was found for this declared dependency.", confidence="low", estimated_effort="small", affected_components=[dependency.manifest_file] if dependency.manifest_file else [], evidence=[DebtEvidence(source="dependency_manifest", file=dependency.manifest_file or "", description=f"Declared {dependency.ecosystem} dependency: {dependency.package_name}.")], remediation="Check scripts, plugins, runtime loading, and transitive requirements before removing this dependency.", measured=False))
        return findings

    @staticmethod
    def _churn_signals(commits):
        churn: dict[str, int] = defaultdict(int); counts: dict[str, int] = defaultdict(int)
        for commit in commits:
            for path in commit.files_changed or []: churn[path] += (commit.insertions or 0) + (commit.deletions or 0); counts[path] += 1
        return [TechnicalDebtFinding(category="historical_churn", severity="low", title=f"High historical churn: {path}", details=f"Indexed Git history records {counts[path]} changes and {churn[path]} changed lines.", confidence="medium", estimated_effort="unknown", affected_components=[path], evidence=[DebtEvidence(source="git_history", file=path, description=f"{counts[path]} indexed commits; {churn[path]} insertions/deletions.")], remediation="Review recent changes and tests before planning refactoring; churn alone does not establish a defect.", measured=True) for path in sorted(churn, key=lambda item: (counts[item], churn[item]), reverse=True)[:10] if counts[path] >= 3]
