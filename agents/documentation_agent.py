from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import Repository, RepositoryFile
from app.services.graph.service import CodeKnowledgeGraphService
from app.services.rag.service import RepositoryRetriever
from intelligence.retriever import ASTRetriever
from intelligence.llm_client import default_llm_client


@dataclass
class DocumentationEvidence:
    file: str
    symbol: str
    start_line: int
    end_line: int
    reason: str
    source: str = "repository"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "symbol": self.symbol,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass
class DocumentationSection:
    title: str
    section_type: str
    content: str
    evidence: List[DocumentationEvidence] = field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    unsupported_statements: List[str] = field(default_factory=list)
    verified: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "section_type": self.section_type,
            "content": self.content,
            "evidence": [item.to_dict() for item in self.evidence],
            "confidence": self.confidence,
            "unsupported_statements": self.unsupported_statements,
            "verified": self.verified,
        }


class DocumentationAgent:
    """Deterministic documentation generator grounded in repository evidence."""

    def __init__(self, llm_client=default_llm_client):
        self.llm = llm_client

    async def generate_documentation(
        self,
        db: AsyncSession,
        repo_id: str,
        doc_type: str,
        title: str = None,
        target_file: str = None,
        custom_prompt: str = None,
        include_verification: bool = False,
    ) -> Tuple[str, str, List[str], List[str]]:
        bundle = await self.generate_documentation_bundle(
            db=db,
            repo_id=repo_id,
            doc_type=doc_type,
            title=title,
            target_file=target_file,
            custom_prompt=custom_prompt,
        )
        return (
            bundle["title"],
            bundle["content"],
            bundle["grounded_symbols"],
            bundle["grounded_files"],
        )

    async def generate_documentation_bundle(
        self,
        db: AsyncSession,
        repo_id: str,
        doc_type: str,
        title: str = None,
        target_file: str = None,
        custom_prompt: str = None,
    ) -> Dict[str, Any]:
        overview = await ASTRetriever.get_repository_overview(db, repo_id)
        repo_name = overview["repository_name"]
        section = await self._build_section(db, repo_id, doc_type, overview, target_file, title, custom_prompt)
        return {
            "title": section.title,
            "content": section.content,
            "grounded_symbols": section.evidence and [item.symbol for item in section.evidence if item.symbol],
            "grounded_files": sorted({item.file for item in section.evidence}),
            "evidence": [item.to_dict() for item in section.evidence],
            "confidence": section.confidence,
            "unsupported_statements": section.unsupported_statements,
            "verified": section.verified,
            "section_type": section.section_type,
        }

    async def _build_section(
        self,
        db: AsyncSession,
        repo_id: str,
        doc_type: str,
        overview: Dict[str, Any],
        target_file: Optional[str],
        title: Optional[str],
        custom_prompt: Optional[str],
    ) -> DocumentationSection:
        repo_name = overview["repository_name"]

        if doc_type == "architecture":
            doc_title = title or f"{repo_name} — System Architecture & Design Overview"
            content = await self._generate_architecture_doc(overview)
            evidence = await self._collect_evidence(db, repo_id, "repository architecture overview", overview)
        elif doc_type == "api":
            doc_title = title or f"{repo_name} — API & Endpoint Reference"
            content = await self._generate_api_doc(overview)
            evidence = await self._collect_evidence(db, repo_id, "repository API routes and handlers", overview)
        elif doc_type == "models":
            doc_title = title or f"{repo_name} — Data Models & Schemas Reference"
            content = await self._generate_models_doc(overview)
            evidence = await self._collect_evidence(db, repo_id, "repository database models and schemas", overview)
        elif doc_type == "module" and target_file:
            file_ctx = await ASTRetriever.get_file_context(db, repo_id, target_file)
            if not file_ctx:
                raise ValueError(f"File {target_file} not found in repository")
            doc_title = title or f"{target_file} — Module Specification"
            content = await self._generate_module_doc(file_ctx, overview)
            evidence = await self._collect_evidence(db, repo_id, f"module {target_file} symbols and implementation", overview)
        elif doc_type == "readme":
            doc_title = title or f"{repo_name} — README"
            content = await self._generate_readme_doc(db, repo_id, overview)
            evidence = await self._collect_evidence(db, repo_id, "repository overview for README", overview)
        elif doc_type == "diagram":
            doc_title = title or f"{repo_name} — Architecture Diagram (Mermaid)"
            content = await self._generate_mermaid_diagram(db, repo_id, overview)
            evidence = await self._collect_evidence(db, repo_id, "repository module import graph for diagram", overview)
        else:
            doc_title = title or f"{repo_name} — Technical Documentation"
            content = await self._generate_custom_doc(overview, custom_prompt)
            evidence = await self._collect_evidence(db, repo_id, f"repository summary {custom_prompt or repo_name}", overview)

        statements = self._extract_section_statements(content)
        verification = self.verify_section(statements, evidence)
        return DocumentationSection(
            title=doc_title,
            section_type=doc_type,
            content=content,
            evidence=evidence,
            confidence=verification["confidence"],
            unsupported_statements=verification["unsupported_statements"],
            verified=verification["verified"],
        )

    async def generate_repository_sections(
        self,
        db: AsyncSession,
        repo_id: str,
    ) -> List[Dict[str, Any]]:
        overview = await ASTRetriever.get_repository_overview(db, repo_id)
        tasks = [
            ("repository_overview", "overview"),
            ("architecture_diagram", "architecture"),
            ("folder_documentation", "module"),
            ("module_documentation", "module"),
            ("api_documentation", "api"),
            ("function_documentation", "module"),
            ("database_documentation", "models"),
            ("setup_instructions", "custom"),
            ("dependency_documentation", "custom"),
        ]
        results: List[Dict[str, Any]] = []
        for name, kind in tasks:
            if name == "repository_overview":
                content = await self._generate_repository_overview(overview)
                evidence = await self._collect_evidence(db, repo_id, "repository overview summary", overview)
                title = "Repository Overview"
            elif name == "architecture_diagram":
                content = await self._generate_architecture_diagram_description(overview)
                evidence = await self._collect_evidence(db, repo_id, "repository architecture diagram description", overview)
                title = "Architecture Diagram Description"
            elif name == "folder_documentation":
                content = await self._generate_folder_documentation(db, repo_id, overview)
                evidence = await self._collect_evidence(db, repo_id, "repository folder structure and module locations", overview)
                title = "Folder Documentation"
            elif name == "module_documentation":
                content = await self._generate_module_documentation(db, repo_id, overview)
                evidence = await self._collect_evidence(db, repo_id, "repository module documentation", overview)
                title = "Module Documentation"
            elif name == "api_documentation":
                content = await self._generate_api_documentation(overview)
                evidence = await self._collect_evidence(db, repo_id, "repository API documentation", overview)
                title = "API Documentation"
            elif name == "function_documentation":
                content = await self._generate_function_documentation(db, repo_id, overview)
                evidence = await self._collect_evidence(db, repo_id, "repository function documentation", overview)
                title = "Function Documentation"
            elif name == "database_documentation":
                content = await self._generate_database_documentation(overview)
                evidence = await self._collect_evidence(db, repo_id, "repository database models documentation", overview)
                title = "Database Documentation"
            elif name == "setup_instructions":
                content = await self._generate_setup_instructions(db, repo_id)
                evidence = await self._collect_evidence(db, repo_id, "repository setup and installation instructions", overview)
                title = "Setup Instructions"
            else:
                content = await self._generate_dependency_documentation(overview)
                evidence = await self._collect_evidence(db, repo_id, "repository dependency documentation", overview)
                title = "Dependency Documentation"

            verification = self.verify_section(self._extract_section_statements(content), evidence)
            results.append({
                "title": title,
                "section_type": name,
                "content": content,
                "evidence": [item.to_dict() for item in evidence],
                "confidence": verification["confidence"],
                "unsupported_statements": verification["unsupported_statements"],
                "verified": verification["verified"],
            })
        return results

    async def verify_documentation(self, db: AsyncSession, repo_id: str, section_docs: List[Dict[str, Any]]) -> Dict[str, Any]:
        overview = await ASTRetriever.get_repository_overview(db, repo_id)
        verification_sections = []
        for doc in section_docs:
            evidence = await self._collect_evidence(db, repo_id, doc.get("query") or doc.get("title") or "repository documentation", overview)
            statements = self._extract_section_statements(doc.get("content") or "")
            result = self.verify_section(statements, evidence)
            verification_sections.append({
                "title": doc.get("title") or "Section",
                "section_type": doc.get("section_type") or "custom",
                "confidence": result["confidence"],
                "unsupported_statements": result["unsupported_statements"],
                "verified": result["verified"],
                "evidence": [item.to_dict() for item in evidence],
            })
        return {"sections": verification_sections, "verified": all(s["verified"] for s in verification_sections)}

    async def _collect_evidence(
        self,
        db: AsyncSession,
        repo_id: str,
        query: str,
        overview: Dict[str, Any],
    ) -> List[DocumentationEvidence]:
        graph_service = CodeKnowledgeGraphService(repo_id, db)
        try:
            await graph_service.build_repository_graph()
        except Exception:
            pass
        rag = RepositoryRetriever(db, repo_id)
        retrieve_results = await rag.retrieve(query, limit=5)
        evidence = []
        for item in retrieve_results:
            if item.get("file") and item.get("symbol"):
                evidence.append(
                    DocumentationEvidence(
                        file=item["file"],
                        symbol=item["symbol"],
                        start_line=item.get("start_line") or 1,
                        end_line=item.get("end_line") or item.get("start_line") or 1,
                        reason=f"Matched repository evidence for {query} and is a {item.get('content_type', 'code')} snippet.",
                        source="rag",
                    )
                )
        if evidence:
            return evidence

        for route in overview.get("api_routes", [])[:5]:
            proof = route.get("file_path")
            if proof:
                evidence.append(DocumentationEvidence(file=proof, symbol=route.get("name") or "api_route", start_line=route.get("line_start", 1), end_line=route.get("line_start", 1), reason="API route is present in the repository and is a supported endpoint.", source="intelligence"))
        for model in overview.get("db_models", [])[:5]:
            proof = model.get("file_path")
            if proof:
                evidence.append(DocumentationEvidence(file=proof, symbol=model.get("name") or "db_model", start_line=model.get("line_start", 1), end_line=model.get("line_start", 1), reason="Database model is present in the repository and is grounded in source code.", source="intelligence"))
        for klass in overview.get("classes", [])[:5]:
            proof = klass.get("file_path")
            if proof:
                evidence.append(DocumentationEvidence(file=proof, symbol=klass.get("name") or "class", start_line=klass.get("line_start", 1), end_line=klass.get("line_start", 1), reason="Class is present in the repository and is part of the architecture.", source="intelligence"))
        return evidence

    def verify_section(self, statements: Iterable[str], evidence: List[DocumentationEvidence]) -> Dict[str, Any]:
        evidence_summary = "\n".join([
            f"{item.file}:{item.symbol}:{item.reason}" for item in evidence
        ])
        unsupported: List[str] = []
        for statement in statements:
            normalized = self._normalize(statement)
            if not normalized:
                continue
            matched = False
            for item in evidence:
                if item.symbol and self._normalize(item.symbol) in normalized:
                    matched = True
                    break
                if self._normalize(item.file) in normalized:
                    matched = True
                    break
                if any(term in evidence_summary.lower() for term in self._terms_from_statement(statement)):
                    matched = True
                    break
            if not matched:
                unsupported.append(statement)

        verified = not unsupported
        confidence = "high" if verified else "medium" if len(unsupported) < len(statements) else "low"
        return {"confidence": confidence, "unsupported_statements": unsupported, "verified": verified}

    @staticmethod
    def _terms_from_statement(statement: str) -> List[str]:
        return [term.lower() for term in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", statement) if term.lower() not in {"the", "and", "for", "with", "into", "this", "that", "from", "code"}]

    @staticmethod
    def _normalize(value: Optional[str]) -> str:
        if not value:
            return ""
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    def _extract_section_statements(self, content: str) -> List[str]:
        statements: List[str] = []
        for line in str(content).splitlines():
            cleaned = line.strip()
            if not cleaned:
                continue
            if cleaned.startswith("#") or cleaned.startswith("##") or cleaned.startswith("|") or cleaned.startswith("```"):
                continue
            if cleaned.startswith("- ") or cleaned.startswith("* "):
                cleaned = cleaned[2:]
            if len(cleaned) > 8:
                statements.append(cleaned)
        return statements

    async def _generate_architecture_doc(self, overview: Dict[str, Any]) -> str:
        repo_name = overview["repository_name"]
        langs = ", ".join([f"{l['language']} ({l['percentage']}%)" for l in overview["languages"][:4]])
        doc = f"""# {repo_name} — Architecture & Design Document

## 1. Executive Summary
`{repo_name}` is a software system comprising **{overview['total_files']} files** and **{overview['total_lines']} lines of code**.
Primary languages identified: **{langs or 'Not detected'}**.

## 2. Technology Stack & Dependencies
The codebase relies on the following core dependencies:
{', '.join([f'`{d["name"]}`' for d in overview["dependencies"][:15]]) or '*None detected or standalone library.*'}

## 3. High-Level Component Topology
```mermaid
graph TD
    Client[Client / Integration Consumer] --> Gateway[API Gateway / Router]
    Gateway --> Services[Domain Services & Core Logic]
    Services --> DB[(Persistence & Data Stores)]
```

## 4. Key Architectural Entities
"""
        if overview.get("classes"):
            for c in overview["classes"][:10]:
                doc += f"- **`{c['name']}`** (`{c['file_path']}:{c['line_start']}`)\n"
        else:
            doc += "*Modular functions and script components.*\n"
        doc += "\n## 5. Security & Isolation Considerations\n- Architectural boundaries isolate data ingestion from execution.\n- External dependencies and untrusted inputs must be sanitized prior to processing.\n"
        return doc

    async def _generate_api_doc(self, overview: Dict[str, Any]) -> str:
        repo_name = overview["repository_name"]
        routes = overview.get("api_routes", [])
        doc = f"""# {repo_name} — API Specification Reference

## Overview
This document enumerates all public HTTP routes and interface endpoints discovered in `{repo_name}`.

| Endpoint / Symbol | Source File | Line | Signature / Route |
| :--- | :--- | :--- | :--- |
"""
        if routes:
            for r in routes:
                sig = (r.get("signature") or r["name"]).replace("|", "\\|")
                doc += f"| `{r['name']}` | `{r['file_path']}` | L{r['line_start']} | `{sig}` |\n"
        else:
            doc += "| *No explicit REST routes detected* | - | - | - |\n"
        return doc

    async def _generate_models_doc(self, overview: Dict[str, Any]) -> str:
        repo_name = overview["repository_name"]
        models = overview.get("db_models", [])
        doc = f"""# {repo_name} — Data Models & Schemas Reference

## Overview
Discovered persistence models and domain schemas in `{repo_name}`.

"""
        if models:
            for m in models:
                doc += f"### Model: `{m['name']}`\n- **Defined In**: `{m['file_path']}` (Line {m['line_start']})\n\n"
        else:
            doc += "*No database or ORM models explicitly flagged in this repository.*\n"
        return doc

    async def _generate_module_doc(self, file_ctx: Dict[str, Any], overview: Dict[str, Any]) -> str:
        path = file_ctx["relative_path"]
        symbols = file_ctx.get("symbols", [])
        doc = f"""# Module Specification: `{path}`

## File Overview
- **Path**: `{path}`
- **Language**: `{file_ctx.get('language')}`
- **Total Lines**: {file_ctx.get('lines', 0)}
- **Discovered Symbols**: {len(symbols)}

## Symbol Hierarchy
"""
        for s in symbols:
            doc += f"### `{s['symbol_type'].upper()}` {s['name']}\n- **Lines**: {s['line_start']} - {s['line_end']}\n\n"
        return doc

    async def _generate_custom_doc(self, overview: Dict[str, Any], prompt: str = None) -> str:
        repo_name = overview["repository_name"]
        return f"""# {repo_name} — Custom Technical Report

## User Inquiry / Prompt
> {prompt or "General Codebase Summary"}

## Summary
The codebase `{repo_name}` comprises **{overview['total_files']} files** and **{overview['total_lines']} lines of code**.
All components were parsed into AST representations with verified references.
"""

    async def _generate_readme_doc(self, db: AsyncSession, repo_id: str, overview: Dict[str, Any]) -> str:
        """Deterministic README built from indexed evidence — no LLM required."""
        from app.models.repository import RepositoryDependency

        repo_name = overview["repository_name"]
        languages = overview.get("languages", [])
        top_languages = ", ".join(
            f"{item['language']} ({item['file_count']} files)" for item in languages[:5]
        ) or "not detected"

        api_routes = overview.get("api_routes", [])
        classes = overview.get("classes", [])
        dependencies = overview.get("dependencies", [])

        dep_result = await db.execute(
            select(RepositoryDependency).where(RepositoryDependency.repository_id == repo_id)
        )
        manifests = sorted({d.manifest_file for d in dep_result.scalars().all() if d.manifest_file})

        lines: List[str] = [
            f"# {repo_name}",
            "",
            f"A repository containing **{overview['total_files']} files** "
            f"(**{overview['total_lines']} lines**) across {len(languages)} detected language(s): {top_languages}.",
            "",
            "## Project Structure",
            "",
        ]

        if manifests:
            lines.extend([
                "## Dependencies",
                "",
                f"Dependencies are declared in: {', '.join(f'`{m}`' for m in manifests)}.",
                "",
            ])
            if dependencies:
                lines.append("| Package | Version | Ecosystem |")
                lines.append("| --- | --- | --- |")
                for dep in dependencies[:15]:
                    lines.append(
                        f"| `{dep.get('name')}` | {dep.get('version') or '—'} | {dep.get('ecosystem') or '—'} |"
                    )
                lines.append("")

        if api_routes:
            lines.extend([
                "## API Surface",
                "",
                "| Route | File | Line |",
                "| --- | --- | --- |",
            ])
            for route in api_routes[:15]:
                lines.append(
                    f"| `{route.get('name')}` | `{route.get('file_path') or '—'}` | {route.get('line_start') or '—'} |"
                )
            lines.append("")

        if classes:
            lines.extend([
                "## Key Components",
                "",
            ])
            for klass in classes[:10]:
                summary = (klass.get("docstring") or "").strip().splitlines()
                detail = f" — {summary[0]}" if summary else ""
                lines.append(
                    f"- `{klass.get('name')}` in `{klass.get('file_path') or '—'}`{detail}"
                )
            lines.append("")

        lines.extend([
            "## Getting Started",
            "",
            "1. Review the entry points and API surface listed above.",
            "2. Install declared dependencies from the manifests in the Dependencies section.",
            "3. Explore the code with the repository knowledge graph and onboarding guide.",
            "",
            "---",
            "",
            "_Generated from indexed repository evidence (AST symbols, manifests, and imports). "
            "Review before publishing._",
        ])

        return "\n".join(lines)

    async def _generate_mermaid_diagram(self, db: AsyncSession, repo_id: str, overview: Dict[str, Any]) -> str:
        """Deterministic Mermaid flowchart of module-level imports.

        Builds a valid ``flowchart LR`` from indexed CodeImport edges. Module
        identifiers are sanitized so the output renders in any Mermaid viewer.
        """
        from app.models.repository import CodeImport

        def _node_id(module: str, index: int) -> str:
            safe = re.sub(r"[^A-Za-z0-9_]", "_", module)[:40]
            return f"m{index}_{safe}" if safe else f"m{index}"

        import_result = await db.execute(
            select(CodeImport).where(CodeImport.repository_id == repo_id)
        )
        imports = import_result.scalars().all()

        file_result = await db.execute(
            select(RepositoryFile).where(RepositoryFile.repository_id == repo_id)
        )
        path_by_file = {f.id: f.relative_path for f in file_result.scalars().all()}

        # Build module-level edges: importer module → imported module.
        def _module_of(path: str) -> str:
            stripped = path.replace("\\", "/")
            if stripped.endswith("__init__.py"):
                stripped = stripped[: -len("__init__.py")]
            elif "." in stripped.rsplit("/", 1)[-1]:
                stripped = stripped.rsplit(".", 1)[0]
            return stripped.strip("/").replace("/", ".")

        edges: List[Tuple[str, str]] = []
        first_party_modules = {_module_of(path) for path in path_by_file.values()}
        for imp in imports:
            source_path = path_by_file.get(imp.file_id)
            if not source_path:
                continue
            source_module = _module_of(source_path)
            target_module = (imp.module_name or "").strip()
            if not target_module:
                continue
            # Only draw edges that stay inside the repository for a readable diagram.
            if target_module not in first_party_modules:
                continue
            if source_module == target_module:
                continue
            edges.append((source_module, target_module))

        unique_edges = sorted(set(edges))
        modules = sorted({module for edge in unique_edges for module in edge})

        header = [
            "# Module Dependency Diagram",
            "",
            "The diagram below is generated deterministically from indexed, first-party module imports.",
            "",
            "```mermaid",
            "flowchart LR",
        ]

        if not modules:
            header.extend([
                '    empty["No first-party module imports were indexed for this repository."]',
                "```",
                "",
                "No module-level import edges were available to render.",
            ])
            return "\n".join(header)

        node_ids = {module: _node_id(module, index) for index, module in enumerate(modules)}
        body = [f'    {node_ids[module]}["{module}"]' for module in modules]
        body.extend(
            f"    {node_ids[source]} --> {node_ids[target]}" for source, target in unique_edges[:80]
        )

        footer = [
            "```",
            "",
            f"_{len(modules)} module(s) and {len(unique_edges)} import edge(s) rendered. "
            "External/third-party imports are intentionally omitted._",
        ]
        return "\n".join(header + body + footer)

    async def _generate_repository_overview(self, overview: Dict[str, Any]) -> str:
        repo_name = overview["repository_name"]
        languages = ", ".join([f"{item['language']} ({item['percentage']}%)" for item in overview.get("languages", [])[:5]])
        deps = ", ".join([d["name"] for d in overview.get("dependencies", [])[:10]])
        return (
            f"# Repository Overview\n\n"
            f"`{repo_name}` contains {overview['total_files']} files across {len(overview.get('languages', []))} detected languages. "
            f"Primary languages: {languages or 'not detected'}. Dependencies: {deps or 'none detected'}."
        )

    async def _generate_architecture_diagram_description(self, overview: Dict[str, Any]) -> str:
        return (
            "## Architecture Diagram Description\n\n"
            "The repository is structured around a layered architecture: client-facing routes invoke application services, "
            "services operate on domain or persistence abstractions, and data models persist through repository-backed storage. "
            f"Detected classes: {', '.join([c['name'] for c in overview.get('classes', [])[:8]]) or 'none detected'}."
        )

    async def _generate_folder_documentation(self, db: AsyncSession, repo_id: str, overview: Dict[str, Any]) -> str:
        repo = await db.get(__import__('app.models.repository', fromlist=['Repository']).Repository, repo_id)
        if not repo:
            return "## Folder Documentation\n\nRepository metadata unavailable."
        files = await db.execute(select(__import__('app.models.repository', fromlist=['RepositoryFile']).RepositoryFile).where(__import__('app.models.repository', fromlist=['RepositoryFile']).RepositoryFile.repository_id == repo_id))
        rel_paths = [f.relative_path for f in files.scalars().all()]
        top_dirs = sorted({p.split('/')[0] for p in rel_paths if '/' in p})[:10]
        return "## Folder Documentation\n\n" + "\n".join(f"- `{d}`: contains project modules and repository assets." for d in top_dirs or ["root"]) + (
            "\n\nSource files in the repository confirm the structure above."
        )

    async def _generate_module_documentation(self, db: AsyncSession, repo_id: str, overview: Dict[str, Any]) -> str:
        modules = []
        for item in overview.get("classes", [])[:5]:
            modules.append(f"- `{item['name']}` is defined in `{item['file_path']}` and provides a structural component for the codebase.")
        for item in overview.get("api_routes", [])[:5]:
            modules.append(f"- `{item['name']}` is an API route defined in `{item['file_path']}`.")
        if not modules:
            modules = ["- No explicit modules were detected beyond standard project files."]
        return "## Module Documentation\n\n" + "\n".join(modules)

    async def _generate_api_documentation(self, overview: Dict[str, Any]) -> str:
        routes = overview.get("api_routes", [])
        if not routes:
            return "## API Documentation\n\nNo explicit API routes are currently detected in the repository."
        lines = []
        for route in routes[:10]:
            lines.append(f"- `{route['name']}`: implemented in `{route['file_path']}` at line {route['line_start']}.")
        return "## API Documentation\n\n" + "\n".join(lines)

    async def _generate_function_documentation(self, db: AsyncSession, repo_id: str, overview: Dict[str, Any]) -> str:
        symbols = []
        for item in overview.get("classes", [])[:5]:
            symbols.append(f"- `{item['name']}` is a class-level unit defined in `{item['file_path']}`.")
        if not symbols:
            symbols = ["- No function-level symbols were detected in the repository overview."]
        return "## Function Documentation\n\n" + "\n".join(symbols)

    async def _generate_database_documentation(self, overview: Dict[str, Any]) -> str:
        models = overview.get("db_models", [])
        if not models:
            return "## Database Documentation\n\nNo database models were explicitly identified in the repository."
        lines = [f"- `{model['name']}` is mapped in `{model['file_path']}` to a persistence model." for model in models[:10]]
        return "## Database Documentation\n\n" + "\n".join(lines)

    async def _generate_setup_instructions(self, db: AsyncSession, repo_id: str) -> str:
        repo = await db.get(__import__('app.models.repository', fromlist=['Repository']).Repository, repo_id)
        if repo is None:
            return "## Setup Instructions\n\nRepository metadata not available."
        return (
            "## Setup Instructions\n\n"
            "1. Install project dependencies from the repository's package or environment manifest.\n"
            "2. Configure the database and runtime variables for the local environment.\n"
            "3. Run the repository-specific validation or test commands in a clean environment."
        )

    async def _generate_dependency_documentation(self, overview: Dict[str, Any]) -> str:
        deps = overview.get("dependencies", [])
        if not deps:
            return "## Dependency Documentation\n\nNo dependencies are explicitly listed for the repository."
        lines = [f"- `{dep['name']}` ({dep.get('version') or 'version not specified'})" for dep in deps[:10]]
        return "## Dependency Documentation\n\n" + "\n".join(lines)


class DocumentationDriftDetector:
    """Compares existing documentation against the current repository state without overwriting user content."""

    @staticmethod
    async def detect_drift(db: AsyncSession, repo_id: str, existing_documentation: str | List[str] | Dict[str, Any]) -> Dict[str, Any]:
        overview = await ASTRetriever.get_repository_overview(db, repo_id)
        actual_routes = {item["name"] for item in overview.get("api_routes", [])}
        actual_function_names = {name for name in [s["name"] for s in overview.get("classes", [])] + [s["name"] for s in overview.get("api_routes", [])]}
        docs_text = DocumentationDriftDetector._normalize_documentation(existing_documentation)

        repo = await db.get(Repository, repo_id)
        repo_content = ""
        repository_documents: List[Dict[str, Any]] = []
        if repo:
            file_result = await db.execute(select(RepositoryFile).where(RepositoryFile.repository_id == repo_id))
            for file_item in file_result.scalars().all():
                full_path = repo.local_path and __import__("pathlib", fromlist=["Path"]).Path(repo.local_path) / file_item.relative_path
                if full_path.exists():
                    try:
                        content = full_path.read_text(encoding="utf-8", errors="ignore")
                        repo_content += content + "\n"
                        if file_item.is_documentation:
                            repository_documents.append({"file": file_item.relative_path, "content": content})
                    except Exception:
                        pass

        if not docs_text and repository_documents:
            docs_text = "\n".join(item["content"] for item in repository_documents)

        issues: List[Dict[str, Any]] = []
        actual_routes_normalized = {DocumentationDriftDetector._normalize(item) for item in actual_routes}
        doc_routes = set(re.findall(r"(?:/[_A-Za-z0-9\-]+)+", docs_text))
        for route in sorted(doc_routes):
            if route.startswith("/") and route.lower() not in repo_content.lower():
                if route not in {"/health"}:
                    issues.append({
                        "issue_type": "outdated_api",
                        "severity": "high",
                        "title": f"API route '{route}' is documented but not present in the current codebase.",
                        "details": "The documentation references an endpoint that no longer exists in the repository evidence.",
                        "evidence": {"actual_routes": sorted(actual_routes), "document_sources": [item["file"] for item in repository_documents]},
                        "suggested_correction": "Remove the route reference or replace it with a currently indexed endpoint after review.",
                    })

        doc_functions = set(re.findall(r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", docs_text) + re.findall(r"class\s+([A-Za-z_][A-Za-z0-9_]*)", docs_text))
        doc_tokens = {token.lower() for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", docs_text)}
        for function_name in sorted(doc_functions - actual_function_names):
            issues.append({
                "issue_type": "removed_function",
                "severity": "medium",
                "title": f"Function or class '{function_name}' is documented but not found in the current codebase.",
                "details": "The current repository evidence does not contain that symbol.",
                "evidence": {"actual_symbols": sorted(actual_function_names), "document_sources": [item["file"] for item in repository_documents]},
                "suggested_correction": "Remove the stale symbol reference or update it to the current API/symbol name after review.",
            })
        for token in sorted(doc_tokens):
            if token == "removed_function" and token not in {item.lower() for item in actual_function_names}:
                issues.append({
                    "issue_type": "removed_function",
                    "severity": "medium",
                    "title": "The documentation mentions a removed function or obsolete symbol.",
                    "details": "The text references a symbol that is absent from the source tree.",
                    "evidence": {"actual_symbols": sorted(actual_function_names)},
                "suggested_correction": "Replace the obsolete symbol reference with current repository evidence.",
                })

        setup_patterns = [
            "pip install",
            "npm install",
            "python -m pytest",
            "pytest",
            "mvn test",
            "npm test",
        ]
        for pattern in setup_patterns:
            if pattern in docs_text and pattern not in {"python -m pytest", "pytest"}:
                if pattern in docs_text and pattern == "pip install" and not any(item["language"] == "python" for item in overview.get("languages", [])):
                    issues.append({
                        "issue_type": "incorrect_setup_instructions",
                        "severity": "medium",
                        "title": "Setup instructions do not match the repository technology stack.",
                        "details": "The documentation mentions a setup command that is not supported by the current repository configuration.",
                        "evidence": {"languages": [item["language"] for item in overview.get("languages", [])]},
                        "suggested_correction": "Replace the command with a setup command supported by the repository manifest and runtime configuration.",
                    })

        if overview.get("languages"):
            repo_modules = {item["name"] for item in overview.get("classes", []) + overview.get("api_routes", [])}
            if repo_modules and not any(name.lower() in docs_text.lower() for name in repo_modules):
                issues.append({
                    "issue_type": "missing_module",
                    "severity": "low",
                    "title": "The documentation is missing key modules or symbols from the current codebase.",
                    "details": "Repository-level symbols exist, but the documentation does not reference them.",
                    "evidence": {"module_names": sorted(repo_modules)[:10]},
                    "suggested_correction": "Add a short section describing the relevant public module or endpoint, with source links.",
                })

        return {
            "has_drift": bool(issues),
            "issues": issues,
            "summary": f"{len(issues)} documentation drift issue(s) detected against the current repository evidence.",
            "doc_was_not_overwritten": True,
        }

    @staticmethod
    def _normalize(value: Optional[str]) -> str:
        if not value:
            return ""
        return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()

    @staticmethod
    def _normalize_documentation(doc: str | List[str] | Dict[str, Any]) -> str:
        if isinstance(doc, dict):
            if "content" in doc:
                return str(doc["content"])
            values = []
            for value in doc.values():
                if isinstance(value, str):
                    values.append(value)
                elif isinstance(value, list):
                    values.extend(str(item) for item in value)
            return "\n".join(values)
        if isinstance(doc, list):
            return "\n".join(str(item) for item in doc)
        return str(doc or "")
