from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import CodeSymbol, Repository, RepositoryFile, RepositoryVectorChunk

_logger = logging.getLogger("codetwin.rag")


# ── Embedding back-ends ────────────────────────────────────────────────────────

class _HashEmbedder:
    """Deterministic hash-based embedder — zero-dependency fallback."""

    DIMENSION = 384
    MODEL_NAME = "deterministic-hash"

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return [t.lower() for t in re.findall(r"[A-Za-z0-9_]+", text or "") if t]

    def embed_one(self, text: str) -> List[float]:
        tokens = self._tokenize(text)
        if not tokens:
            return [0.0] * self.DIMENSION
        vector = [0.0] * self.DIMENSION
        for idx, token in enumerate(tokens):
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            value = int(digest[:12], 16) / float(0xFFFFFFFFFFFF)
            vector[idx % self.DIMENSION] += value
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return [0.0] * self.DIMENSION
        return [v / norm for v in vector]


class _SentenceTransformerEmbedder:
    """
    Sentence-transformers embedder backed by a trained model.

    Loaded lazily on first call so that the import does not block the server
    when sentence-transformers is not installed.
    """

    def __init__(self, model_path: str):
        self._model_path = model_path
        self._model = None
        self.DIMENSION: int = 384    # updated after first load
        self.MODEL_NAME: str = model_path

    def _load(self) -> None:
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer  # type: ignore
        _logger.info("Loading trained embedding model from %s", self._model_path)
        self._model = SentenceTransformer(self._model_path)
        # Infer actual dimension from the model
        probe = self._model.encode(["hello"], normalize_embeddings=True)
        self.DIMENSION = probe.shape[1]
        _logger.info(
            "Embedding model ready: dim=%d  path=%s", self.DIMENSION, self._model_path
        )

    def embed_one(self, text: str) -> List[float]:
        self._load()
        result = self._model.encode(
            [text],
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return result[0].tolist()

    def embed_batch(self, texts: List[str], batch_size: int = 128) -> List[List[float]]:
        self._load()
        result = self._model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return result.tolist()


# ── Factory ────────────────────────────────────────────────────────────────────

def _make_embedder() -> "_HashEmbedder | _SentenceTransformerEmbedder":
    """
    Pick the best available embedder in priority order:
      1. Path in env var CODETWIN_EMBEDDING_MODEL
      2. Trained model at default training output path
      3. Deterministic hash fallback (zero deps)
    """
    env_path = os.getenv("CODETWIN_EMBEDDING_MODEL", "").strip()
    if env_path and Path(env_path).exists():
        _logger.info("Using trained embedding model from CODETWIN_EMBEDDING_MODEL=%s", env_path)
        return _SentenceTransformerEmbedder(env_path)

    # Default training output location
    default_paths = [
        # Relative to the project root (works whether running from backend/ or root)
        Path(__file__).parents[4] / "training" / "output" / "embedding_model",
        Path(__file__).parents[3] / "training" / "output" / "embedding_model",
    ]
    for candidate in default_paths:
        if candidate.exists() and (candidate / "config_sentence_transformers.json").exists():
            _logger.info("Using trained embedding model at %s", candidate)
            return _SentenceTransformerEmbedder(str(candidate))

    _logger.info(
        "No trained embedding model found — using deterministic hash embedder. "
        "Train one with: python training/train_embedding.py"
    )
    return _HashEmbedder()


# Module-level singleton — created once per process
_EMBEDDER: "_HashEmbedder | _SentenceTransformerEmbedder | None" = None


def _get_embedder() -> "_HashEmbedder | _SentenceTransformerEmbedder":
    global _EMBEDDER
    if _EMBEDDER is None:
        _EMBEDDER = _make_embedder()
    return _EMBEDDER


# ── Public EmbeddingService (API-compatible with old interface) ────────────────

class EmbeddingService:
    """
    Public embedding service.

    Delegates to the trained sentence-transformers model when available,
    falls back to the deterministic hash embedder otherwise.

    The class-method interface is preserved so all existing callers
    (RepositoryIndexer, VectorSearchService, etc.) work unchanged.
    """

    DIMENSION: int = 384   # updated lazily on first call

    @classmethod
    def _embedder(cls) -> "_HashEmbedder | _SentenceTransformerEmbedder":
        e = _get_embedder()
        cls.DIMENSION = e.DIMENSION
        return e

    @classmethod
    def generate_embedding(cls, text: str) -> List[float]:
        return cls._embedder().embed_one(text)

    @classmethod
    def generate_embeddings_batch(cls, texts: List[str]) -> List[List[float]]:
        """Efficient batch embedding — uses the model's native batching when available."""
        embedder = cls._embedder()
        if isinstance(embedder, _SentenceTransformerEmbedder):
            return embedder.embed_batch(texts)
        return [embedder.embed_one(t) for t in texts]

    @classmethod
    def model_name(cls) -> str:
        return cls._embedder().MODEL_NAME

    @staticmethod
    def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
        if not left or not right:
            return 0.0
        left_norm = math.sqrt(sum(v * v for v in left))
        right_norm = math.sqrt(sum(v * v for v in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        return dot / (left_norm * right_norm)


class VectorSearchService:
    def __init__(self, db: AsyncSession, repository_id: str, embedding_service: Optional[EmbeddingService] = None):
        self.db = db
        self.repository_id = repository_id
        self.embedding_service = embedding_service or EmbeddingService

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not query or not query.strip():
            return []
        query_embedding = self.embedding_service.generate_embedding(query)
        result = await self.db.execute(
            select(RepositoryVectorChunk).where(RepositoryVectorChunk.repository_id == self.repository_id)
        )
        chunks = result.scalars().all()

        ranked: List[Tuple[float, RepositoryVectorChunk]] = []
        for chunk in chunks:
            embedding = chunk.embedding or []
            if not isinstance(embedding, list) or not embedding:
                continue
            score = self.embedding_service.cosine_similarity(query_embedding, [float(v) for v in embedding])
            ranked.append((score, chunk))

        ranked.sort(key=lambda item: item[0], reverse=True)
        matches: List[Dict[str, Any]] = []
        for score, chunk in ranked[:limit]:
            if score <= 0:
                continue
            matches.append({
                "id": chunk.id,
                "repository_id": chunk.repository_id,
                "file": chunk.file_path,
                "symbol": chunk.symbol,
                "language": chunk.language,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "content_type": chunk.content_type,
                "content": chunk.content,
                "score": round(float(score), 4),
            })
        return matches


class RepositoryIndexer:
    def __init__(self, db: AsyncSession, repository_id: str, embedding_service: Optional[EmbeddingService] = None):
        self.db = db
        self.repository_id = repository_id
        self.embedding_service = embedding_service or EmbeddingService

    async def _delete_existing(self) -> None:
        await self.db.execute(
            delete(RepositoryVectorChunk).where(RepositoryVectorChunk.repository_id == self.repository_id)
        )

    def _read_file_contents(self, repo_path: Path, relative_path: str) -> str:
        full_path = (repo_path / relative_path).resolve()
        try:
            full_path.relative_to(repo_path.resolve())
        except ValueError:
            return ""
        try:
            return full_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    def _chunk_for_symbol(self, file_path: str, language: str, symbol: CodeSymbol, content: str) -> Dict[str, Any]:
        start = max(1, symbol.start_line)
        end = max(start, symbol.end_line)
        snippet = "\n".join(content.splitlines()[start - 1:end])
        if not snippet.strip():
            snippet = symbol.signature or symbol.qualified_name or ""
        metadata = {
            "repository_id": self.repository_id,
            "file_path": file_path,
            "symbol": symbol.name,
            "language": language,
            "start_line": start,
            "end_line": end,
            "content_type": self._content_type_for_symbol(symbol.symbol_type),
            "content": snippet,
        }
        return metadata

    @staticmethod
    def _content_type_for_symbol(symbol_type: str) -> str:
        type_map = {
            "class": "class",
            "interface": "interface",
            "enum": "enum",
            "function": "function",
            "method": "method",
            "api_route": "api_definition",
            "db_model": "database_model",
            "schema_model": "schema_model",
            "variable": "variable",
            "import": "import",
        }
        return type_map.get(symbol_type, "code")

    async def index_repository(self) -> int:
        repo_result = await self.db.execute(select(Repository).where(Repository.id == self.repository_id))
        repo = repo_result.scalar_one_or_none()
        if repo is None:
            raise ValueError(f"Repository {self.repository_id} not found")

        await self._delete_existing()
        file_result = await self.db.execute(
            select(RepositoryFile).where(RepositoryFile.repository_id == self.repository_id).order_by(RepositoryFile.relative_path.asc())
        )
        files = file_result.scalars().all()

        symbol_result = await self.db.execute(
            select(CodeSymbol).where(CodeSymbol.repository_id == self.repository_id).order_by(CodeSymbol.start_line.asc())
        )
        symbols = symbol_result.scalars().all()
        by_file: Dict[str, List[CodeSymbol]] = {}
        for symbol in symbols:
            by_file.setdefault(symbol.file_id, []).append(symbol)

        repo_path = Path(repo.local_path)

        # Collect all chunks first, then embed in a single batch (faster with ST model)
        pending: List[Dict] = []   # {"content": str, "meta": dict}
        for file in files:
            normalized = file.relative_path.replace("\\", "/")
            content = self._read_file_contents(repo_path, normalized)
            if file.is_documentation or file.is_config or file.language in {"json", "yaml", "toml", "ini"}:
                if content.strip():
                    pending.append({
                            "content": content[:4000],
                            "meta": {
                                "repository_id": self.repository_id,
                                "file_path": normalized,
                                "symbol": file.file_name,
                                "language": file.language,
                                "start_line": 1,
                                "end_line": max(1, len(content.splitlines())),
                                "content_type": "documentation" if file.is_documentation else "configuration" if file.is_config else "file",
                            },
                        })

            for symbol in by_file.get(file.id, []):
                chunk = self._chunk_for_symbol(normalized, file.language, symbol, content)
                pending.append({"content": chunk["content"], "meta": chunk})

        # Batch embed all texts
        texts = [p["content"] for p in pending]
        embeddings = self.embedding_service.generate_embeddings_batch(texts) if texts else []

        chunk_records: List[RepositoryVectorChunk] = []
        for item, embedding in zip(pending, embeddings):
            m = item["meta"]
            chunk_records.append(RepositoryVectorChunk(
                repository_id=self.repository_id,
                file_path=m["file_path"],
                symbol=m.get("symbol", ""),
                language=m.get("language", "unknown"),
                start_line=m.get("start_line", 1),
                end_line=m.get("end_line", 1),
                content_type=m.get("content_type", "code"),
                content=item["content"],
                embedding=embedding,
            ))

        for chunk in chunk_records:
            self.db.add(chunk)
        await self.db.commit()
        return len(chunk_records)

    async def reindex_paths(self, relative_paths: Sequence[str]) -> int:
        """Replace retrieval chunks only for paths changed by twin reindexing.

        Callers own the surrounding transaction; this method flushes but does
        not commit, so twin records and their retrieval chunks stay consistent.
        """
        paths = sorted({path.replace("\\", "/") for path in relative_paths if path})
        if not paths:
            return 0

        await self.db.execute(
            delete(RepositoryVectorChunk).where(
                RepositoryVectorChunk.repository_id == self.repository_id,
                RepositoryVectorChunk.file_path.in_(paths),
            )
        )
        repo = await self.db.get(Repository, self.repository_id)
        if repo is None:
            raise ValueError(f"Repository {self.repository_id} not found")

        file_result = await self.db.execute(
            select(RepositoryFile).where(
                RepositoryFile.repository_id == self.repository_id,
                RepositoryFile.relative_path.in_(paths),
            )
        )
        files = file_result.scalars().all()
        if not files:
            await self.db.flush()
            return 0

        file_ids = [item.id for item in files]
        symbol_result = await self.db.execute(
            select(CodeSymbol)
            .where(CodeSymbol.repository_id == self.repository_id, CodeSymbol.file_id.in_(file_ids))
            .order_by(CodeSymbol.start_line.asc())
        )
        by_file: Dict[str, List[CodeSymbol]] = {}
        for symbol in symbol_result.scalars().all():
            by_file.setdefault(symbol.file_id, []).append(symbol)

        chunk_records: List[RepositoryVectorChunk] = []
        repo_path = Path(repo.local_path)
        for file in files:
            normalized = file.relative_path.replace("\\", "/")
            content = self._read_file_contents(repo_path, normalized)
            if file.is_documentation or file.is_config or file.language in {"json", "yaml", "toml", "ini"}:
                if content.strip():
                    chunk_records.append(RepositoryVectorChunk(
                        repository_id=self.repository_id,
                        file_path=normalized,
                        symbol=file.file_name,
                        language=file.language,
                        start_line=1,
                        end_line=max(1, len(content.splitlines())),
                        content_type="documentation" if file.is_documentation else "configuration" if file.is_config else "file",
                        content=content[:4000],
                        embedding=(self.embedding_service.generate_embeddings_batch([content[:4000]]) or [[]])[0],
                    ))
            for symbol in by_file.get(file.id, []):
                chunk = self._chunk_for_symbol(normalized, file.language, symbol, content)
                chunk_records.append(RepositoryVectorChunk(
                    repository_id=self.repository_id,
                    file_path=normalized,
                    symbol=chunk["symbol"],
                    language=chunk["language"],
                    start_line=chunk["start_line"],
                    end_line=chunk["end_line"],
                    content_type=chunk["content_type"],
                    content=chunk["content"],
                    embedding=(self.embedding_service.generate_embeddings_batch([chunk["content"]]) or [[]])[0],
                ))

        self.db.add_all(chunk_records)
        await self.db.flush()
        return len(chunk_records)


class RepositoryRetriever:
    def __init__(self, db: AsyncSession, repository_id: str):
        self.db = db
        self.repository_id = repository_id

    async def retrieve(self, question: str, limit: int = 5) -> List[Dict[str, Any]]:
        search_service = VectorSearchService(self.db, self.repository_id)
        results = await search_service.search(question, limit=limit)
        return results

    async def answer_question(self, question: str) -> Dict[str, Any]:
        results = await self.retrieve(question, limit=5)
        if not results:
            return {
                "answer": "I cannot determine the answer from the repository evidence available.",
                "evidence": [],
                "confidence": "low",
            }

        question_lower = (question or "").lower()
        question_terms = set(re.findall(r"[A-Za-z_]+", question_lower))
        question_symbols = {
            token.lower() for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", question_lower)
            if token.lower() not in {"what", "does", "do", "the", "a", "an", "how", "why", "when", "where", "which"}
        }
        scored_results = []
        for item in results:
            symbol_name = (item.get("symbol") or "").lower()
            text = ((item.get("content") or "") + " " + (item.get("file") or "")).lower()
            score = float(item.get("score", 0.0))
            if symbol_name and symbol_name in question_lower:
                score += 1.5
            if symbol_name and any(symbol in symbol_name for symbol in question_symbols):
                score += 1.2
            if question_terms and any(term in text for term in question_terms):
                score += 0.25 * len(question_terms.intersection(set(re.findall(r"[A-Za-z_]+", text))))
            scored_results.append((score, item))
        scored_results.sort(key=lambda pair: pair[0], reverse=True)
        best = scored_results[0][1]
        score = scored_results[0][0]
        evidence = []
        for _, item in scored_results[:5]:
            evidence.append({
                "file": item["file"],
                "start_line": item["start_line"],
                "end_line": item["end_line"],
                "reason": f"Matches the query and is a {item['content_type']} chunk for symbol '{item['symbol']}' in {item['file']}.",
            })

        summary = self._derive_summary(best)
        if not summary or len(summary.strip()) < 10:
            return {
                "answer": "I cannot determine the answer from the repository evidence available.",
                "evidence": evidence,
                "confidence": "low" if score < 0.2 else "medium",
            }

        if score < 0.2 and not any(term in (best.get("content") or "").lower() for term in question_terms):
            return {
                "answer": "I cannot determine the answer from the repository evidence available.",
                "evidence": evidence,
                "confidence": "low",
            }

        confidence = "high" if score >= 0.5 else "medium" if score >= 0.2 else "low"
        return {
            "answer": summary,
            "evidence": evidence,
            "confidence": confidence,
        }

    @staticmethod
    def _derive_summary(best: Dict[str, Any]) -> str:
        content = (best.get("content") or "").strip()
        if not content:
            return ""
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not lines:
            return ""
        for line in lines[:8]:
            if any(keyword in line.lower() for keyword in ["return", "def ", "class ", "@app", "import ", "router.", "const ", "func "]):
                return line
        if len(content) <= 220:
            return content
        return content[:220].rstrip() + "..."
