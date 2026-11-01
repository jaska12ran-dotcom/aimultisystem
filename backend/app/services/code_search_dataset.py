"""
CodeSearchNet Dataset Integration Service
----------------------------------------
Integrates the CodeSearchNet dataset for enhanced code search and retrieval.

The dataset contains code snippets with docstrings, which can be used to:
1. Improve code search and retrieval
2. Generate better code explanations
3. Enhance the RAG (Retrieval Augmented Generation) system
4. Provide code examples for error explanations

This service gracefully handles download failures and falls back to local data
if the full dataset cannot be downloaded.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Try to import datasets module
try:
    from datasets import load_dataset
    DATASETS_AVAILABLE = True
except ImportError:
    DATASETS_AVAILABLE = False
    logger.warning("datasets module not available. Install with: pip install datasets")


@dataclass
class CodeSnippet:
    """Represents a code snippet from the dataset."""
    language: str
    code: str
    docstring: str
    url: str = ""
    path: str = ""


class CodeSearchResult(BaseModel):
    """Result from code search."""
    snippet: CodeSnippet
    score: float = 0.0
    match_reason: str = ""


class CodeSearchResponse(BaseModel):
    """Response from code search query."""
    query: str
    results: List[CodeSearchResult]
    total_results: int
    language_filter: Optional[str] = None
    dataset_source: str = "codesearchnet"
    limitations: List[str] = Field(default_factory=lambda: [
        "Results are based on code patterns from the CodeSearchNet dataset.",
        "Similarity scores are heuristic and may not reflect actual code quality.",
        "Dataset may not cover all programming languages or frameworks.",
    ])


class CodeExampleResponse(BaseModel):
    """Response with code examples for a given concept."""
    concept: str
    examples: List[CodeSnippet]
    language: Optional[str] = None


class CodeSearchDatasetService:
    """Service for code search and retrieval using CodeSearchNet dataset."""

    def __init__(self, cache_dir: Optional[str] = None):
        """
        Initialize the service.

        Args:
            cache_dir: Directory to cache the dataset locally
        """
        self.cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".cache" / "codesearchnet"
        self._dataset = None
        self._loaded = False
        self._snippets_by_language: Dict[str, List[CodeSnippet]] = {}

    async def load_dataset(self, max_samples: int = 1000) -> bool:
        """
        Load the CodeSearchNet dataset.

        Args:
            max_samples: Maximum number of samples to load

        Returns:
            True if dataset loaded successfully, False otherwise
        """
        if self._loaded:
            return True

        if not DATASETS_AVAILABLE:
            logger.error("datasets module not available")
            return False

        try:
            logger.info(f"Loading CodeSearchNet dataset (max {max_samples} samples)...")

            # Load a small subset for demo/development purposes
            # In production, you would load the full dataset or a larger subset
            self._dataset = load_dataset(
                "sentence-transformers/codesearchnet",
                split=f"train[:{max_samples}]",
                cache_dir=str(self.cache_dir),
            )

            # Index snippets by language
            self._snippets_by_language = {}
            for example in self._dataset:
                lang = example.get("language", "unknown").lower()
                snippet = CodeSnippet(
                    language=lang,
                    code=example.get("code", ""),
                    docstring=example.get("docstring", ""),
                    url=example.get("url", ""),
                    path=example.get("path", ""),
                )
                if lang not in self._snippets_by_language:
                    self._snippets_by_language[lang] = []
                self._snippets_by_language[lang].append(snippet)

            self._loaded = True
            logger.info(f"Loaded dataset with {len(self._dataset)} examples across {len(self._snippets_by_language)} languages")
            return True

        except Exception as e:
            logger.error(f"Failed to load CodeSearchNet dataset: {e}")
            # Fall back to local sample data
            return self._load_fallback_data()

    def _load_fallback_data(self) -> bool:
        """Load fallback data when dataset download fails."""
        logger.info("Loading fallback code snippets...")

        # Sample code snippets for fallback
        fallback_snippets = [
            CodeSnippet(
                language="python",
                code="def read_file(filepath):\n    with open(filepath, 'r') as f:\n        return f.read()",
                docstring="Read the contents of a file and return as string",
            ),
            CodeSnippet(
                language="python",
                code="import json\n\ndef parse_json(data):\n    try:\n        return json.loads(data)\n    except json.JSONDecodeError:\n        return None",
                docstring="Parse JSON string safely, returning None on error",
            ),
            CodeSnippet(
                language="javascript",
                code="function fetchWithTimeout(url, timeout = 5000) {\n  return Promise.race([\n    fetch(url),\n    new Promise((_, reject) =>\n      setTimeout(() => reject(new Error('Timeout')), timeout)\n    )\n  ]);\n}",
                docstring="Fetch URL with timeout using Promise.race",
            ),
            CodeSnippet(
                language="python",
                code="class ErrorLogger:\n    def __init__(self):\n        self.errors = []\n    \n    def log_error(self, error_type, message, file_path=None):\n        self.errors.append({\n            'type': error_type,\n            'message': message,\n            'file': file_path\n        })",
                docstring="Simple error logging class",
            ),
        ]

        self._snippets_by_language = {"python": [], "javascript": []}
        for snippet in fallback_snippets:
            self._snippets_by_language[snippet.language].append(snippet)

        self._loaded = True
        logger.info(f"Loaded {len(fallback_snippets)} fallback snippets")
        return True

    async def search(
        self,
        query: str,
        language: Optional[str] = None,
        limit: int = 5,
    ) -> CodeSearchResponse:
        """
        Search for code snippets matching the query.

        Args:
            query: Search query
            language: Optional language filter
            limit: Maximum number of results

        Returns:
            CodeSearchResponse with matching snippets
        """
        if not self._loaded:
            await self.load_dataset()

        results: List[CodeSearchResult] = []

        # Simple keyword-based search (in production, use embeddings)
        query_lower = query.lower()
        query_words = set(query_lower.split())

        snippets_to_search = []
        if language:
            lang = language.lower()
            snippets_to_search = self._snippets_by_language.get(lang, [])
        else:
            for snippets in self._snippets_by_language.values():
                snippets_to_search.extend(snippets)

        for snippet in snippets_to_search:
            # Calculate relevance score
            text = f"{snippet.docstring} {snippet.code}".lower()
            text_words = set(text.split())

            # Simple overlap score
            overlap = len(query_words & text_words)
            if overlap > 0:
                # Calculate score based on overlap and docstring match
                docstring_overlap = len(query_words & set(snippet.docstring.lower().split()))
                score = (overlap * 0.3 + docstring_overlap * 0.7) / len(query_words)

                # Determine match reason
                match_reason = "keyword match"
                if docstring_overlap > 0:
                    match_reason = "docstring match"

                results.append(CodeSearchResult(
                    snippet=snippet,
                    score=score,
                    match_reason=match_reason,
                ))

        # Sort by score and limit
        results.sort(key=lambda x: x.score, reverse=True)
        results = results[:limit]

        return CodeSearchResponse(
            query=query,
            results=results,
            total_results=len(results),
            language_filter=language,
        )

    async def get_examples(
        self,
        concept: str,
        language: Optional[str] = None,
        limit: int = 3,
    ) -> CodeExampleResponse:
        """
        Get code examples for a given concept.

        Args:
            concept: Concept to find examples for
            language: Optional language filter
            limit: Maximum number of examples

        Returns:
            CodeExampleResponse with code examples
        """
        if not self._loaded:
            await self.load_dataset()

        examples: List[CodeSnippet] = []

        if language:
            lang = language.lower()
            snippets = self._snippets_by_language.get(lang, [])
        else:
            snippets = []
            for lang_snippets in self._snippets_by_language.values():
                snippets.extend(lang_snippets)

        # Simple keyword matching
        concept_lower = concept.lower()
        concept_words = set(concept_lower.split())

        for snippet in snippets:
            text = f"{snippet.docstring} {snippet.code}".lower()
            text_words = set(text.split())

            # Check for keyword overlap
            overlap = concept_words & text_words
            if overlap:
                examples.append(snippet)

        # If no exact matches, return random examples
        if not examples and snippets:
            import random
            examples = random.sample(snippets, min(limit, len(snippets)))

        return CodeExampleResponse(
            concept=concept,
            examples=examples[:limit],
            language=language,
        )

    async def get_error_fix_example(
        self,
        error_type: str,
        file_path: Optional[str] = None,
    ) -> Optional[CodeSnippet]:
        """
        Get a code example for fixing a specific error type.

        Args:
            error_type: Type of error (e.g., ImportError, SyntaxError, etc.)
            file_path: Optional file path where error occurred

        Returns:
            CodeSnippet with example fix, or None if not found
        """
        if not self._loaded:
            await self.load_dataset()

        # Map error types to relevant code patterns
        error_to_concept = {
            "ImportError": "import module",
            "ModuleNotFoundError": "import module",
            "SyntaxError": "parse json",
            "TimeoutError": "fetch with timeout",
            "PermissionError": "read file",
            "FileNotFoundError": "open file",
            "KeyError": "dictionary access",
            "ValueError": "parse json",
        }

        concept = error_to_concept.get(error_type, "error handling")

        examples = await self.get_examples(concept=concept, limit=1)
        return examples.examples[0] if examples.examples else None

    @property
    def is_loaded(self) -> bool:
        """Check if dataset is loaded."""
        return self._loaded

    @property
    def languages_available(self) -> List[str]:
        """Get list of available languages."""
        return list(self._snippets_by_language.keys())

    @property
    def total_snippets(self) -> int:
        """Get total number of snippets loaded."""
        return sum(len(snippets) for snippets in self._snippets_by_language.values())