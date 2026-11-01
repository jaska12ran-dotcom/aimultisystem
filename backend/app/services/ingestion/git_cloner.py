import os
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

try:
    import git
except ImportError:
    git = None

class GitCloneError(Exception):
    pass

def clone_git_repository(
    repo_url: str,
    target_dir: str | Path,
    branch: Optional[str] = None,
    depth: int = 50,
) -> Dict[str, Any]:
    """
    Clones a remote Git repository into target_dir with shallow depth for speed and safety.
    """
    target_path = Path(target_dir).resolve()
    if target_path.exists():
        shutil.rmtree(target_path, ignore_errors=True)
    os.makedirs(target_path, exist_ok=True)

    if not git:
        raise GitCloneError("GitPython is not installed or available.")

    clone_kwargs: Dict[str, Any] = {"depth": depth}
    if branch:
        clone_kwargs["branch"] = branch

    try:
        repo = git.Repo.clone_from(repo_url, target_path, **clone_kwargs)
        default_branch = repo.active_branch.name if not repo.head.is_detached else "main"
        
        return {
            "local_path": str(target_path),
            "default_branch": default_branch,
            "success": True,
        }
    except Exception as e:
        raise GitCloneError(f"Failed to clone repository '{repo_url}': {str(e)}")

def extract_git_commits(repo_dir: str | Path, max_commits: int = 50) -> List[Dict[str, Any]]:
    """
    Extracts commit history, author, dates, and file changes.
    """
    repo_path = Path(repo_dir)
    commits_data: List[Dict[str, Any]] = []

    if not git:
        return commits_data

    try:
        repo = git.Repo(repo_path)
        for commit in list(repo.iter_commits(max_count=max_commits)):
            # Stats calculation
            stats = commit.stats
            files_changed = list(stats.files.keys()) if stats else []
            insertions = stats.total.get("insertions", 0) if stats else 0
            deletions = stats.total.get("deletions", 0) if stats else 0

            commits_data.append({
                "commit_hash": commit.hexsha,
                "author_name": commit.author.name or "Unknown",
                "author_email": commit.author.email or "",
                "committed_at": datetime.fromtimestamp(commit.committed_date),
                "message": commit.message.strip(),
                "files_changed": files_changed,
                "insertions": insertions,
                "deletions": deletions,
            })
    except Exception:
        # If directory is not a git repo or has no commits, gracefully return empty list
        pass

    return commits_data
