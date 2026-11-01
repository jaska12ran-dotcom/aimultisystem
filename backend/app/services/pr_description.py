"""
PR Description Generator Service
----------------------------------
Generates a structured, accurate pull-request description from:
  - A diff or list of changed files / symbols
  - Indexed repository evidence (symbols, relationships, commits)
  - Optional user-supplied context

Output follows the conventional PR template:
  ## Summary
  ## What changed
  ## Why
  ## Risk / impact
  ## Testing done
  ## Related areas to review
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import (
    CodeSymbol,
    GitCommit,
    Repository,
    RepositoryFile,
)
from app.services.change_impact import ChangeImpactService
from intelligence.llm_client import default_llm_client
from intelligence.retriever import ASTRetriever


# ── Output schema ──────────────────────────────────────────────────────────────


class PRDescriptionResponse(BaseModel):
    repository_id: str
    title: str
    description_markdown: str
    changed_symbols: List[str] = Field(default_factory=list)
    affected_files: List[str] = Field(default_factory=list)
    risk_level: str = "medium"   # low | medium | high | critical
    suggested_reviewers_rationale: str = ""
    limitations: List[str] = Field(default_factory=list)


# ── Service ────────────────────────────────────────────────────────────────────


class PRDescriptionService:
    def __init__(self, db: AsyncSession, repository: Repository, llm_client=default_llm_client):
        self.db = db
        self.repository = repository
        self.llm = llm_client

    async def generate(
        self,
        changed_files: List[str],
        changed_symbols: Optional[List[str]] = None,
        diff: Optional[str] = None,
        user_context: Optional[str] = None,
        branch_name: Optional[str] = None,
    ) -> PRDescriptionResponse:
        changed_symbols = changed_symbols or []

        # ── 1. Gather evidence ─────────────────────────────────────────────────
        files_res = await self.db.execute(
            select(RepositoryFile).where(RepositoryFile.repository_id == self.repository.id)
        )
        all_files = {f.relative_path.replace("\\", "/"): f for f in files_res.scalars().all()}

        symbols_res = await self.db.execute(
            select(CodeSymbol).where(CodeSymbol.repository_id == self.repository.id)
        )
        all_symbols = symbols_res.scalars().all()
        file_by_id = {f.id: f for f in all_files.values()}

        # Symbols in changed files
        changed_file_ids = {
            f.id
            for path, f in all_files.items()
            if any(path.endswith(cf.replace("\\", "/")) or cf.replace("\\", "/").endswith(path) for cf in changed_files)
        }
        modified_symbols = [
            s for s in all_symbols if s.file_id in changed_file_ids
        ]
        changed_sym_names = [s.qualified_name for s in modified_symbols[:30]]

        # ── 2. Impact analysis ─────────────────────────────────────────────────
        impact_files: List[str] = []
        risk_level = "medium"
        if changed_files:
            try:
                impact = await ChangeImpactService(self.db, self.repository).analyze(
                    query=changed_files[0],
                    file_path=changed_files[0],
                    diff=diff,
                )
                impact_files = [c.file_path or "" for c in impact.affected_files][:10]
                risk_level = impact.overall_risk or "medium"
            except Exception:
                pass

        # ── 3. Recent related commits ──────────────────────────────────────────
        commits_res = await self.db.execute(
            select(GitCommit)
            .where(GitCommit.repository_id == self.repository.id)
            .order_by(GitCommit.committed_at.desc())
            .limit(100)
        )
        related_commits = [
            c for c in commits_res.scalars().all()
            if any(
                cf in (c.files_changed or []) for cf in changed_files
            )
        ][:5]

        # ── 4. Test files to review ────────────────────────────────────────────
        test_files = [
            f.relative_path
            for f in all_files.values()
            if f.is_test and any(
                cf.replace("\\", "/").split("/")[-1].replace(".py", "").replace(".ts", "") in f.relative_path
                for cf in changed_files
            )
        ][:5]

        # ── 5. Build description ───────────────────────────────────────────────
        description = await self._build_description(
            changed_files=changed_files,
            changed_symbols=changed_sym_names,
            impact_files=impact_files,
            risk_level=risk_level,
            related_commits=related_commits,
            test_files=test_files,
            user_context=user_context,
            branch_name=branch_name,
            diff=diff,
        )

        # ── 6. PR title ────────────────────────────────────────────────────────
        title = await self._suggest_title(changed_files, changed_sym_names, user_context, branch_name)

        # Reviewer rationale
        reviewer_rationale = ""
        if impact_files:
            reviewer_rationale = (
                f"Files {', '.join(impact_files[:3])} are affected by this change. "
                "Reviewers familiar with these areas should inspect the diff."
            )

        return PRDescriptionResponse(
            repository_id=self.repository.id,
            title=title,
            description_markdown=description,
            changed_symbols=changed_sym_names[:15],
            affected_files=impact_files[:10],
            risk_level=risk_level,
            suggested_reviewers_rationale=reviewer_rationale,
            limitations=[
                "PR description is generated from indexed static evidence; runtime side-effects are not captured.",
                "Impact analysis reflects the indexed call graph; dynamic/runtime-only paths may be missed.",
            ],
        )

    async def _build_description(
        self,
        changed_files: List[str],
        changed_symbols: List[str],
        impact_files: List[str],
        risk_level: str,
        related_commits: List[GitCommit],
        test_files: List[str],
        user_context: Optional[str],
        branch_name: Optional[str],
        diff: Optional[str],
    ) -> str:
        # Try LLM first
        system = (
            "You are a senior software engineer writing a pull request description. "
            "Write a concise, accurate PR description in Markdown. "
            "Use the following template sections:\n"
            "## Summary\n## What changed\n## Why\n## Risk / Impact\n## Testing done\n## Areas to review\n"
            "Base your description on the provided evidence only. Do not hallucinate features."
        )
        evidence_text = (
            f"Branch: {branch_name or 'unknown'}\n"
            f"Changed files: {', '.join(changed_files[:10])}\n"
            f"Modified symbols: {', '.join(changed_symbols[:15])}\n"
            f"Risk level: {risk_level}\n"
            f"Affected by this change: {', '.join(impact_files[:8]) or 'none detected'}\n"
            f"Related commits: {'; '.join((c.message or '').splitlines()[0][:80] for c in related_commits[:3])}\n"
            f"Test files to update: {', '.join(test_files[:5]) or 'none identified'}\n"
            + (f"User context: {user_context}" if user_context else "")
            + (f"\nDiff snippet:\n{diff[:1200]}" if diff else "")
        )
        user_prompt = f"Write the PR description for this change:\n\n{evidence_text}"

        try:
            llm_result = await self.llm.generate(system, user_prompt, max_tokens=800, temperature=0.3)
            if llm_result and len(llm_result.strip()) > 100:
                return llm_result.strip()
        except Exception:
            pass

        # Deterministic fallback
        lines = ["## Summary"]
        if user_context:
            lines.append(user_context)
        else:
            lines.append(
                f"This PR modifies {len(changed_files)} file(s)"
                + (f" on branch `{branch_name}`" if branch_name else "")
                + "."
            )

        lines += ["", "## What changed"]
        for cf in changed_files[:8]:
            lines.append(f"- `{cf}`")
        if changed_symbols:
            lines.append("")
            lines.append("Modified symbols: " + ", ".join(f"`{s}`" for s in changed_symbols[:8]))

        lines += ["", "## Risk / Impact"]
        lines.append(f"**Risk level:** {risk_level.upper()}")
        if impact_files:
            lines.append("")
            lines.append("Potentially affected files:")
            for af in impact_files[:5]:
                lines.append(f"- `{af}`")

        lines += ["", "## Testing done"]
        if test_files:
            lines.append("Relevant test files:")
            for tf in test_files:
                lines.append(f"- `{tf}`")
        else:
            lines.append("- No matching test files automatically identified; manual testing required.")

        lines += ["", "## Areas to review"]
        for af in impact_files[:5]:
            lines.append(f"- `{af}`")
        if not impact_files:
            lines.append("- Review all changed files listed above.")

        return "\n".join(lines)

    async def _suggest_title(
        self,
        changed_files: List[str],
        changed_symbols: List[str],
        user_context: Optional[str],
        branch_name: Optional[str],
    ) -> str:
        if branch_name:
            # Convert branch convention to readable title
            clean = (
                branch_name.replace("-", " ").replace("_", " ")
                .replace("/", " — ")
                .strip()
            )
            if len(clean) > 8:
                return clean.capitalize()

        if user_context:
            first_line = user_context.splitlines()[0][:70].strip()
            if first_line:
                return first_line

        if changed_files:
            basename = changed_files[0].replace("\\", "/").split("/")[-1]
            return f"Update {basename}"

        return "Codebase changes"
