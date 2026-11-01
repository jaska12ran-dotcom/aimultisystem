import hashlib
from pathlib import Path

def calculate_checksum(file_path: Path | str) -> str:
    """Calculates SHA256 checksum of a file for integrity tracking."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()

def hash_text(text: str) -> str:
    """Computes SHA256 of text string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
