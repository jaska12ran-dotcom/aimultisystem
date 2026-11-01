"""
SWE-bench Verified Integration Service
--------------------------------------
Enables CodeTwin to reference, search, and retrieve real-world verified bug fixes
and patches from the SWE-bench Verified benchmark dataset.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

DATASET_PROCESSED_PATH = (
    Path(__file__).resolve().parents[3]
    / "training"
    / "datasets"
    / "processed"
    / "swebench"
)
DATASET_RAW_PATH = (
    Path(__file__).resolve().parents[3]
    / "training"
    / "datasets"
    / "swebench"
    / "swebench_verified_raw.jsonl"
)


class SWEBenchInstanceSummary(BaseModel):
    instance_id: str
    repo: str
    problem_statement: str
    base_commit: str = ""
    version: str = ""
    patch: str = ""
    modified_files: List[str] = Field(default_factory=list)
    fail_to_pass: List[str] = Field(default_factory=list)
    score: float = 0.0
    match_reason: str = ""


class SWEBenchSearchResult(BaseModel):
    query: str
    total_results: int
    results: List[SWEBenchInstanceSummary]
    dataset_source: str = "SWE-bench/SWE-bench_Verified"


class SWEBenchService:
    """Service for searching and retrieving verified fixes from SWE-bench."""

    def __init__(self, data_path: Optional[Path] = None):
        self.data_path = data_path or DATASET_RAW_PATH
        self._instances: List[Dict[str, Any]] = []
        self._loaded = False

    def load_instances(self) -> int:
        """Load instances from processed or raw JSONL files if available."""
        if self._loaded:
            return len(self._instances)

        candidates = [
            self.data_path,
            DATASET_PROCESSED_PATH / "instructions" / "train.jsonl",
            DATASET_PROCESSED_PATH / "train.jsonl",
        ]

        for cand in candidates:
            if cand and cand.is_file():
                try:
                    with cand.open(encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                self._instances.append(json.loads(line))
                    self._loaded = True
                    logger.info("Loaded %d SWE-bench instances from %s", len(self._instances), cand)
                    break
                except Exception as exc:
                    logger.warning("Could not read SWE-bench data from %s: %s", cand, exc)

        return len(self._instances)

    def search_fixes(
        self,
        query: str,
        repo_filter: Optional[str] = None,
        limit: int = 5,
    ) -> SWEBenchSearchResult:
        """
        Search for relevant verified bug fixes matching a problem description or error.
        """
        self.load_instances()
        query_words = set(query.lower().split())

        scored: List[tuple[float, str, Dict[str, Any]]] = []

        for item in self._instances:
            repo = item.get("repo") or item.get("repository_id", "")
            if repo_filter and repo_filter.lower() not in repo.lower():
                continue

            problem = item.get("problem_statement") or item.get("instruction") or ""
            patch = item.get("patch") or item.get("completion") or ""
            problem_lower = problem.lower()

            matches = sum(1 for w in query_words if len(w) > 3 and w in problem_lower)
            if matches > 0:
                score = matches / max(len(query_words), 1)
                reason = f"Matched {matches} keywords in issue description"
                scored.append((score, reason, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:limit]

        results = []
        for score, reason, item in top:
            inst_id = item.get("instance_id") or item.get("example_id", "")
            repo = item.get("repo") or item.get("repository_id", "")
            problem = item.get("problem_statement") or item.get("instruction") or ""
            patch = item.get("patch") or item.get("completion") or ""
            files = item.get("modified_files") or item.get("evidence") or []

            results.append(
                SWEBenchInstanceSummary(
                    instance_id=inst_id,
                    repo=repo,
                    problem_statement=problem[:500] + ("..." if len(problem) > 500 else ""),
                    base_commit=item.get("base_commit", ""),
                    version=item.get("version", ""),
                    patch=patch,
                    modified_files=files if isinstance(files, list) else [],
                    fail_to_pass=item.get("fail_to_pass", []),
                    score=round(score, 3),
                    match_reason=reason,
                )
            )

        return SWEBenchSearchResult(
            query=query,
            total_results=len(scored),
            results=results,
        )

    def get_instance(self, instance_id: str) -> Optional[SWEBenchInstanceSummary]:
        """Retrieve a specific instance by instance_id."""
        self.load_instances()
        for item in self._instances:
            item_id = item.get("instance_id") or item.get("example_id", "")
            if item_id == instance_id or item_id == f"swebench_{instance_id}":
                patch = item.get("patch") or item.get("completion") or ""
                return SWEBenchInstanceSummary(
                    instance_id=item_id,
                    repo=item.get("repo") or item.get("repository_id", ""),
                    problem_statement=item.get("problem_statement") or item.get("instruction") or "",
                    base_commit=item.get("base_commit", ""),
                    version=item.get("version", ""),
                    patch=patch,
                    modified_files=item.get("modified_files") or item.get("evidence") or [],
                    fail_to_pass=item.get("fail_to_pass", []),
                    score=1.0,
                    match_reason="Exact instance match",
                )
        return None

