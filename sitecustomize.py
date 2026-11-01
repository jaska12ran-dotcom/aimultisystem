import sys
from pathlib import Path

root = Path(__file__).resolve().parent
backend = root / 'backend'
for candidate in (root, backend):
    path = str(candidate)
    if path not in sys.path:
        sys.path.insert(0, path)
