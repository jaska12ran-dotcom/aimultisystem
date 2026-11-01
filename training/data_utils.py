"""Shared dataset schema and prompt helpers for the CodeTwin training pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TASKS = {
    "repository_architecture",
    "code_to_documentation",
    "documentation_verification",
    "code_to_test",
    "test_failure_diagnosis",
    "change_impact",
    "business_rule_extraction",
    "security_evidence_extraction",
    "codebase_qa",
    "git_history_reasoning",
}
REQUIRED_FIELDS = {
    "example_id",
    "repository_id",
    "task",
    "repository_context",
    "code_context",
    "expected_output",
    "evidence",
    "verification_result",
    "confidence",
    "example_type",
}
SPLIT_NAMES = ("train", "validation", "test")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number}: each JSONL record must be an object")
            records.append(record)
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_prompt(record: dict[str, Any]) -> str:
    sections = [
        f"Task: {record['task']}",
        f"Repository ID: {record['repository_id']}",
        "Repository context:\n" + record["repository_context"],
        "Code context:\n" + record["code_context"],
        "Evidence policy: cite only exact file, symbol, or commit references "
        "supported by the supplied context. If the context is insufficient, say so.",
    ]
    if record.get("candidate_output"):
        sections.append("Candidate output to verify:\n" + record["candidate_output"])
    sections.append(
        "Return one JSON object with keys answer (string), evidence (array of exact "
        "references), confidence (number from 0 to 1), impacted_files (array), and "
        "findings (array). Do not claim facts unsupported by the supplied context."
    )
    return "\n\n".join(sections)


def build_target(record: dict[str, Any]) -> str:
    target = {
        "answer": record["expected_output"],
        "evidence": record["evidence"],
        "confidence": record["confidence"],
        "impacted_files": record.get("expected_impacted_files", []),
        "findings": record.get("expected_findings", []),
    }
    return json.dumps(target, ensure_ascii=False)
