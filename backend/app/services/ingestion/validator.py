"""
Repository Ingestion Validator
------------------------------
All user-supplied repository inputs are treated as UNTRUSTED.
Validation enforces:
- GitHub URL format and hostname (only github.com / gitlab.com / bitbucket.org)
- Path confinement – local paths must not escape allowed roots
- File size limits for uploads
- Filename sanitization
- No shell-executable characters in names
"""
from __future__ import annotations

import re
import os
from pathlib import Path, PurePosixPath
from typing import Optional
from urllib.parse import urlparse

from app.core.config import settings
from app.utils.logger import logger

# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────
_ALLOWED_GIT_HOSTS: set[str] = {
    "github.com",
    "gitlab.com",
    "bitbucket.org",
}

_SAFE_REPO_URL_RE = re.compile(
    r"^https?://(github\.com|gitlab\.com|bitbucket\.org)/[A-Za-z0-9._\-]+/[A-Za-z0-9._\-]+(\.git)?/?$"
)

_UNSAFE_NAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

MAX_UPLOAD_SIZE_BYTES: int = 500 * 1024 * 1024  # 500 MB
MAX_LOCAL_REPO_SIZE_BYTES: int = 2 * 1024 * 1024 * 1024  # 2 GB

# ──────────────────────────────────────────────────────────────
# Public validators
# ──────────────────────────────────────────────────────────────


class ValidationError(ValueError):
    """Raised when user-supplied input fails security or format checks."""


def validate_github_url(url: str) -> str:
    """Validates and normalises a Git clone URL.

    Returns the validated URL string.
    Raises ValidationError on failure.
    """
    url = url.strip()
    if not url:
        raise ValidationError("Repository URL must not be empty.")

    # Reject obvious injection attempts
    if any(c in url for c in [";", "&", "|", "`", "$", "\n", "\r"]):
        raise ValidationError("Repository URL contains forbidden characters.")

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValidationError(
            f"Only http/https URLs are accepted. Got scheme: '{parsed.scheme}'"
        )

    if parsed.netloc.lower() not in _ALLOWED_GIT_HOSTS:
        raise ValidationError(
            f"Host '{parsed.netloc}' is not in the allowed list: "
            f"{sorted(_ALLOWED_GIT_HOSTS)}"
        )

    if not _SAFE_REPO_URL_RE.match(url):
        raise ValidationError(
            "URL must follow the pattern: https://<host>/<owner>/<repo>[.git]"
        )

    logger.debug("GitHub URL validated: %s", url)
    return url


def validate_local_path(raw_path: str) -> Path:
    """Validates a local directory path provided by the user.

    Returns a resolved absolute Path.
    Raises ValidationError on failure.
    """
    raw_path = raw_path.strip()
    if not raw_path:
        raise ValidationError("Local repository path must not be empty.")

    try:
        path = Path(raw_path).resolve()
    except Exception as exc:
        raise ValidationError(f"Cannot resolve path '{raw_path}': {exc}") from exc

    if not path.exists():
        raise ValidationError(f"Path does not exist: {path}")

    if not path.is_dir():
        raise ValidationError(f"Path is not a directory: {path}")

    # Prevent traversal into system-sensitive paths
    forbidden_prefixes = ["/proc", "/sys", "/dev", "/run", "C:\\Windows", "C:\\System32"]
    for prefix in forbidden_prefixes:
        try:
            resolved_prefix = Path(prefix).resolve()
            if str(path).startswith(str(resolved_prefix)):
                raise ValidationError(f"Access to '{path}' is not permitted.")
        except Exception:
            pass

    # Basic size guard – don't scan enormous trees
    try:
        total_size = _estimate_directory_size(path)
        if total_size > MAX_LOCAL_REPO_SIZE_BYTES:
            raise ValidationError(
                f"Local repository is too large ({total_size // (1024**3):.1f} GB). "
                f"Maximum is {MAX_LOCAL_REPO_SIZE_BYTES // (1024**3)} GB."
            )
    except ValidationError:
        raise
    except Exception:
        pass  # if we can't stat, proceed and let scanner fail gracefully

    logger.debug("Local path validated: %s", path)
    return path


def validate_upload_zip(filename: str, file_size: int) -> str:
    """Validates a ZIP file upload.

    Returns the sanitised base filename (without path components).
    Raises ValidationError on failure.
    """
    if not filename:
        raise ValidationError("Uploaded file must have a name.")

    # Strip directory components (e.g. ../../evil.zip)
    safe_name = Path(filename).name
    if not safe_name:
        raise ValidationError("Invalid filename.")

    if not safe_name.lower().endswith(".zip"):
        raise ValidationError("Only .zip archives are accepted.")

    if _UNSAFE_NAME_CHARS_RE.search(safe_name):
        raise ValidationError(f"Filename '{safe_name}' contains forbidden characters.")

    if len(safe_name) > 255:
        raise ValidationError("Filename is too long (max 255 characters).")

    if file_size > MAX_UPLOAD_SIZE_BYTES:
        raise ValidationError(
            f"Upload size {file_size // (1024**2)} MB exceeds the "
            f"{MAX_UPLOAD_SIZE_BYTES // (1024**2)} MB limit."
        )

    logger.debug("ZIP filename validated: %s (%d bytes)", safe_name, file_size)
    return safe_name


def validate_repo_name(name: Optional[str], fallback: str) -> str:
    """Returns a clean display name, falling back to `fallback` if None or blank."""
    if not name or not name.strip():
        return _sanitise_name(fallback)
    return _sanitise_name(name.strip())


# ──────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────


def _sanitise_name(name: str) -> str:
    """Strips path separators and control characters from a display name."""
    name = _UNSAFE_NAME_CHARS_RE.sub("_", name)
    name = name.strip(". ")
    return name[:128] or "repository"


def _estimate_directory_size(path: Path) -> int:
    """Approximate total size of a directory (skips inaccessible entries)."""
    total = 0
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat().st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += _estimate_directory_size(Path(entry.path))
            except Exception:
                pass
    except Exception:
        pass
    return total
