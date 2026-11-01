"""Validate held-out evaluation data, calculate metrics, and write JSON reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluations"))
from metrics.core import calculate_metrics  # noqa: E402


CATALOG_PATH = ROOT / "evaluations" / "benchmarks" / "catalog.json"


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
                raise ValueError(f"{path}:{line_number}: each row must be a JSON object")
            records.append(record)
    if not records:
        raise ValueError(f"{path}: file contains no records")
    return records


def load_training_repositories(path: Path) -> set[str]:
    repositories: set[str] = set()
    if path.suffix.casefold() == ".jsonl":
        rows = read_jsonl(path)
        values = [row.get("repository_id") for row in rows]
    else:
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            values = parsed
        elif isinstance(parsed, dict) and isinstance(parsed.get("repositories"), list):
            values = parsed["repositories"]
        else:
            values = [
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{path}: training repository entries must be non-empty strings")
        repositories.add(value)
    if not repositories:
        raise ValueError(f"{path}: no training repositories found")
    return repositories


def validate_records(
    examples: list[dict[str, Any]], predictions: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    example_by_id: dict[str, dict[str, Any]] = {}
    prediction_by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(examples, start=1):
        for field in ("example_id", "repository_id", "task"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"dataset row {index}: {field} must be a non-empty string")
        example_id = row["example_id"]
        if example_id in example_by_id:
            raise ValueError(f"dataset row {index}: duplicate example_id {example_id!r}")
        example_by_id[example_id] = row
    for index, row in enumerate(predictions, start=1):
        if not isinstance(row.get("example_id"), str) or not row["example_id"].strip():
            raise ValueError(f"prediction row {index}: example_id must be a non-empty string")
        example_id = row["example_id"]
        if example_id in prediction_by_id:
            raise ValueError(f"prediction row {index}: duplicate example_id {example_id!r}")
        prediction_by_id[example_id] = row
    missing = example_by_id.keys() - prediction_by_id.keys()
    unknown = prediction_by_id.keys() - example_by_id.keys()
    if missing or unknown:
        details = []
        if missing:
            details.append("missing predictions: " + ", ".join(sorted(missing)[:10]))
        if unknown:
            details.append("unknown predictions: " + ", ".join(sorted(unknown)[:10]))
        raise ValueError("; ".join(details))
    return example_by_id, prediction_by_id


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", required=True, help="Benchmark key from benchmarks/catalog.json")
    parser.add_argument("--dataset", required=True, type=Path, help="Normalized, labeled JSONL examples")
    parser.add_argument("--predictions", required=True, type=Path, help="CodeTwin prediction/outcome JSONL")
    parser.add_argument(
        "--training-repositories",
        required=True,
        type=Path,
        help="Repository IDs used for model training (.jsonl, JSON list/object, or one ID per line)",
    )
    parser.add_argument("--model", required=True, help="Model/agent identifier and version")
    parser.add_argument("--dataset-version", default="", help="Upstream benchmark release or revision")
    parser.add_argument("--harness-version", default="", help="Upstream evaluator/sandbox version")
    parser.add_argument("--code-revision", default="", help="CodeTwin commit or source revision evaluated")
    parser.add_argument("--license-reviewed", action="store_true", help="Confirm upstream terms were reviewed")
    parser.add_argument("--license-note", default="", help="Record the source/license review decision")
    parser.add_argument("--output", type=Path, help="Output JSON report path")
    args = parser.parse_args()

    if not args.license_reviewed or not args.license_note.strip():
        parser.error(
            "review dataset and underlying repository terms first, then provide "
            "--license-reviewed and a non-empty --license-note"
        )
    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        benchmark = catalog["benchmarks"].get(args.benchmark)
        if benchmark is None:
            raise ValueError(
                f"unknown benchmark {args.benchmark!r}; choose one of "
                + ", ".join(sorted(catalog["benchmarks"]))
            )
        examples = read_jsonl(args.dataset)
        predictions = read_jsonl(args.predictions)
        training_repositories = load_training_repositories(args.training_repositories)
        example_by_id, prediction_by_id = validate_records(examples, predictions)
        evaluation_repositories = {row["repository_id"] for row in examples}
        overlap = evaluation_repositories & training_repositories
        if overlap:
            raise ValueError(
                "evaluation is not held out: repository IDs overlap training: "
                + ", ".join(sorted(overlap))
            )
        ordered_examples = list(example_by_id.values())
        ordered_predictions = [prediction_by_id[key] for key in example_by_id]
        metrics, per_example = calculate_metrics(ordered_examples, ordered_predictions)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    report = {
        "schema_version": 1,
        "report_id": str(uuid4()),
        "created_at": now.isoformat(),
        "benchmark": {
            "key": args.benchmark,
            "display_name": benchmark["display_name"],
            "upstream": benchmark["upstream"],
            "license_review": benchmark["license_review"],
            "license_note": args.license_note.strip(),
            "dataset_version": args.dataset_version or None,
            "harness_version": args.harness_version or None,
        },
        "model": args.model,
        "code_revision": args.code_revision or None,
        "split_policy": "repository-disjoint from the supplied training repository manifest",
        "counts": {
            "examples": len(ordered_examples),
            "evaluation_repositories": len(evaluation_repositories),
            "training_repositories": len(training_repositories),
        },
        "provenance": {
            "dataset_path": str(args.dataset.resolve()),
            "dataset_sha256": sha256(args.dataset),
            "predictions_path": str(args.predictions.resolve()),
            "predictions_sha256": sha256(args.predictions),
            "training_repositories_path": str(args.training_repositories.resolve()),
            "training_repositories_sha256": sha256(args.training_repositories),
        },
        "metrics": metrics,
        "per_example": per_example,
    }
    output = args.output or (
        ROOT / "evaluations" / "reports"
        / f"{args.benchmark}-{now.strftime('%Y%m%dT%H%M%SZ')}-{report['report_id'][:8]}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Report written: {output}")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
