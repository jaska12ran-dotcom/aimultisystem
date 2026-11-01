"""Validate examples and create deterministic repository-isolated JSONL splits."""

from __future__ import annotations

import argparse
import random
from collections import defaultdict
from pathlib import Path

from data_utils import SPLIT_NAMES, read_jsonl, write_jsonl
from validate_data import validate_records, validate_splits


def split_by_repository(
    records: list[dict],
    *,
    seed: int,
    validation_fraction: float,
    test_fraction: float,
) -> dict[str, list[dict]]:
    if validation_fraction <= 0 or test_fraction <= 0:
        raise ValueError("validation and test fractions must both be greater than zero")
    if validation_fraction + test_fraction >= 1:
        raise ValueError("validation and test fractions must sum to less than one")

    groups: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        groups[record["repository_id"]].append(record)
    repositories = list(groups)
    if len(repositories) < 3:
        raise ValueError(
            f"at least 3 distinct repositories are required for train/validation/test; "
            f"found {len(repositories)}"
        )

    random.Random(seed).shuffle(repositories)
    repository_count = len(repositories)
    test_count = max(1, round(repository_count * test_fraction))
    validation_count = max(1, round(repository_count * validation_fraction))
    if test_count + validation_count >= repository_count:
        raise ValueError(
            "split fractions leave no repository for training; add repositories or adjust fractions"
        )

    assignments = {
        "test": set(repositories[:test_count]),
        "validation": set(repositories[test_count : test_count + validation_count]),
        "train": set(repositories[test_count + validation_count :]),
    }
    splits = {
        split: [record for record in records if record["repository_id"] in repo_ids]
        for split, repo_ids in assignments.items()
    }
    return splits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).parent / "datasets" / "examples.jsonl",
        help="Validated JSONL source examples",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent / "datasets" / "processed",
        help="Directory for train.jsonl, validation.jsonl, and test.jsonl",
    )
    parser.add_argument("--validation-fraction", type=float, default=0.15)
    parser.add_argument("--test-fraction", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--require-verified", action="store_true")
    args = parser.parse_args()

    try:
        records = read_jsonl(args.input)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1
    errors = validate_records(
        records,
        args.input,
        require_both_labels=True,
        require_verified=args.require_verified,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    try:
        splits = split_by_repository(
            records,
            seed=args.seed,
            validation_fraction=args.validation_fraction,
            test_fraction=args.test_fraction,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    for split in SPLIT_NAMES:
        write_jsonl(args.output_dir / f"{split}.jsonl", splits[split])
    errors = validate_splits(args.output_dir, require_verified=args.require_verified)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    for split in SPLIT_NAMES:
        repos = len({row["repository_id"] for row in splits[split]})
        print(f"{split}: {len(splits[split])} examples from {repos} repositories")
    print(f"Repository-isolated splits written to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
