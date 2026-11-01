import sys
import os
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

def test_project_structure_exists():
    root = Path(__file__).resolve().parent.parent
    expected_dirs = [
        "backend",
        "frontend",
        "agents",
        "intelligence",
        "sandbox",
        "training",
        "evaluations",
        "tests",
        ".agents",
        "docker",
        "docs",
        "scripts",
    ]
    for d in expected_dirs:
        target = root / d
        assert target.exists() and target.is_dir(), f"Expected directory missing: {d}"

    expected_files = [
        ".env.example",
        "docker-compose.yml",
        "README.md",
        ".gitignore",
    ]
    for f in expected_files:
        target = root / f
        assert target.exists() and target.is_file(), f"Expected file missing: {f}"
