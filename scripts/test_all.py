import subprocess
import sys
from pathlib import Path

def run_cmd(cmd, cwd=None):
    print(f"\n[RUNNING] {cmd} in {cwd or '.'}")
    res = subprocess.run(cmd, shell=True, cwd=cwd)
    if res.returncode != 0:
        print(f"[FAILED] {cmd}")
        sys.exit(res.returncode)
    print(f"[SUCCESS] {cmd}")

def main():
    root = Path(__file__).resolve().parent.parent
    
    # 1. Backend tests
    python_bin = root / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python_bin.exists():
        python_bin = "python"
    
    run_cmd(f'"{python_bin}" -m pytest backend/tests -v', cwd=root)
    run_cmd(f'"{python_bin}" -m pytest tests -v', cwd=root)

    # 2. Frontend build
    run_cmd("npm run build", cwd=root / "frontend")

    print("\n All CodeTwin verifications passed successfully!")

if __name__ == "__main__":
    main()
