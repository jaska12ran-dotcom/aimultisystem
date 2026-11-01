"""
Sensitive Data Flow Analyzer
-------------------------------
Performs a lightweight, static taint-style analysis over indexed repository data.
Identifies where sensitive data (passwords, PII, tokens, secrets) originates and
whether it flows into risky sinks (logs, HTTP responses, files, databases).

Strategy:
  1. Source detection — find symbols/files that handle sensitive inputs
     (login, password, token, credit_card, ssn, email, secret, api_key, etc.)
  2. Sink detection — find logging calls, HTTP response builders, file writes
  3. Path tracing — use indexed CodeRelationship edges to trace source → sink paths
  4. Risk scoring — path length × sink severity × source sensitivity

No code is executed; all analysis is over indexed AST data.
"""
from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import (
    CodeImport,
    CodeRelationship,
    CodeSymbol,
    Repository,
    RepositoryFile,
)


# ── Constants ─────────────────────────────────────────────────────────────────

# Terms that suggest a symbol handles sensitive data
SENSITIVE_SOURCES: Set[str] = {
    "password", "passwd", "pwd", "secret", "token", "api_key", "apikey",
    "auth", "credential", "credit_card", "card_number", "cvv", "ssn",
    "social_security", "dob", "date_of_birth", "email", "phone",
    "address", "ip_address", "location", "pii", "private_key",
    "access_token", "refresh_token", "session_id", "cookie",
}

# Terms that suggest a symbol is a risky sink
SENSITIVE_SINKS: Set[str] = {
    "log", "logger", "print", "debug", "info", "warning", "error",
    "response", "jsonify", "return_json", "serialize",
    "write", "save", "upload", "send", "emit", "publish",
    "insert", "update", "execute", "query",
    "render", "template",
}

# Severity mapping for sink types
SINK_SEVERITY: Dict[str, str] = {
    "log": "high",
    "logger": "high",
    "print": "high",
    "debug": "medium",
    "response": "high",
    "jsonify": "high",
    "serialize": "medium",
    "write": "medium",
    "save": "medium",
    "upload": "high",
    "send": "high",
    "emit": "medium",
    "insert": "medium",
    "update": "low",
    "execute": "medium",
    "render": "medium",
    "template": "low",
}


def _term_in(name: str, terms: Set[str]) -> bool:
    lower = name.lower()
    return any(t in lower for t in terms)


def _is_source(sym: CodeSymbol) -> bool:
    return (
        _term_in(sym.name, SENSITIVE_SOURCES)
        or _term_in(sym.qualified_name, SENSITIVE_SOURCES)
        or (sym.docstring and _term_in(sym.docstring, SENSITIVE_SOURCES))
        or any(
            _term_in(str(p.get("name", "")), SENSITIVE_SOURCES)
            for p in (sym.parameters or [])
            if isinstance(p, dict)
        )
    )


def _is_sink(sym: CodeSymbol) -> bool:
    return _term_in(sym.name, SENSITIVE_SINKS) or _term_in(sym.qualified_name, SENSITIVE_SINKS)


# ── Output schema ─────────────────────────────────────────────────────────────


class DataFlowPath(BaseModel):
    source_symbol: str
    source_file: str
    sink_symbol: str
    sink_file: str
    path_length: int
    severity: str            # critical | high | medium | low
    risk_description: str
    path_symbols: List[str] = Field(default_factory=list)


class SensitiveDataFlowResponse(BaseModel):
    repository_id: str
    source_count: int
    sink_count: int
    flow_paths: List[DataFlowPath] = Field(default_factory=list)
    unprotected_sources: List[Dict[str, Any]] = Field(default_factory=list)
    summary: str
    limitations: List[str] = Field(default_factory=list)


# ── Service ────────────────────────────────────────────────────────────────────


class SensitiveDataFlowService:
    """Lightweight taint-style sensitive data flow analysis over indexed data."""

    MAX_PATH_DEPTH = 5  # BFS depth limit to keep analysis tractable

    def __init__(self, db: AsyncSession, repository: Repository):
        self.db = db
        self.repository = repository

    async def analyze(self) -> SensitiveDataFlowResponse:
        # ── Load data ─────────────────────────────────────────────────────────
        symbols_res = await self.db.execute(
            select(CodeSymbol).where(CodeSymbol.repository_id == self.repository.id)
        )
        symbols = symbols_res.scalars().all()
        sym_by_id: Dict[str, CodeSymbol] = {s.id: s for s in symbols}

        files_res = await self.db.execute(
            select(RepositoryFile).where(RepositoryFile.repository_id == self.repository.id)
        )
        files = {f.id: f for f in files_res.scalars().all()}

        rels_res = await self.db.execute(
            select(CodeRelationship).where(CodeRelationship.repository_id == self.repository.id)
        )
        relationships = rels_res.scalars().all()

        # Build adjacency list: source_id → list of target_ids
        forward: Dict[str, List[str]] = defaultdict(list)
        for rel in relationships:
            if rel.source_symbol_id and rel.target_symbol_id:
                forward[rel.source_symbol_id].append(rel.target_symbol_id)

        # ── Classify sources and sinks ────────────────────────────────────────
        sources = [s for s in symbols if _is_source(s)]
        sinks = {s.id: s for s in symbols if _is_sink(s)}
        sink_ids = set(sinks.keys())

        # ── BFS from each source towards sinks ───────────────────────────────
        flow_paths: List[DataFlowPath] = []
        seen_paths: Set[Tuple[str, str]] = set()

        for source in sources:
            if not files.get(source.file_id):
                continue
            # BFS
            queue: deque[Tuple[str, List[str]]] = deque([(source.id, [source.id])])
            visited: Set[str] = {source.id}

            while queue:
                current_id, path = queue.popleft()

                if len(path) > self.MAX_PATH_DEPTH:
                    break

                if current_id in sink_ids and current_id != source.id:
                    sink_sym = sinks[current_id]
                    key = (source.id, current_id)
                    if key not in seen_paths:
                        seen_paths.add(key)
                        sink_file = files.get(sink_sym.file_id)
                        source_file = files.get(source.file_id)
                        sink_type = next(
                            (k for k in SINK_SEVERITY if k in sink_sym.name.lower()), "unknown"
                        )
                        severity_rank = SINK_SEVERITY.get(sink_type, "medium")
                        # Downgrade if path is very long
                        if len(path) > 3 and severity_rank == "high":
                            severity_rank = "medium"

                        path_syms = [
                            sym_by_id[sid].qualified_name
                            for sid in path
                            if sid in sym_by_id
                        ]
                        flow_paths.append(
                            DataFlowPath(
                                source_symbol=source.qualified_name,
                                source_file=source_file.relative_path if source_file else "",
                                sink_symbol=sink_sym.qualified_name,
                                sink_file=sink_file.relative_path if sink_file else "",
                                path_length=len(path),
                                severity=severity_rank,
                                risk_description=(
                                    f"Sensitive data from `{source.name}` "
                                    f"flows {len(path) - 1} step(s) to `{sink_sym.name}` "
                                    f"({sink_type} sink)."
                                ),
                                path_symbols=path_syms,
                            )
                        )

                for next_id in forward.get(current_id, []):
                    if next_id not in visited:
                        visited.add(next_id)
                        queue.append((next_id, path + [next_id]))

        # ── Unprotected sources (no validation / sanitizer nearby) ────────────
        unprotected: List[Dict[str, Any]] = []
        sanitizer_terms = {"sanitize", "validate", "escape", "encode", "hash", "encrypt", "mask"}

        for source in sources[:30]:
            # Check if any symbol in the same file looks like a sanitizer
            file_syms = [s for s in symbols if s.file_id == source.file_id]
            has_sanitizer = any(
                _term_in(s.name, sanitizer_terms) for s in file_syms
            )
            f = files.get(source.file_id)
            if f and not has_sanitizer:
                unprotected.append({
                    "symbol": source.qualified_name,
                    "file": f.relative_path,
                    "line": source.start_line,
                    "reason": (
                        f"`{source.name}` handles sensitive data but no sanitizer/validator "
                        "was detected in the same file."
                    ),
                })

        # ── Sort by severity ──────────────────────────────────────────────────
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        flow_paths.sort(key=lambda p: (sev_order.get(p.severity, 4), p.path_length))

        high_count = sum(1 for p in flow_paths if p.severity in {"critical", "high"})
        summary = (
            f"Found {len(flow_paths)} sensitive data flow path(s) from {len(sources)} source(s) "
            f"to {len(sinks)} sink(s). {high_count} high/critical severity path(s) detected."
            if flow_paths
            else (
                f"No sensitive data flows detected between {len(sources)} source(s) and "
                f"{len(sinks)} sink(s) in the indexed relationship graph."
            )
        )

        return SensitiveDataFlowResponse(
            repository_id=self.repository.id,
            source_count=len(sources),
            sink_count=len(sinks),
            flow_paths=flow_paths[:50],
            unprotected_sources=unprotected[:20],
            summary=summary,
            limitations=[
                "Analysis is based on indexed static relationship edges; runtime data flows are not tracked.",
                "Taint propagation is keyword-heuristic based; it may miss obfuscated variable names.",
                "External library sinks (e.g. third-party logging libraries) are only detected if indexed.",
                "Encryption/masking applied inside the same call chain may not be reflected if not indexed.",
            ],
        )
