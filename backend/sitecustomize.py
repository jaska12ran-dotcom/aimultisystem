import sys
from pathlib import Path

backend = Path(__file__).resolve().parent
root = backend.parent
for candidate in (backend, root):
    path = str(candidate)
    if path not in sys.path:
        sys.path.insert(0, path)
