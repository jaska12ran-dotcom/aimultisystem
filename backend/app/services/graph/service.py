from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import unquote

import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import (
    CodeImport,
    CodeRelationship,
    CodeSymbol,
    GitCommit,
    Repository,
    RepositoryDependency,
    RepositoryFile,
)


@dataclass
class GraphNode:
    id: str
    name: str
    node_type: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.node_type,
            "metadata": self.metadata,
        }


@dataclass
class GraphRelationship:
    source: str
    target: str
    relationship_type: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "type": self.relationship_type,
            "metadata": self.metadata,
        }


class GraphStore(ABC):
    @abstractmethod
    def add_node(self, node_id: str, node_type: str, name: str, metadata: Optional[Dict[str, Any]] = None) -> GraphNode:
        raise NotImplementedError

    @abstractmethod
    def add_relationship(self, source: str, target: str, relationship_type: str, metadata: Optional[Dict[str, Any]] = None) -> GraphRelationship:
        raise NotImplementedError

    @abstractmethod
    def query_relationships(self, source: Optional[str] = None, target: Optional[str] = None, relationship_type: Optional[str] = None) -> List[GraphRelationship]:
        raise NotImplementedError

    @abstractmethod
    def find_callers(self, node_id: str) -> List[GraphRelationship]:
        raise NotImplementedError

    @abstractmethod
    def find_dependencies(self, node_id: str) -> List[GraphRelationship]:
        raise NotImplementedError

    @abstractmethod
    def find_dependents(self, node_id: str) -> List[GraphRelationship]:
        raise NotImplementedError

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        raise NotImplementedError


class NetworkXGraphStore(GraphStore):
    def __init__(self):
        self.graph = nx.DiGraph()

    def add_node(self, node_id: str, node_type: str, name: str, metadata: Optional[Dict[str, Any]] = None) -> GraphNode:
        metadata = metadata or {}
        self.graph.add_node(node_id, name=name, type=node_type, metadata=metadata)
        return GraphNode(id=node_id, name=name, node_type=node_type, metadata=metadata)

    def add_relationship(self, source: str, target: str, relationship_type: str, metadata: Optional[Dict[str, Any]] = None) -> GraphRelationship:
        metadata = metadata or {}
        self.graph.add_edge(source, target, type=relationship_type, metadata=metadata)
        return GraphRelationship(source=source, target=target, relationship_type=relationship_type, metadata=metadata)

    def query_relationships(self, source: Optional[str] = None, target: Optional[str] = None, relationship_type: Optional[str] = None) -> List[GraphRelationship]:
        rels: List[GraphRelationship] = []
        for src, dst, data in self.graph.edges(data=True):
            if source is not None and src != source:
                continue
            if target is not None and dst != target:
                continue
            if relationship_type is not None and data.get("type") != relationship_type:
                continue
            rels.append(
                GraphRelationship(
                    source=src,
                    target=dst,
                    relationship_type=data.get("type"),
                    metadata=data.get("metadata", {}),
                )
            )
        return rels

    def find_callers(self, node_id: str) -> List[GraphRelationship]:
        return [
            GraphRelationship(source=src, target=node_id, relationship_type=data.get("type"), metadata=data.get("metadata", {}))
            for src, _, data in self.graph.in_edges(node_id, data=True)
        ]

    def find_dependencies(self, node_id: str) -> List[GraphRelationship]:
        return [
            GraphRelationship(source=node_id, target=dst, relationship_type=data.get("type"), metadata=data.get("metadata", {}))
            for _, dst, data in self.graph.out_edges(node_id, data=True)
        ]

    def find_dependents(self, node_id: str) -> List[GraphRelationship]:
        return [
            GraphRelationship(source=src, target=node_id, relationship_type=data.get("type"), metadata=data.get("metadata", {}))
            for src, _, data in self.graph.in_edges(node_id, data=True)
        ]

    def to_dict(self) -> Dict[str, Any]:
        nodes = []
        for node_id, attrs in self.graph.nodes(data=True):
            nodes.append({
                "id": node_id,
                "name": attrs.get("name"),
                "type": attrs.get("type"),
                "metadata": attrs.get("metadata", {}),
            })
        edges = []
        for src, dst, attrs in self.graph.edges(data=True):
            edges.append({
                "source": src,
                "target": dst,
                "type": attrs.get("type"),
                "metadata": attrs.get("metadata", {}),
            })
        return {"nodes": nodes, "relationships": edges}


class CodeKnowledgeGraphService:
    def __init__(self, repository_id: str, db: AsyncSession, store: Optional[GraphStore] = None):
        self.repository_id = repository_id
        self.db = db
        self.store = store or NetworkXGraphStore()

    def add_node(self, node_id: str, node_type: str, name: str, metadata: Optional[Dict[str, Any]] = None) -> GraphNode:
        return self.store.add_node(node_id, node_type, name, metadata)

    def add_relationship(self, source: str, target: str, relationship_type: str, metadata: Optional[Dict[str, Any]] = None) -> GraphRelationship:
        return self.store.add_relationship(source, target, relationship_type, metadata)

    def query_relationships(self, source: Optional[str] = None, target: Optional[str] = None, relationship_type: Optional[str] = None) -> List[GraphRelationship]:
        return self.store.query_relationships(source=source, target=target, relationship_type=relationship_type)

    def find_callers(self, node_id: str) -> List[GraphRelationship]:
        return self.store.find_callers(node_id)

    def find_dependencies(self, node_id: str) -> List[GraphRelationship]:
        return self.store.find_dependencies(node_id)

    def find_dependents(self, node_id: str) -> List[GraphRelationship]:
        return self.store.find_dependents(node_id)

    def trace_api_to_code(self, api_name: str) -> List[Dict[str, Any]]:
        api_name = unquote(api_name)
        matches = []
        for _, data in self.store.graph.nodes(data=True):
            node_name = data.get("name")
            if node_name and node_name.lower() == api_name.lower() and data.get("type") in {"api", "api_route"}:
                node_id = next((nid for nid, attrs in self.store.graph.nodes(data=True) if attrs.get("name") == node_name and attrs.get("type") in {"api", "api_route"}), None)
                if node_id is not None:
                    for rel in self.store.find_dependencies(node_id):
                        matches.append({
                            "api": api_name,
                            "relationship": rel.relationship_type,
                            "target": rel.target,
                        })
        return matches

    async def build_repository_graph(self) -> Dict[str, Any]:
        repo_result = await self.db.execute(select(Repository).where(Repository.id == self.repository_id))
        repo = repo_result.scalar_one_or_none()
        if repo is None:
            raise ValueError(f"Repository {self.repository_id} not found")

        self.add_node(f"repository:{repo.id}", "repository", repo.name, {"repository_id": repo.id})

        file_result = await self.db.execute(select(RepositoryFile).where(RepositoryFile.repository_id == self.repository_id))
        files = file_result.scalars().all()
        for file in files:
            file_id = f"file:{file.id}"
            self.add_node(file_id, "file", file.relative_path, {
                "path": file.relative_path,
                "language": file.language,
                "sha256": file.sha256_hash,
            })
            self.add_relationship(f"repository:{repo.id}", file_id, "contains", {"path": file.relative_path})

        symbol_result = await self.db.execute(select(CodeSymbol).where(CodeSymbol.repository_id == self.repository_id))
        symbols = symbol_result.scalars().all()
        for symbol in symbols:
            symbol_id = f"symbol:{symbol.id}"
            file_id = f"file:{symbol.file_id}"
            node_type = symbol.symbol_type if symbol.symbol_type else "symbol"
            if node_type == "api_route":
                node_type = "api"
            self.add_node(symbol_id, node_type, symbol.name, {
                "qualified_name": symbol.qualified_name,
                "file_id": symbol.file_id,
                "start_line": symbol.start_line,
                "end_line": symbol.end_line,
            })
            self.add_relationship(file_id, symbol_id, "contains", {"symbol_type": symbol.symbol_type})

        rel_result = await self.db.execute(select(CodeRelationship).where(CodeRelationship.repository_id == self.repository_id))
        for rel in rel_result.scalars().all():
            if rel.source_symbol_id:
                src_id = f"symbol:{rel.source_symbol_id}"
                if rel.target_symbol_id:
                    tgt_id = f"symbol:{rel.target_symbol_id}"
                    self.add_relationship(src_id, tgt_id, rel.relationship_type or "references", {"evidence_line": rel.evidence_line})

        import_result = await self.db.execute(select(CodeImport).where(CodeImport.repository_id == self.repository_id))
        for imp in import_result.scalars().all():
            src_id = f"file:{imp.file_id}"
            module_name = imp.module_name.strip()
            if not module_name:
                continue
            import_node_id = f"module:{module_name}"
            self.add_node(import_node_id, "module", module_name, {"module_name": module_name})
            self.add_relationship(src_id, import_node_id, "imports", {"line_number": imp.line_number})

        dep_result = await self.db.execute(select(RepositoryDependency).where(RepositoryDependency.repository_id == self.repository_id))
        for dep in dep_result.scalars().all():
            dep_node_id = f"package:{dep.package_name}"
            self.add_node(dep_node_id, "package", dep.package_name, {"ecosystem": dep.ecosystem, "version": dep.version_spec})
            self.add_relationship(f"repository:{repo.id}", dep_node_id, "depends_on", {"ecosystem": dep.ecosystem})

        commit_result = await self.db.execute(select(GitCommit).where(GitCommit.repository_id == self.repository_id))
        for commit in commit_result.scalars().all():
            commit_id = f"commit:{commit.id}"
            self.add_node(commit_id, "git_commit", commit.commit_hash, {"message": commit.message})
            for changed in commit.files_changed or []:
                file_node = next((nid for nid, data in self.store.graph.nodes(data=True) if data.get("name") == changed and data.get("type") == "file"), None)
                if file_node:
                    self.add_relationship(commit_id, file_node, "modifies", {"message": commit.message})

        return self.store.to_dict()

    def find_symbol_relationships(self, symbol_name: str) -> List[Dict[str, Any]]:
        q = unquote(symbol_name)
        matched = [
            {"id": node_id, "name": attrs.get("name"), "type": attrs.get("type")}
            for node_id, attrs in self.store.graph.nodes(data=True)
            if attrs.get("name") and attrs.get("name").lower() == q.lower()
        ]
        if not matched:
            return []
        results: List[Dict[str, Any]] = []
        for node_id, *_ in [(item["id"], item["name"], item["type"]) for item in matched]:
            for rel in self.store.query_relationships(source=node_id):
                results.append({
                    "source": rel.source,
                    "target": rel.target,
                    "type": rel.relationship_type,
                    "metadata": rel.metadata,
                })
            for rel in self.store.query_relationships(target=node_id):
                results.append({
                    "source": rel.source,
                    "target": rel.target,
                    "type": rel.relationship_type,
                    "metadata": rel.metadata,
                })
        return results

    def find_symbol_callers(self, symbol_name: str) -> List[Dict[str, Any]]:
        q = unquote(symbol_name)
        node_id = next(
            (node_id for node_id, attrs in self.store.graph.nodes(data=True) if attrs.get("name") and attrs.get("name").lower() == q.lower()),
            None,
        )
        if node_id is None:
            return []
        return [
            {"source": rel.source, "target": rel.target, "type": rel.relationship_type, "metadata": rel.metadata}
            for rel in self.store.find_callers(node_id)
        ]

    def find_symbol_dependents(self, symbol_name: str) -> List[Dict[str, Any]]:
        q = unquote(symbol_name)
        node_id = next(
            (node_id for node_id, attrs in self.store.graph.nodes(data=True) if attrs.get("name") and attrs.get("name").lower() == q.lower()),
            None,
        )
        if node_id is None:
            return []
        return [
            {"source": rel.source, "target": rel.target, "type": rel.relationship_type, "metadata": rel.metadata}
            for rel in self.store.find_dependents(node_id)
        ]

    def find_symbol_dependencies(self, symbol_name: str) -> List[Dict[str, Any]]:
        q = unquote(symbol_name)
        node_id = next(
            (node_id for node_id, attrs in self.store.graph.nodes(data=True) if attrs.get("name") and attrs.get("name").lower() == q.lower()),
            None,
        )
        if node_id is None:
            return []
        return [
            {"source": rel.source, "target": rel.target, "type": rel.relationship_type, "metadata": rel.metadata}
            for rel in self.store.find_dependencies(node_id)
        ]
