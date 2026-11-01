"""Normalize CodeSearchNet comment/code pairs into embedding training splits."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("codetwin.prepare_embedding_data")
DEFAULT_INPUT = (
    Path(__file__).parent
    / "datasets"
    / "processed"
    / "codesearchnet_pair_sample.jsonl"
)
DEFAULT_OUTPUT = Path(__file__).parent / "datasets" / "codesearchnet"
SPLITS = ("train", "validation", "test")


def prepare_records(
    records: list[dict[str, Any]],
    *,
    validation_fraction: float,
    test_fraction: float,
    seed: int,
) -> dict[str, list[dict[str, str]]]:
    if validation_fraction <= 0 or test_fraction <= 0:
        raise ValueError("validation and test fractions must both be greater than zero")
    if validation_fraction + test_fraction >= 1:
        raise ValueError("validation and test fractions must sum to less than one")

    by_code: dict[str, dict[str, str]] = {}
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"record {index}: expected a JSON object")
        comment = record.get("comment")
        code = record.get("code")
        if not isinstance(comment, str) or not comment.strip():
            raise ValueError(f"record {index}: comment must be a non-empty string")
        if not isinstance(code, str) or not code.strip():
            raise ValueError(f"record {index}: code must be a non-empty string")
        normalized_code = code.strip()
        by_code.setdefault(
            normalized_code,
            {"language": "mixed", "query": comment.strip(), "code": normalized_code},
        )

    unique_records = list(by_code.values())
    if len(unique_records) < 3:
        raise ValueError(
            f"at least 3 unique code examples are required for train/validation/test; "
            f"found {len(unique_records)}"
        )

    random.Random(seed).shuffle(unique_records)
    total = len(unique_records)
    test_count = max(1, round(total * test_fraction))
    validation_count = max(1, round(total * validation_fraction))
    if test_count + validation_count >= total:
        raise ValueError("split fractions leave no examples for training")

    test_end = test_count
    validation_end = test_end + validation_count
    return {
        "test": unique_records[:test_end],
        "validation": unique_records[test_end:validation_end],
        "train": unique_records[validation_end:],
    }


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
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            records.append(record)
    return records


def write_splits(output_dir: Path, splits: dict[str, list[dict[str, str]]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary_paths: dict[str, Path] = {}
    try:
        for split in SPLITS:
            output_path = output_dir / f"{split}.jsonl"
            temporary_path = output_path.with_suffix(".jsonl.tmp")
            temporary_paths[split] = temporary_path
            with temporary_path.open("w", encoding="utf-8", newline="\n") as stream:
                for record in splits[split]:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")

        for split, temporary_path in temporary_paths.items():
            temporary_path.replace(output_dir / f"{split}.jsonl")
    except OSError:
        for temporary_path in temporary_paths.values():
            temporary_path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validation-fraction", type=float, default=0.1)
    parser.add_argument("--test-fraction", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        splits = prepare_records(
            read_jsonl(args.input),
            validation_fraction=args.validation_fraction,
            test_fraction=args.test_fraction,
            seed=args.seed,
        )
        write_splits(args.output_dir, splits)
    except (OSError, ValueError) as exc:
        LOGGER.error("Embedding data preparation failed: %s", exc)
        return 1

    LOGGER.info(
        "Wrote development splits to %s (deduplicated by exact code): %s",
        args.output_dir,
        {split: len(rows) for split, rows in splits.items()},
    )
    LOGGER.warning(
        "The source pair config has no repository IDs or held-out splits; "
        "these partitions are not repository-isolated benchmark data."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
