import sys
from pathlib import Path

root = Path(__file__).resolve().parent
backend = root / 'backend'
for candidate in (str(root), str(backend)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
