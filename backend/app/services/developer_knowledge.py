from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import CodeImport, CodeRelationship, CodeSymbol, GitCommit, Repository, RepositoryFile
from app.schemas.developer_knowledge import BusinessRule, BusinessRuleResponse, CodeMemoryResponse, OnboardingResponse, OnboardingStep, SourceReference


class DeveloperKnowledgeService:
    def __init__(self, db: AsyncSession, repository: Repository):
        self.db = db
        self.repository = repository

    async def _records(self):
        files = (await self.db.execute(select(RepositoryFile).where(RepositoryFile.repository_id == self.repository.id))).scalars().all()
        symbols = (await self.db.execute(select(CodeSymbol).where(CodeSymbol.repository_id == self.repository.id))).scalars().all()
        relationships = (await self.db.execute(select(CodeRelationship).where(CodeRelationship.repository_id == self.repository.id))).scalars().all()
        imports = (await self.db.execute(select(CodeImport).where(CodeImport.repository_id == self.repository.id))).scalars().all()
        return files, symbols, relationships, imports

    async def onboarding(self) -> OnboardingResponse:
        files, symbols, relationships, imports = await self._records()
        by_id = {item.id: item for item in files}
        entry_symbols = [item for item in symbols if item.symbol_type == "api_route"]
        entry_files = [item for item in files if Path(item.relative_path).name.casefold() in {"main.py", "app.py", "manage.py", "main.ts", "index.ts", "server.ts"}]
        # Entry points: explicitly indexed API routes first, then conventional filenames
        entries: list[SourceReference] = []
        for item in entry_symbols:
            if item.file_id in by_id:
                entries.append(SourceReference(file=by_id[item.file_id].relative_path, line=item.start_line, description=f"Indexed {item.symbol_type}: {item.qualified_name} (entry point)"))
        for item in entry_files:
            if item.relative_path not in {entry.file for entry in entries}:
                entries.append(SourceReference(file=item.relative_path, description=f"Conventional application entry-point filename."))
        # Important modules: rank by public role (api_route > db_model > class > function) and complexity
        important: list[CodeSymbol] = sorted(symbols, key=lambda item: ((item.symbol_type not in {"api_route", "db_model", "class"}), -(item.complexity_score or 1)))[:20]
        important_refs: list[SourceReference] = []
        for item in important:
            if item.file_id in by_id and item.symbol_type in {"api_route", "db_model", "class"}:
                important_refs.append(SourceReference(file=by_id[item.file_id].relative_path, line=item.start_line, description=f"{item.symbol_type}: {item.qualified_name}"))
        # Build relationship maps for guided paths
        forward: dict[str, list[CodeRelationship]] = defaultdict(list)  # source -> targets
        backward: dict[str, list[CodeRelationship]] = defaultdict(list)  # target -> sources
        for relation in relationships:
            if relation.source_symbol_id and relation.target_symbol_id:
                fwd_key = f'{relation.source_symbol_id}'.casefold()
                bwd_key = f'{relation.target_symbol_id}'.casefold()
                forward[fwd_key].append(relation)
                backward[bwd_key].append(relation)
        # Learning tasks: specific code-reading assignments based on top symbols
        top_symbols = important[:8]
        learning: list[OnboardingStep] = []
        for idx, item in enumerate(top_symbols):
            if item.file_id not in by_id:
                continue
            level = "beginner" if idx < 2 else "intermediate" if idx < 5 else "advanced"
            # Gather callers and dependents from the indexed graph
            callers: list[SourceReference] = []
            dependents: list[SourceReference] = []
            sym_key = item.id.casefold()
            for rel in forward.get(sym_key, []):
                sf = by_id.get(rel.source_file_id)
                if sf:
                    callers.append(SourceReference(file=sf.relative_path, line=rel.evidence_line, description=f"Caller via {rel.relationship_type}"))
            for rel in backward.get(sym_key, []):
                sf = by_id.get(rel.source_file_id)
                if sf:
                    dependents.append(SourceReference(file=sf.relative_path, line=rel.evidence_line, description=f"Dependant via {rel.relationship_type}"))
            sig = item.signature or f"{item.symbol_type} {item.name}"
            dep_type = "callers" if idx < 2 else "dependents" if idx < 5 else "downstream dependencies"
            file_rel = by_id[item.file_id].relative_path
            learning.append(OnboardingStep(
                title=f"Analyze {item.qualified_name}",
                level=level,
                description=(f"Read the signature {sig} at [{file_rel}:{item.start_line}-{item.end_line}]. "
                            f"Identify its inputs, outputs, and {dep_type} from the repository graph."),
                references=[SourceReference(file=file_rel, line=item.start_line, description=sig)] + (callers[:3] if idx < 2 else dependents[:3] if idx < 5 else callers[:2] + dependents[:2])
            ))
        # Enhanced guided paths with 3 tiers
        paths: list[OnboardingStep] = []
        # Beginner: start at entry points and read simple flow
        if entries:
            paths.append(OnboardingStep(
                title="Begin at indexed entry points",
                level="beginner",
                description="Start with request handlers or conventional entry files, then follow cited code relationships to explore downstream logic.",
                references=entries[:6]
            ))
        # Intermediate: trace key modules and their relationships
        if important_refs:
            paths.append(OnboardingStep(
                title="Trace key modules and their relationships",
                level="intermediate",
                description="Read the listed API, model, and class definitions. For each, follow the indexed forward/backward relationships to understand downstream and upstream code.",
                references=important_refs[:8]
            ))
        # Advanced: follow observed data and call flow through the graph
        if relationships:
            # Sample a few relationships to show the data-driven path
            sample_rels = relationships[:12]
            rel_refs: list[SourceReference] = []
            for rel in sample_rels:
                sf = by_id.get(rel.source_file_id)
                tf = by_id.get(rel.target_file_id) if rel.target_file_id else None
                s_sym = by_id.get(rel.source_symbol_id) if rel.source_symbol_id else None
                t_sym = by_id.get(rel.target_symbol_id) if rel.target_symbol_id else None
                s_desc = f" {rel.source_symbol_id}: {s_sym.qualified_name if s_sym else '?'} at {sf.relative_path}:{sf.start_line}-{sf.end_line}" if sf and s_sym else ""
                t_desc = f" {rel.target_symbol_id}: {t_sym.qualified_name if t_sym else '?'} at {tf.relative_path}:{tf.start_line}-{tf.end_line}" if tf and t_sym else ""
                rel_refs.append(SourceReference(file=sf.relative_path if sf else "", line=rel.evidence_line, description=f"{rel.relationship_type} relationship{s_desc}{t_desc}"))
            paths.append(OnboardingStep(
                title="Follow observed data and call flow",
                level="advanced",
                description="Use these persisted call/import relationships to inspect downstream code. Dynamic relationships, fixtures, and runtime-generated paths may be absent.",
                references=rel_refs
            ))
        test_files = [item.relative_path for item in files if item.is_test]
        return OnboardingResponse(repository_id=self.repository.id, overview=f"Indexed repository contains {len(files)} files, {len(symbols)} symbols, and {len(relationships)} persisted relationships.", entry_points=entries, important_modules=important_refs, guided_paths=paths, learning_tasks=learning, testing_instructions=["Start by reviewing indexed test files such as " + ", ".join(test_files[:5]) + "." if test_files else "No test files were identified in the repository index. Use the Tests workspace to inspect static test mappings before executing tests.", "Use the Code relationship graph to trace forward (callers) and backward (dependents) from any symbol."], limitations=["Reading order is based on indexed file names, symbol roles, and static relationships; it does not infer unrecorded business context.", "Call/data flow references are static repository evidence and can omit runtime, framework, or generated paths. " "Probabilistic or dynamically constructed paths will not appear in the graph."])

    async def business_rules(self) -> BusinessRuleResponse:
        files, symbols, _, imports = await self._records()
        by_id = {item.id: item for item in files}; root = Path(self.repository.local_path).resolve()
        api_by_file = defaultdict(list)
        for symbol in symbols:
            if symbol.symbol_type == "api_route": api_by_file[symbol.file_id].append(symbol)
        tests = [item for item in files if item.is_test]
        rules = []
        for file in files:
            if file.is_binary or file.file_extension.casefold() != ".py" or file.size_bytes > 1_000_000: continue
            full_path = (root / file.relative_path).resolve()
            try:
                full_path.relative_to(root); tree = ast.parse(full_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeError, SyntaxError): continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.If) or not getattr(node, "lineno", None): continue
                condition = ast.unparse(node.test)
                raises = [child for child in node.body if isinstance(child, ast.Raise)]
                explicit = bool(raises)
                description = f"When `{condition}`, the code {'raises an error' if raises else 'takes a conditional branch'}."
                related_apis = [SourceReference(file=file.relative_path, line=item.start_line, description=f"API route {item.qualified_name} is defined in this module.") for item in api_by_file[file.id]]
                related_tests = [SourceReference(file=test.relative_path, description="Test filename matches the production module name.") for test in tests if Path(file.relative_path).stem.casefold() in test.relative_path.casefold()]
                rules.append(BusinessRule(rule_type="validation" if raises else "conditional", description=description, confidence="high" if explicit else "medium", explicit=explicit, source_evidence=[SourceReference(file=file.relative_path, line=node.lineno, description=f"Observed condition: {condition}.")], related_tests=related_tests, related_apis=related_apis, contradictions=[]))
        return BusinessRuleResponse(repository_id=self.repository.id, rules=rules[:100], limitations=["Rules are extracted from static Python conditional logic only; they are candidates for review, not a complete business specification.", "A conditional without an exception is treated as an inferred rule, and dynamic behavior or configuration can change its meaning.", "Conflicts are reported only when direct contradictory indexed evidence is available; none is inferred from absence."])

    async def code_memory(self, target: str) -> CodeMemoryResponse:
        files, symbols, relationships, imports = await self._records(); needle = target.casefold()
        matched: list[RepositoryFile] = []
        # 1. Match by file path containing the target
        for f in files:
            if needle in f.relative_path.casefold():
                matched.append(f)
        # 2. Match by exact symbol name or qualified name
        by_id = {item.id: item for item in files}
        symbol_matches: set[str] = set()
        for s in symbols:
            if needle == s.name.casefold() or needle == s.qualified_name.casefold():
                symbol_matches.add(s.file_id)
        for fid in symbol_matches:
            f = by_id.get(fid)
            if f and f not in matched:
                matched.append(f)
        # 3. Match by symbol name appearing in file paths
        for s in symbols:
            if needle in s.name.casefold() and s.file_id in by_id:
                if by_id[s.file_id].relative_path not in [m.relative_path for m in matched]:
                    matched.append(by_id[s.file_id])
        paths = {file.relative_path.replace("\\", "/").casefold() for file in matched}
        # Git history: connect commits that touched matched files to the target
        commits = (await self.db.execute(select(GitCommit).where(GitCommit.repository_id == self.repository.id).order_by(GitCommit.committed_at.desc()).limit(200))).scalars().all()
        # Build a set of matched file paths for commit filtering
        matched_path_set = {str(p.replace("\\", "/")).casefold() for p in paths}
        evidence: list[dict] = []
        for commit in commits:
            changed = commit.files_changed or []
            changed_paths = {str(p.replace("\\", "/")).casefold() for p in changed}
            if changed_paths & matched_path_set:
                evidence.append({"commit_hash": commit.commit_hash, "message": commit.message, "author": commit.author_name, "timestamp": commit.committed_at, "files_changed": commit.files_changed})
        # Documentation references: documentation files that mention the target
        docs = [file for file in files if file.is_documentation]
        references: list[SourceReference] = []
        for doc in docs:
            if needle in doc.relative_path.casefold():
                references.append(SourceReference(file=doc.relative_path, description="Repository documentation file; search its content for target references."))
        # Enhance summary with symbol info
        matched_symbols = [s for s in symbols if any(f.id == s.file_id for f in matched)]
        summary = (f"Found {len(matched)} matching file(s) and {len(evidence)} matching indexed commit(s). "
                  f"Matched {len(matched_symbols)} symbol(s)." if matched else "No indexed file or symbol matched this target.")
        return CodeMemoryResponse(repository_id=self.repository.id, target=target, matched_files=[file.relative_path for file in matched], history_available=bool(commits), commits=evidence[:20], documentation_references=references[:10], summary=summary, limitations=["Commit records show files changed together and commit messages; they do not prove developer intent.", "Pull requests and issue records are unavailable unless separately imported and connected.", "Symbol matching is based on exact name/qualified-name comparison; partial or fuzzy matches are not supported."])
