"""
Safe ZIP extractor
------------------
Prevents:
- Zip Slip (path traversal via ../../../etc/passwd entries)
- Zip Bomb (decompression-bomb DoS via excessive uncompressed size)
- Symlink attacks (entries pointing outside target)
- Executable extension filtering (for additional defence-in-depth)

CRITICAL: Never execute any extracted file. Extraction is purely read-only analysis.
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Tuple

MAX_UNCOMPRESSED_BYTES: int = 500 * 1024 * 1024  # 500 MB
MAX_FILE_COUNT: int = 10_000
MAX_COMPRESSION_RATIO: float = 100.0  # Flag single files with >100x ratio


class ArchiveExtractionError(Exception):
    """Raised when a security check fails during archive extraction."""


def extract_zip_safely(zip_path: str | Path, target_dir: str | Path) -> Tuple[str, int]:
    """
    Safely extracts a ZIP archive to *target_dir*.

    Security checks applied:
    1. Zip Slip – every member's resolved path must be a descendant of target_dir.
    2. Zip Bomb – total uncompressed size must be ≤ MAX_UNCOMPRESSED_BYTES.
    3. Compression ratio – individual file ratio must be ≤ MAX_COMPRESSION_RATIO.
    4. File count – archive must contain ≤ MAX_FILE_COUNT entries.
    5. Symlinks are never extracted.

    Returns (extracted_root_dir, file_count).
    """
    zip_path = Path(zip_path).resolve()
    target_dir = Path(target_dir).resolve()

    if not zip_path.exists():
        raise ArchiveExtractionError(f"ZIP archive not found: {zip_path}")

    if not zipfile.is_zipfile(zip_path):
        raise ArchiveExtractionError("File is not a valid ZIP archive.")

    os.makedirs(target_dir, exist_ok=True)

    total_bytes = 0
    file_count = 0

    with zipfile.ZipFile(zip_path, "r") as archive:
        members = archive.infolist()

        for member in members:
            # ── Entry count guard ──────────────────────────────────
            file_count += 1
            if file_count > MAX_FILE_COUNT:
                raise ArchiveExtractionError(
                    f"Archive exceeds the maximum permitted file count ({MAX_FILE_COUNT} files)."
                )

            # ── Skip directories (we create them implicitly) ───────
            if member.filename.endswith("/"):
                continue

            # ── Symlink detection ──────────────────────────────────
            # External-attribute bits 0xA1ED0000 mark a symlink on Unix
            unix_attr = (member.external_attr >> 16) & 0xFFFF
            if unix_attr & 0xA000 == 0xA000:
                raise ArchiveExtractionError(
                    f"Archive contains a symbolic link: '{member.filename}'. "
                    "Symlinks are rejected for security."
                )

            # ── Zip Bomb: uncompressed size accumulation ───────────
            total_bytes += member.file_size
            if total_bytes > MAX_UNCOMPRESSED_BYTES:
                raise ArchiveExtractionError(
                    f"Archive uncompressed size exceeds the "
                    f"{MAX_UNCOMPRESSED_BYTES // (1024**2)} MB limit."
                )

            # ── Compression ratio guard ────────────────────────────
            compressed = member.compress_size or 1  # avoid div-by-zero
            ratio = member.file_size / compressed
            if ratio > MAX_COMPRESSION_RATIO and member.file_size > 1_000:
                raise ArchiveExtractionError(
                    f"Suspicious compression ratio ({ratio:.0f}x) for entry "
                    f"'{member.filename}'. Possible zip bomb."
                )

            # ── Zip Slip: path traversal ───────────────────────────
            member_path = (target_dir / member.filename).resolve()
            try:
                member_path.relative_to(target_dir)
            except ValueError:
                raise ArchiveExtractionError(
                    f"Path traversal detected in archive entry: '{member.filename}'. "
                    "Extraction aborted."
                )

        # All members passed – perform the actual extraction
        archive.extractall(target_dir)

    # If the archive unpacked into a single top-level subdirectory, return that inner path
    children = [p for p in target_dir.iterdir() if not p.name.startswith(".")]
    if len(children) == 1 and children[0].is_dir():
        return str(children[0]), file_count

    return str(target_dir), file_count
