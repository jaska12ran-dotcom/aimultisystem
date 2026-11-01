from __future__ import annotations

import json
import re
from typing import Any, Dict


def parse_result(exit_code: int, stdout: str, stderr: str, duration: float, language: str) -> Dict[str, Any]:
    combined = "\n".join(part for part in [stdout, stderr] if part)
    status = "passed" if exit_code == 0 else "failed"
    tests = {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
    coverage: Dict[str, Any] = {}

    if language in {"python", "javascript", "typescript", "java"}:
        pytest_match = re.search(r"(\d+) passed(?:,\s*(\d+) failed)?(?:,\s*(\d+) skipped)?", combined, re.IGNORECASE)
        if pytest_match:
            tests["passed"] = int(pytest_match.group(1))
            tests["failed"] = int(pytest_match.group(2) or 0)
            tests["skipped"] = int(pytest_match.group(3) or 0)
            tests["total"] = tests["passed"] + tests["failed"] + tests["skipped"]
            status = "passed" if exit_code == 0 and tests["failed"] == 0 else "failed"

        jest_match = re.search(r"Tests:\s*(\d+)\s+passed(?:,\s*(\d+)\s+failed)?(?:,\s*(\d+)\s+skipped)?", combined, re.IGNORECASE)
        if jest_match:
            tests["passed"] = int(jest_match.group(1))
            tests["failed"] = int(jest_match.group(2) or 0)
            tests["skipped"] = int(jest_match.group(3) or 0)
            tests["total"] = tests["passed"] + tests["failed"] + tests["skipped"]
            status = "passed" if exit_code == 0 and tests["failed"] == 0 else "failed"

        java_match = re.search(r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)", combined, re.IGNORECASE)
        if java_match:
            tests["total"] = int(java_match.group(1))
            tests["failed"] = int(java_match.group(2))
            tests["skipped"] = int(java_match.group(4))
            tests["passed"] = max(0, tests["total"] - tests["failed"] - tests["skipped"])
            status = "passed" if exit_code == 0 and tests["failed"] == 0 else "failed"

        coverage_match = re.search(r"TOTAL\s+\d+\s+\d+\s+\d+\s+(\d+)%", combined, re.IGNORECASE)
        if coverage_match:
            coverage = {"percent": int(coverage_match.group(1))}

        coverage_json = None
        if "coverage" in combined.lower():
            try:
                coverage_json = json.loads(combined)
            except Exception:
                coverage_json = None
        if isinstance(coverage_json, dict):
            coverage = coverage_json.get("coverage", coverage_json)

    if exit_code == 0 and tests["failed"] == 0 and tests["total"] == 0:
        status = "passed"
    elif exit_code != 0 and tests["failed"] == 0 and tests["total"] == 0:
        status = "failed"

    return {
        "status": status,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "duration": round(duration, 3),
        "coverage": coverage,
        "tests": tests,
    }
