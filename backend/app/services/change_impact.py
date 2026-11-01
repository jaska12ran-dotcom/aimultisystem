import ast
import re
from collections import defaultdict, deque
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import (
    CodeImport,
    CodeRelationship,
    CodeSymbol,
    GitCommit,
    Repository,
    RepositoryFile,
)
from app.schemas.impact import (
    ImpactAnalysisResponse,
    ImpactComponent,
    ImpactEvidence,
    ImpactGraphEdge,
    ImpactGraphNode,
    ImpactRisk,
)


CALL_RELATIONSHIPS = {"calls", "inherits", "implements", "accesses", "references"}
IMPACT_RELATIONSHIPS = CALL_RELATIONSHIPS | {"implemented_by"}


def _path_key(value: str) -> str:
    return value.replace("\\", "/").strip("/").casefold()


def _module_key(path: str) -> str:
    path_obj = PurePosixPath(path.replace("\\", "/"))
    return ".".join(path_obj.with_suffix("").parts).casefold()


class ChangeImpactService:
    """Builds a traceable change-risk estimate from persisted repository evidence."""

    def __init__(self, db: AsyncSession, repository: Repository):
        self.db = db
        self.repository = repository

    @staticmethod
    def _detect_changed_symbols(
        file_path: str,
        changed_code: str,
        file_symbols: List[CodeSymbol],
    ) -> List[str]:
        changed: List[str] = []
        if not changed_code or not file_symbols:
            return changed

        ext = Path(file_path).suffix.casefold()
        if ext == ".py":
            try:
                tree = ast.parse(changed_code)
                new_funcs = {
                    node.name: node
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                }
                for sym in file_symbols:
                    if sym.name not in new_funcs:
                        changed.append(sym.qualified_name or sym.name)
                    else:
                        node = new_funcs[sym.name]
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            new_args = [a.arg for a in node.args.args]
                            old_params = [
                                p.get("name")
                                for p in (sym.parameters or [])
                                if isinstance(p, dict) and p.get("name")
                            ]
                            if old_params and new_args != old_params:
                                changed.append(sym.qualified_name or sym.name)
            except SyntaxError:
                return [s.qualified_name or s.name for s in file_symbols]
        else:
            for sym in file_symbols:
                pattern = rf"\b{re.escape(sym.name)}\b"
                if not re.search(pattern, changed_code):
                    changed.append(sym.qualified_name or sym.name)
        return changed

    async def analyze(
        self,
        query: str = "",
        file_path: Optional[str] = None,
        changed_code: Optional[str] = None,
        diff: Optional[str] = None,
    ) -> ImpactAnalysisResponse:
        files_result = await self.db.execute(
            select(RepositoryFile).where(
                RepositoryFile.repository_id == self.repository.id
            )
        )
        files = files_result.scalars().all()
        files_by_id = {file.id: file for file in files}

        symbols_result = await self.db.execute(
            select(CodeSymbol).where(CodeSymbol.repository_id == self.repository.id)
        )
        symbols = symbols_result.scalars().all()
        symbols_by_id = {symbol.id: symbol for symbol in symbols}

        effective_query = (query or file_path or "").strip()
        changed_symbols: List[str] = []
        if file_path and changed_code:
            matched_files = [f for f in files if _path_key(f.relative_path) == _path_key(file_path)]
            if matched_files:
                file_syms = [s for s in symbols if s.file_id == matched_files[0].id]
                changed_symbols = self._detect_changed_symbols(file_path, changed_code, file_syms)

        if changed_symbols:
            targets, match_kind = self._find_targets(changed_symbols[0], files, symbols, files_by_id)
        else:
            targets, match_kind = self._find_targets(effective_query, files, symbols, files_by_id)

        if not targets:
            return ImpactAnalysisResponse(
                repository_id=self.repository.id,
                symbol=effective_query or "unknown",
                affected_files=[],
                changed_symbols=changed_symbols,
                confidence=0.0,
                confidence_reasons=["No matching file or symbol was found in the indexed repository."],
            )

        selected_targets = list(targets)
        expanded_targets = list(targets)
        for item in selected_targets:
            selected_symbol = item.get("symbol")
            selected_file = item["file"]
            if selected_symbol is None:
                expanded_targets.extend(
                    {
                        "symbol": symbol,
                        "file": selected_file,
                        "selection_relation": "contained_in_selected_file",
                    }
                    for symbol in symbols
                    if symbol.file_id == selected_file.id
                )
            elif selected_symbol.symbol_type in {"class", "db_model", "interface", "enum"}:
                expanded_targets.extend(
                    {
                        "symbol": symbol,
                        "file": selected_file,
                        "selection_relation": "member_of_selected_type",
                        "selected_type": selected_symbol.qualified_name,
                    }
                    for symbol in symbols
                    if symbol.file_id == selected_file.id
                    and symbol.id != selected_symbol.id
                    and symbol.qualified_name.startswith(f"{selected_symbol.qualified_name}.")
                )

        target_symbol_ids = {
            item["symbol"].id for item in expanded_targets if item.get("symbol") is not None
        }
        target_file_ids = {item["file"].id for item in targets}

        relations_result = await self.db.execute(
            select(CodeRelationship).where(
                CodeRelationship.repository_id == self.repository.id
            )
        )
        relationships = relations_result.scalars().all()

        # In an edge A -> B, a change to B may affect A.
        dependents: Dict[str, List[CodeRelationship]] = defaultdict(list)
        explicit_test_edges: List[CodeRelationship] = []
        for relation in relationships:
            if relation.target_symbol_id and relation.source_symbol_id:
                if relation.relationship_type in IMPACT_RELATIONSHIPS:
                    dependents[relation.target_symbol_id].append(relation)
                if relation.relationship_type == "tests" and relation.target_symbol_id in target_symbol_ids:
                    explicit_test_edges.append(relation)

        imports_result = await self.db.execute(
            select(CodeImport).where(CodeImport.repository_id == self.repository.id)
        )
        imports = imports_result.scalars().all()
        import_dependents = self._find_import_dependents(
            imports, files_by_id, expanded_targets, target_symbol_ids
        )

        direct_by_key: Dict[Tuple[str, str], ImpactComponent] = {}
        indirect_by_key: Dict[Tuple[str, str], ImpactComponent] = {}
        affected_api_by_key: Dict[Tuple[str, str], ImpactComponent] = {}
        affected_test_by_key: Dict[Tuple[str, str], ImpactComponent] = {}
        target_components = []
        for item in expanded_targets:
            if item.get("symbol") is None:
                target_components.append(self._file_component(item["file"], "selected_target"))
                continue
            selection_relation = item.get("selection_relation", "selected_target")
            evidence = None
            if selection_relation != "selected_target":
                selected_type = item.get("selected_type", item["file"].relative_path)
                evidence = ImpactEvidence(
                    source="repository_structure",
                    file=item["file"].relative_path,
                    line=item["symbol"].start_line,
                    description=f"{item['symbol'].qualified_name} is {selection_relation.replace('_', ' ')}: {selected_type}.",
                )
            target_components.append(
                self._symbol_component(item["symbol"], files_by_id, selection_relation, evidence)
            )

        graph_nodes: Dict[str, ImpactGraphNode] = {}
        graph_edges: Dict[Tuple[str, str, str, str, Optional[int]], ImpactGraphEdge] = {}
        for component in target_components:
            self._add_graph_node(graph_nodes, component, "target")

        first_level: Set[str] = set()
        for target_id in target_symbol_ids:
            for relation in dependents.get(target_id, []):
                if relation.source_symbol_id in target_symbol_ids:
                    continue
                component = self._relationship_component(
                    relation, symbols_by_id, files_by_id
                )
                if component is None:
                    continue
                self._add_component(direct_by_key, component)
                first_level.add(relation.source_symbol_id)
                target_symbol = symbols_by_id.get(relation.target_symbol_id)
                source_symbol = symbols_by_id.get(relation.source_symbol_id)
                if target_symbol and source_symbol:
                    self._add_graph_relation(
                        graph_nodes, graph_edges, target_symbol, source_symbol,
                        files_by_id, relation, "direct",
                    )
                if component.symbol_type == "api_route":
                    self._add_component(affected_api_by_key, component)

        # Resolve import edges at file/module level; the imported symbol list narrows
        # the match where available, while wildcard/module imports remain file-level.
        for file, reason, line in import_dependents:
            component = self._file_component(file, "imports_changed_module", line, reason)
            self._add_component(direct_by_key, component)
            for item in expanded_targets:
                if item["file"].id == file.id:
                    continue
                evidence = ImpactEvidence(
                    source="repository_import",
                    file=file.relative_path,
                    line=line,
                    description=reason or f"{file.relative_path} imports the selected module.",
                )
                target_component = next((
                    candidate for candidate in target_components
                    if candidate.file == item["file"].relative_path
                    and (item.get("symbol") is None or candidate.symbol == item["symbol"].qualified_name)
                ), None)
                if target_component:
                    self._add_graph_edge_from_components(
                        graph_nodes, graph_edges, target_component, component,
                        "imports", evidence, "direct",
                    )
                    break

        # Walk only code dependency relationships for indirect impact. Test edges are
        # classified separately and do not inflate the transitive call graph.
        queue = deque((symbol_id, 1) for symbol_id in first_level)
        visited = set(first_level) | target_symbol_ids
        while queue:
            impacted_id, depth = queue.popleft()
            if depth >= 4:
                continue
            for relation in dependents.get(impacted_id, []):
                source_id = relation.source_symbol_id
                if source_id in visited:
                    continue
                visited.add(source_id)
                component = self._relationship_component(
                    relation, symbols_by_id, files_by_id
                )
                if component is not None:
                    self._add_component(indirect_by_key, component)
                    target_symbol = symbols_by_id.get(relation.target_symbol_id)
                    source_symbol = symbols_by_id.get(relation.source_symbol_id)
                    if target_symbol and source_symbol:
                        self._add_graph_relation(
                            graph_nodes, graph_edges, target_symbol, source_symbol,
                            files_by_id, relation, "indirect", changed_category="direct",
                        )
                    if component.symbol_type == "api_route":
                        self._add_component(affected_api_by_key, component)
                queue.append((source_id, depth + 1))

        for relation in explicit_test_edges:
            component = self._relationship_component(
                relation, symbols_by_id, files_by_id
            )
            if component is not None:
                self._add_component(affected_test_by_key, component)
                self._add_component(direct_by_key, component)

        impacted_ids = target_symbol_ids | first_level | visited
        test_components = self._find_test_files(
            files,
            symbols,
            files_by_id,
            symbols_by_id,
            relationships,
            imports,
            impacted_ids,
            targets,
        )
        for component in test_components:
            self._add_component(affected_test_by_key, component)

        # A selected API is itself an affected API; otherwise include APIs reached
        # through direct or indirect code relationships.
        for component in target_components:
            if component.symbol_type == "api_route":
                self._add_component(affected_api_by_key, component)

        changed_file_ids = target_file_ids | {
            component_file_id
            for component_file_id in (
                self._component_file_id(component, symbols_by_id, files)
                for component in list(direct_by_key.values()) + list(indirect_by_key.values())
            )
            if component_file_id
        }
        commits = await self._recent_matching_commits(changed_file_ids, files_by_id)

        risks = self._build_risks(
            targets,
            list(direct_by_key.values()),
            list(indirect_by_key.values()),
            list(affected_api_by_key.values()),
            list(affected_test_by_key.values()),
            commits,
        )
        confidence, confidence_reasons = self._confidence(
            match_kind,
            len(targets),
            sum(
                1
                for relation in relationships
                if relation.relationship_type in IMPACT_RELATIONSHIPS
                and relation.target_symbol_id in (target_symbol_ids | first_level)
            ),
            len(import_dependents),
            commits,
            len(affected_test_by_key),
        )

        modules = self._modules(targets, direct_by_key.values(), indirect_by_key.values(), files_by_id, symbols_by_id)

        # Collect all affected files across direct, indirect, API, tests, and module dependencies
        affected_files_set: Set[str] = set()
        for comp in direct_by_key.values():
            if comp.file:
                affected_files_set.add(comp.file)
        for comp in indirect_by_key.values():
            if comp.file:
                affected_files_set.add(comp.file)
        for comp in affected_api_by_key.values():
            if comp.file:
                affected_files_set.add(comp.file)
        for comp in affected_test_by_key.values():
            if comp.file:
                affected_files_set.add(comp.file)
        for mod in modules:
            if mod.file:
                affected_files_set.add(mod.file)

        target_file_paths = {
            item["file"].relative_path for item in targets if "file" in item and item["file"]
        }
        ordered_affected_files = sorted(affected_files_set - target_file_paths)
        if target_file_paths:
            ordered_affected_files = sorted(target_file_paths) + ordered_affected_files

        if changed_symbols:
            confidence_reasons.append(
                f"Detected code modifications in symbols: {', '.join(changed_symbols[:5])}"
            )

        return ImpactAnalysisResponse(
            repository_id=self.repository.id,
            symbol=effective_query,
            affected_files=ordered_affected_files,
            changed_symbols=changed_symbols,
            target=target_components,
            direct_impact=self._sorted(direct_by_key.values()),
            indirect_impact=self._sorted(indirect_by_key.values()),
            affected_apis=self._sorted(affected_api_by_key.values()),
            affected_modules=self._sorted(modules),
            affected_tests=self._sorted(affected_test_by_key.values()),
            potential_risks=risks,
            graph_nodes=list(graph_nodes.values()),
            graph_edges=list(graph_edges.values()),
            confidence=confidence,
            confidence_reasons=confidence_reasons,
        )

    @staticmethod
    def _graph_node_id(file: str, symbol: str) -> str:
        return f"{_path_key(file)}::{symbol.casefold()}"

    @classmethod
    def _add_graph_node(cls, nodes, component, category):
        node_id = cls._graph_node_id(component.file, component.symbol)
        current = nodes.get(node_id)
        if current is None or (current.category != "target" and category == "target"):
            nodes[node_id] = ImpactGraphNode(
                id=node_id,
                symbol=component.symbol,
                file=component.file,
                category=category,
                line=component.start_line,
            )
        return node_id

    @classmethod
    def _add_graph_edge_from_components(cls, nodes, edges, source_component, target_component, relationship, evidence, target_category, source_category="target"):
        source_id = cls._add_graph_node(nodes, source_component, source_category)
        target_id = cls._add_graph_node(nodes, target_component, target_category)
        key = (source_id, target_id, relationship, evidence.file, evidence.line)
        edges.setdefault(key, ImpactGraphEdge(
            source=source_id,
            target=target_id,
            relationship=relationship,
            evidence=evidence,
        ))

    @classmethod
    def _add_graph_relation(cls, nodes, edges, changed_symbol, dependent_symbol, files_by_id, relation, category, changed_category="target"):
        changed_file = files_by_id.get(changed_symbol.file_id)
        dependent_file = files_by_id.get(dependent_symbol.file_id)
        if changed_file is None or dependent_file is None:
            return
        changed_component = cls._symbol_component(changed_symbol, files_by_id, "selected_target")
        dependent_component = cls._symbol_component(dependent_symbol, files_by_id, relation.relationship_type)
        evidence_file = files_by_id.get(relation.source_file_id)
        evidence = ImpactEvidence(
            source="dependency_graph",
            file=evidence_file.relative_path if evidence_file else dependent_file.relative_path,
            line=relation.evidence_line,
            description=relation.evidence_text or f"{dependent_symbol.qualified_name} {relation.relationship_type} {changed_symbol.qualified_name}.",
        )
        cls._add_graph_edge_from_components(
            nodes, edges, changed_component, dependent_component,
            relation.relationship_type, evidence, category, source_category=changed_category,
        )

    @staticmethod
    def _find_targets(query, files, symbols, files_by_id):
        normalized = _path_key(query)
        file_matches = [item for item in files if _path_key(item.relative_path) == normalized]
        if file_matches:
            return [{"file": item} for item in file_matches], "file"

        name = query.strip().casefold()
        exact_qualified = [item for item in symbols if item.qualified_name.casefold() == name]
        if exact_qualified:
            return [{"symbol": item, "file": files_by_id[item.file_id]} for item in exact_qualified], "qualified"

        leaf_name = name.rsplit(".", 1)[-1]
        exact_name = [item for item in symbols if item.name.casefold() == leaf_name]
        if "." in name:
            module_prefix = name.rsplit(".", 1)[0]
            module_matches = [
                item
                for item in exact_name
                if _module_key(files_by_id[item.file_id].relative_path).endswith(module_prefix)
            ]
            if module_matches:
                return [{"symbol": item, "file": files_by_id[item.file_id]} for item in module_matches], "qualified"
        if exact_name:
            return [{"symbol": item, "file": files_by_id[item.file_id]} for item in exact_name], "name"

        suffix_matches = [
            item
            for item in symbols
            if item.qualified_name.casefold().endswith(f".{name}")
        ]
        return (
            [{"symbol": item, "file": files_by_id[item.file_id]} for item in suffix_matches],
            "qualified" if suffix_matches else "missing",
        )

    @staticmethod
    def _find_import_dependents(imports, files_by_id, targets, target_symbol_ids):
        target_modules = {_module_key(item["file"].relative_path) for item in targets}
        target_stems = {
            PurePosixPath(item["file"].relative_path.replace("\\", "/")).stem.casefold()
            for item in targets
        }
        target_names = {
            item["symbol"].name.casefold()
            for item in targets
            if item.get("symbol") is not None
        }
        results = []
        for imp in imports:
            source_file = files_by_id.get(imp.file_id)
            if source_file is None or imp.file_id in {item["file"].id for item in targets}:
                continue
            module = (imp.module_name or "").strip().replace("\\", "/").strip(".").replace("/", ".").casefold()
            module_leaf = module.rsplit(".", 1)[-1]
            matches_module = any(
                module == target or module.endswith(f".{target}") or target.endswith(f".{module}")
                for target in target_modules
            ) or module_leaf in target_stems
            imported = {str(value).casefold() for value in (imp.imported_symbols or [])}
            matches_symbol = bool(target_names & imported)
            if matches_module and (not imported or matches_symbol):
                results.append((
                    source_file,
                    f"Import '{imp.module_name}' may depend on the changed module or symbol.",
                    imp.line_number,
                ))
        return results

    @staticmethod
    def _symbol_component(symbol, files_by_id, relationship, evidence=None):
        file = files_by_id.get(symbol.file_id)
        return ImpactComponent(
            symbol=symbol.qualified_name or symbol.name,
            symbol_type=symbol.symbol_type,
            file=file.relative_path if file else "",
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            relationship=relationship,
            evidence=[evidence] if evidence else [],
        )

    @staticmethod
    def _file_component(file, relationship, line=None, reason=None):
        return ImpactComponent(
            symbol=PurePosixPath(file.relative_path.replace("\\", "/")).stem,
            symbol_type="module",
            file=file.relative_path,
            relationship=relationship,
            evidence=[
                ImpactEvidence(
                    source="repository_import",
                    file=file.relative_path,
                    line=line,
                    description=reason or f"Repository file {file.relative_path} is in the impact set.",
                )
            ],
        )

    @classmethod
    def _relationship_component(cls, relation, symbols_by_id, files_by_id):
        symbol = symbols_by_id.get(relation.source_symbol_id)
        if symbol is None:
            return None
        evidence_file = files_by_id.get(relation.source_file_id)
        evidence = ImpactEvidence(
            source="dependency_graph",
            file=evidence_file.relative_path if evidence_file else "",
            line=relation.evidence_line,
            description=relation.evidence_text or (
                f"{symbol.qualified_name} has a {relation.relationship_type} relationship "
                "to the selected or affected symbol."
            ),
        )
        return cls._symbol_component(
            symbol,
            files_by_id,
            relation.relationship_type,
            evidence,
        )

    @staticmethod
    def _add_component(destination, component):
        key = (component.file.casefold(), component.symbol.casefold())
        existing = destination.get(key)
        if existing is None:
            destination[key] = component
            return
        known = {
            (item.source, item.file, item.line, item.description)
            for item in existing.evidence
        }
        existing.evidence.extend(
            item for item in component.evidence
            if (item.source, item.file, item.line, item.description) not in known
        )

    def _find_test_files(
        self, files, symbols, files_by_id, symbols_by_id, relationships,
        imports, impacted_ids, targets,
    ):
        impacted_names = {
            symbols_by_id[item].name.casefold()
            for item in impacted_ids
            if item in symbols_by_id
        }
        impacted_module_names = {
            PurePosixPath(item["file"].relative_path.replace("\\", "/")).stem.casefold()
            for item in targets
        }
        test_evidence: Dict[str, ImpactEvidence] = {}
        for relation in relationships:
            source = symbols_by_id.get(relation.source_symbol_id)
            target = symbols_by_id.get(relation.target_symbol_id)
            if relation.relationship_type == "tests" and source and target:
                source_file = files_by_id.get(source.file_id)
                if source_file and source_file.is_test and relation.target_symbol_id in impacted_ids:
                    test_evidence[source_file.id] = ImpactEvidence(
                        source="test_relationship",
                        file=source_file.relative_path,
                        line=relation.evidence_line,
                        description=relation.evidence_text or f"{source.name} tests {target.name}.",
                    )
        imports_by_file: Dict[str, List[CodeImport]] = defaultdict(list)
        for imp in imports:
            imports_by_file[imp.file_id].append(imp)
        for file in files:
            if not file.is_test:
                continue
            evidence = test_evidence.get(file.id)
            if evidence is None:
                linked = [
                    rel for rel in relationships
                    if rel.source_file_id == file.id
                    and rel.target_symbol_id in impacted_ids
                    and rel.relationship_type in CALL_RELATIONSHIPS | {"tests"}
                ]
                if linked:
                    rel = linked[0]
                    evidence = ImpactEvidence(
                        source="test_call_graph",
                        file=file.relative_path,
                        line=rel.evidence_line,
                        description=rel.evidence_text or "Test file contains a relationship to impacted code.",
                    )
                elif any(
                    imp.module_name.casefold().split(".")[-1] in impacted_module_names
                    or bool({str(value).casefold() for value in (imp.imported_symbols or [])} & impacted_names)
                    for imp in imports_by_file.get(file.id, [])
                ):
                    evidence = ImpactEvidence(
                        source="test_import",
                        file=file.relative_path,
                        description="Test file imports the changed module or one of its impacted symbols.",
                    )
                elif any(name in file.relative_path.casefold() for name in impacted_module_names | impacted_names):
                    evidence = ImpactEvidence(
                        source="test_path_match",
                        file=file.relative_path,
                        description="Test file path refers to the changed module or symbol; association is inferred from naming.",
                    )
            if evidence:
                component = self._file_component(file, "tests_impacted", evidence.line, evidence.description)
                component.evidence = [evidence]
                test_evidence[file.id] = evidence
        return [
            self._file_component(
                files_by_id[file_id],
                "tests_impacted",
                evidence.line,
                evidence.description,
            ).model_copy(update={"evidence": [evidence]})
            for file_id, evidence in test_evidence.items()
            if file_id in files_by_id
        ]

    async def _recent_matching_commits(self, file_ids, files_by_id):
        if not file_ids:
            return []
        paths = {_path_key(files_by_id[file_id].relative_path) for file_id in file_ids if file_id in files_by_id}
        result = await self.db.execute(
            select(GitCommit)
            .where(GitCommit.repository_id == self.repository.id)
            .order_by(GitCommit.committed_at.desc())
            .limit(100)
        )
        matching = []
        for commit in result.scalars().all():
            changed_paths = {_path_key(str(path)) for path in (commit.files_changed or [])}
            overlap = paths & changed_paths
            if overlap:
                matching.append((commit, overlap))
        return matching

    @staticmethod
    def _build_risks(targets, direct, indirect, apis, tests, commits):
        risks = []
        evidence = []
        for component in direct[:5]:
            evidence.extend(component.evidence[:1])
        if direct:
            risks.append(ImpactRisk(
                severity="medium" if len(direct) < 5 else "high",
                description=f"The change may affect {len(direct)} directly connected component(s).",
                evidence=evidence,
            ))
        if indirect:
            risks.append(ImpactRisk(
                severity="medium",
                description=f"Changes may propagate through {len(indirect)} indirect dependent component(s).",
                evidence=[item for component in indirect[:5] for item in component.evidence[:1]],
            ))
        if apis:
            risks.append(ImpactRisk(
                severity="high",
                description=f"{len(apis)} API endpoint(s) are in the impact set; externally visible behavior may change.",
                evidence=[item for component in apis[:5] for item in component.evidence[:1]],
            ))
        if not tests:
            risks.append(ImpactRisk(
                severity="medium",
                description="No related test file was identified in indexed repository evidence; regression coverage may be incomplete.",
                evidence=[
                    ImpactEvidence(
                        source="repository_index",
                        file=item["file"].relative_path,
                        description="No linked or name-matched test file was found for this target.",
                    )
                    for item in targets
                ],
            ))
        if commits:
            recent = commits[:5]
            risks.append(ImpactRisk(
                severity="informational",
                description=f"Git history shows {len(commits)} recent commit(s) touching files in this impact set.",
                evidence=[
                    ImpactEvidence(
                        source="git_history",
                        file=next(iter(paths)),
                        description=f"{commit.commit_hash[:12]}: {commit.message}",
                    )
                    for commit, paths in recent
                ],
            ))
        if not risks:
            risks.append(ImpactRisk(
                severity="informational",
                description="No dependency edges or additional risks were identified; unindexed or dynamic relationships may still exist.",
                evidence=[
                    ImpactEvidence(
                        source="repository_index",
                        file=item["file"].relative_path,
                        description="Risk assessment is limited to relationships present in the repository index.",
                    )
                    for item in targets
                ],
            ))
        return risks

    @staticmethod
    def _confidence(match_kind, target_count, relationship_count, import_count, commits, tests_count):
        score = {"file": 0.78, "qualified": 0.88, "name": 0.74}.get(match_kind, 0.5)
        reasons = [f"Target matched by {match_kind} lookup."]
        if target_count > 1:
            score -= min(0.15, 0.04 * (target_count - 1))
            reasons.append(f"Target name matched {target_count} definitions, so the result may span multiple locations.")
        if relationship_count:
            score += 0.04
            reasons.append("Persisted call/inheritance relationship evidence was available.")
        else:
            reasons.append("No persisted symbol relationship edges were available.")
        if import_count:
            score += 0.02
            reasons.append(f"Repository import evidence identified {import_count} potentially dependent file(s).")
        if tests_count:
            score += 0.03
            reasons.append(f"Related test evidence was found in {tests_count} test component(s).")
        if commits:
            score += 0.02
            reasons.append(f"Git history provided evidence for {len(commits)} recent matching commit(s).")
        return round(max(0.0, min(1.0, score)), 2), reasons

    @staticmethod
    def _component_file_id(component, symbols_by_id, files):
        for file in files:
            if file.relative_path == component.file:
                return file.id
        for symbol in symbols_by_id.values():
            if symbol.qualified_name == component.symbol:
                return symbol.file_id
        return None

    @classmethod
    def _modules(cls, targets, direct, indirect, files_by_id, symbols_by_id):
        components = list(direct) + list(indirect)
        output = {}
        for target in targets:
            file = target["file"]
            output[file.relative_path.casefold()] = cls._file_component(file, "target_module")
        for component in components:
            output.setdefault(
                component.file.casefold(),
                ImpactComponent(
                    symbol=PurePosixPath(component.file.replace("\\", "/")).stem,
                    symbol_type="module",
                    file=component.file,
                    relationship="affected_module",
                    evidence=component.evidence,
                ),
            )
        return list(output.values())

    @staticmethod
    def _sorted(components: Iterable[ImpactComponent]):
        unique = {(item.file.casefold(), item.symbol.casefold()): item for item in components}
        return sorted(unique.values(), key=lambda item: (item.file.casefold(), item.start_line or 0, item.symbol.casefold()))
