"""Validate CodeTwin JSONL examples and repository-isolated dataset splits."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

from data_utils import REQUIRED_FIELDS, SPLIT_NAMES, TASKS, read_jsonl


def validate_records(
    records: list[dict[str, Any]],
    source: Path,
    *,
    require_both_labels: bool = True,
    require_all_tasks: bool = False,
    require_verified: bool = False,
) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    observed_tasks: set[str] = set()
    observed_types: set[str] = set()
    unverified = 0

    for index, record in enumerate(records, start=1):
        line = index
        location = f"{source}:{line}"
        missing = REQUIRED_FIELDS - record.keys()
        if missing:
            errors.append(f"{location}: missing fields: {', '.join(sorted(missing))}")
            continue

        for field in ("example_id", "repository_id", "repository_context", "code_context", "expected_output"):
            if not isinstance(record[field], str) or not record[field].strip():
                errors.append(f"{location}: {field} must be a non-empty string")
        example_id = record["example_id"]
        if isinstance(example_id, str):
            if example_id in seen_ids:
                errors.append(f"{location}: duplicate example_id {example_id!r}")
            seen_ids.add(example_id)

        task = record["task"]
        if not isinstance(task, str) or task not in TASKS:
            errors.append(f"{location}: unsupported task {task!r}")
        else:
            observed_tasks.add(task)

        evidence = record["evidence"]
        if not isinstance(evidence, list) or not evidence or not all(
            isinstance(item, str) and item.strip() for item in evidence
        ):
            errors.append(f"{location}: evidence must be a non-empty array of strings")

        verification = record["verification_result"]
        if not isinstance(verification, dict):
            errors.append(f"{location}: verification_result must be an object")
        elif not isinstance(verification.get("status"), str) or verification["status"] not in {
            "passed",
            "failed",
            "not_run",
        }:
            errors.append(
                f"{location}: verification_result.status must be passed, failed, or not_run"
            )
        elif not isinstance(verification.get("method"), str) or not verification["method"].strip():
            errors.append(f"{location}: verification_result.method must be a non-empty string")
        elif verification["status"] == "not_run":
            unverified += 1

        confidence = record["confidence"]
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            errors.append(f"{location}: confidence must be a finite number from 0 to 1")

        example_type = record["example_type"]
        if not isinstance(example_type, str) or example_type not in {"positive", "negative"}:
            errors.append(f"{location}: example_type must be positive or negative")
        else:
            observed_types.add(example_type)
            if example_type == "negative" and (
                not isinstance(record.get("candidate_output"), str)
                or not record["candidate_output"].strip()
            ):
                errors.append(f"{location}: negative examples require candidate_output")

        for optional_list in ("expected_impacted_files", "expected_findings"):
            if optional_list in record and (
                not isinstance(record[optional_list], list)
                or not all(isinstance(item, str) and item.strip() for item in record[optional_list])
            ):
                errors.append(f"{location}: {optional_list} must be an array of non-empty strings")

    if not records:
        errors.append(f"{source}: dataset has no records")
    if require_both_labels and observed_types != {"positive", "negative"}:
        errors.append(f"{source}: include both positive and negative examples")
    if require_all_tasks and observed_tasks != TASKS:
        errors.append(f"{source}: missing task categories: {', '.join(sorted(TASKS - observed_tasks))}")
    if require_verified and unverified:
        errors.append(f"{source}: {unverified} examples are not execution-verified")
    if unverified:
        print(f"WARNING: {source}: {unverified} example(s) have verification status not_run")
    return errors


def validate_splits(split_dir: Path, *, require_verified: bool = False) -> list[str]:
    errors: list[str] = []
    repo_sets: dict[str, set[str]] = {}
    observed_types: set[str] = set()
    for split in SPLIT_NAMES:
        path = split_dir / f"{split}.jsonl"
        if not path.is_file():
            errors.append(f"{path}: split file does not exist")
            continue
        try:
            records = read_jsonl(path)
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
            continue
        errors.extend(
            validate_records(
                records,
                path,
                require_both_labels=False,
                require_verified=require_verified,
            )
        )
        repo_sets[split] = {record["repository_id"] for record in records if isinstance(record.get("repository_id"), str)}
        observed_types.update(
            record["example_type"]
            for record in records
            if record.get("example_type") in {"positive", "negative"}
        )
    if observed_types != {"positive", "negative"}:
        errors.append(f"{split_dir}: combined splits must contain positive and negative examples")
    for first_index, first in enumerate(SPLIT_NAMES):
        for second in SPLIT_NAMES[first_index + 1 :]:
            overlap = repo_sets.get(first, set()) & repo_sets.get(second, set())
            if overlap:
                errors.append(
                    f"{split_dir}: repository leakage between {first} and {second}: "
                    + ", ".join(sorted(overlap))
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).parent / "datasets" / "examples.jsonl",
        help="JSONL source dataset",
    )
    parser.add_argument("--require-all-tasks", action="store_true")
    parser.add_argument("--require-verified", action="store_true")
    parser.add_argument("--splits-dir", type=Path, help="Also validate train/validation/test split files")
    args = parser.parse_args()

    try:
        records = read_jsonl(args.input)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1
    errors = validate_records(
        records,
        args.input,
        require_all_tasks=args.require_all_tasks,
        require_verified=args.require_verified,
    )
    if args.splits_dir:
        errors.extend(validate_splits(args.splits_dir, require_verified=args.require_verified))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Validation succeeded: {len(records)} source examples in {args.input}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
