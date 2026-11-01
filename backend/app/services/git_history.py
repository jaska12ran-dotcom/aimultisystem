from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    import git
except ImportError:
    git = None

from app.models.repository import CodeSymbol, GitCommit, Repository, RepositoryFile
from app.schemas.git_history import (
    GitFileHistory,
    GitHistoryAnalysis,
    GitHistoryEvidence,
    WhyCodeResponse,
)


RECENT_WINDOW_DAYS = 90
ABANDONED_AFTER_DAYS = 365


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip("/").casefold()


class GitHistoryService:
    def __init__(self, db: AsyncSession, repository: Repository):
        self.db = db
        self.repository = repository

    async def analyze(self, limit: int = 500) -> GitHistoryAnalysis:
        commits_result = await self.db.execute(
            select(GitCommit)
            .where(GitCommit.repository_id == self.repository.id)
            .order_by(GitCommit.committed_at.desc())
            .limit(limit)
        )
        commits = commits_result.scalars().all()
        files_result = await self.db.execute(
            select(RepositoryFile).where(RepositoryFile.repository_id == self.repository.id)
        )
        files = files_result.scalars().all()
        symbols_result = await self.db.execute(
            select(CodeSymbol).where(CodeSymbol.repository_id == self.repository.id)
        )
        symbols = symbols_result.scalars().all()

        symbols_by_file: Dict[str, List[CodeSymbol]] = defaultdict(list)
        for symbol in symbols:
            symbols_by_file[symbol.file_id].append(symbol)

        commit_rows: Dict[str, List[GitCommit]] = defaultdict(list)
        for commit in commits:
            for changed_path in commit.files_changed or []:
                commit_rows[_normalize_path(str(changed_path))].append(commit)

        now = datetime.now(timezone.utc)
        recent_cutoff = now - timedelta(days=RECENT_WINDOW_DAYS)
        abandoned_cutoff = now - timedelta(days=ABANDONED_AFTER_DAYS)
        file_summaries: List[GitFileHistory] = []
        for repo_file in files:
            file_commits = commit_rows.get(_normalize_path(repo_file.relative_path), [])
            file_commits.sort(key=lambda item: self._as_utc(item.committed_at), reverse=True)
            timestamps = [self._as_utc(item.committed_at) for item in file_commits]
            insertions = sum(item.insertions or 0 for item in file_commits)
            deletions = sum(item.deletions or 0 for item in file_commits)
            recent_count = sum(timestamp >= recent_cutoff for timestamp in timestamps)
            is_critical = any(
                symbol.symbol_type in {"api_route", "db_model"}
                for symbol in symbols_by_file.get(repo_file.id, [])
            )
            evidence = [
                self._evidence(commit, "Commit lists this file as changed.")
                for commit in file_commits[:5]
            ]
            frequency_threshold = max(5, (len(commits) + 19) // 20)
            churn = insertions + deletions
            hotspot = len(file_commits) >= frequency_threshold and (
                len(file_commits) >= 5 or churn >= 250
            )
            risk = "high" if hotspot and (len(file_commits) >= 10 or churn >= 1000) else (
                "medium" if hotspot else "low"
            )
            last_modified = timestamps[0] if timestamps else None
            file_summaries.append(
                GitFileHistory(
                    file=repo_file.relative_path,
                    change_frequency=len(file_commits),
                    insertions=insertions,
                    deletions=deletions,
                    churn=churn,
                    last_modified=last_modified,
                    recent_commit_count=recent_count,
                    is_hotspot=hotspot,
                    hotspot_risk=risk,
                    abandoned_area_candidate=bool(
                        commits and (last_modified is None or last_modified < abandoned_cutoff)
                    ),
                    critical_component=is_critical,
                    recently_modified_critical=bool(is_critical and recent_count),
                    evidence=evidence,
                )
            )

        file_summaries.sort(
            key=lambda item: (-item.change_frequency, -item.churn, item.file.casefold())
        )
        branches, branches_available = self._branches()
        frequently_changed = [
            item for item in file_summaries if item.change_frequency >= 5
        ]
        high_risk = [
            item for item in file_summaries
            if item.is_hotspot and item.hotspot_risk == "high"
        ]
        abandoned = [item for item in file_summaries if item.abandoned_area_candidate]
        recent_critical = [
            item for item in file_summaries if item.recently_modified_critical
        ]
        unstable_modules = sorted(
            {
                str(Path(item.file).parent).replace("\\", "/")
                for item in file_summaries
                if item.is_hotspot
            }
        )

        if not commits:
            summary = "No indexed Git commit history is available; change patterns and abandoned areas cannot be assessed."
            scope = "No indexed commits. Branches are read from the current local checkout when available."
        elif len(commits) >= limit:
            summary = (
                f"Analyzed the {len(commits)} most recent indexed commits. "
                "Hotspots and abandoned-area candidates are limited to this history window."
            )
            scope = f"Most recent {len(commits)} indexed commits (requested limit {limit}); full history is not guaranteed."
        else:
            summary = (
                f"Analyzed {len(commits)} indexed commits. "
                "Abandoned-area labels mean no recent changes were observed in the available history, not proof of abandonment."
            )
            scope = f"All {len(commits)} commits currently indexed for this repository; ingestion may have capped the source history."

        return GitHistoryAnalysis(
            repository_id=self.repository.id,
            history_available=bool(commits),
            history_scope=scope,
            commits_analyzed=len(commits),
            branches=branches,
            branch_history_available=branches_available,
            files=file_summaries,
            frequently_changed_files=frequently_changed,
            unstable_modules=unstable_modules,
            high_risk_hotspots=high_risk,
            abandoned_area_candidates=abandoned,
            recently_modified_critical_components=recent_critical,
            summary=summary,
        )

    async def why_code_exists(self, target: str, limit: int = 10) -> WhyCodeResponse:
        normalized = _normalize_path(target)
        files_result = await self.db.execute(
            select(RepositoryFile).where(RepositoryFile.repository_id == self.repository.id)
        )
        files = files_result.scalars().all()
        target_files = [
            item for item in files
            if _normalize_path(item.relative_path) == normalized
        ]
        symbols_result = await self.db.execute(
            select(CodeSymbol).where(CodeSymbol.repository_id == self.repository.id)
        )
        symbols = symbols_result.scalars().all()
        if not target_files:
            matched_symbols = [
                symbol for symbol in symbols
                if symbol.name.casefold() == target.casefold()
                or symbol.qualified_name.casefold() == target.casefold()
            ]
            target_file_ids = {symbol.file_id for symbol in matched_symbols}
            target_files = [item for item in files if item.id in target_file_ids]

        if not target_files:
            return WhyCodeResponse(
                repository_id=self.repository.id,
                target=target,
                answer="I cannot determine why this code exists because no matching file or indexed symbol was found.",
                sufficient_history=False,
                limitation="The target could not be matched to repository evidence.",
            )

        target_paths = {_normalize_path(item.relative_path) for item in target_files}
        commits_result = await self.db.execute(
            select(GitCommit)
            .where(GitCommit.repository_id == self.repository.id)
            .order_by(GitCommit.committed_at.desc())
            .limit(500)
        )
        matching: List[Tuple[GitCommit, Set[str]]] = []
        for commit in commits_result.scalars().all():
            overlaps = target_paths & {
                _normalize_path(str(path)) for path in (commit.files_changed or [])
            }
            if overlaps:
                matching.append((commit, overlaps))
        evidence = [
            self._evidence(commit, f"Commit changed {', '.join(sorted(paths))}.")
            for commit, paths in matching[:limit]
        ]

        messages = [
            (commit.message or "").strip().splitlines()[0]
            for commit, _ in matching[:limit]
            if (commit.message or "").strip()
        ]
        informative_messages = [
            message for message in messages
            if message.casefold() not in {"update", "changes", "change", "initial commit", "misc"}
            and len(message) > 10
        ]
        sufficient = bool(matching and informative_messages)
        if sufficient:
            quoted = "; ".join(f'"{message}"' for message in informative_messages[:5])
            answer = (
                "The available commit messages describe changes to this code as: "
                f"{quoted}. These messages are the recorded historical rationale; they do not establish intent beyond what their authors wrote."
            )
            limitation = (
                "Evidence is limited to commit messages and changed-file records. "
                "Git history does not prove the original design intent, and symbol-level attribution is file-level."
            )
        else:
            answer = (
                "I cannot determine why this code exists from the available Git history. "
                "The indexed history has no matching commit with an informative rationale."
            )
            limitation = (
                "No sufficiently informative commit-message evidence was found for the target. "
                "No developer intention has been inferred."
            )
        return WhyCodeResponse(
            repository_id=self.repository.id,
            target=target,
            answer=answer,
            sufficient_history=sufficient,
            evidence=evidence,
            limitation=limitation,
        )

    def _branches(self) -> Tuple[List[str], bool]:
        if git is None:
            return [], False
        repo_path = Path(self.repository.local_path)
        try:
            repo = git.Repo(repo_path)
            return sorted((branch.name for branch in repo.branches), key=str.casefold), True
        except (git.InvalidGitRepositoryError, git.NoSuchPathError, OSError):
            return [], False

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _evidence(commit: GitCommit, relevance: str) -> GitHistoryEvidence:
        timestamp = commit.committed_at
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return GitHistoryEvidence(
            commit_hash=commit.commit_hash,
            message=commit.message,
            author=commit.author_name,
            timestamp=timestamp,
            files_changed=list(commit.files_changed or []),
            relevance=relevance,
        )
