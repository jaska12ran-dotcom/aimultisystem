"""Download, validate, deduplicate, and save a sample from a Hugging Face dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from datasets import Sequence, Value, load_dataset
from datasets.exceptions import DatasetGenerationError, DatasetNotFoundError
from huggingface_hub.errors import HfHubHTTPError


LOGGER = logging.getLogger("codetwin.dataset_loader")
DEFAULT_SETTINGS = Path(__file__).parent / "dataset_settings.json"


def read_settings(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as stream:
            settings = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read settings from {path}: {exc}") from exc
    if not isinstance(settings, dict):
        raise ValueError(f"{path}: settings must be a JSON object")

    required = {
        "dataset_id",
        "config",
        "split",
        "limit",
        "output",
        "features",
        "required_content_fields",
        "deduplicate_fields",
    }
    missing = required - settings.keys()
    if missing:
        raise ValueError(f"{path}: missing settings: {', '.join(sorted(missing))}")
    if not isinstance(settings["limit"], int) or isinstance(settings["limit"], bool) or settings["limit"] <= 0:
        raise ValueError(f"{path}: limit must be a positive integer")
    if not isinstance(settings["features"], dict) or not settings["features"]:
        raise ValueError(f"{path}: features must be a non-empty object")
    if not all(
        isinstance(settings[field], str) and settings[field].strip()
        for field in ("dataset_id", "config", "split", "output")
    ):
        raise ValueError(f"{path}: dataset_id, config, split, and output must be non-empty strings")
    for key, value in settings["features"].items():
        if not isinstance(key, str) or not isinstance(value, str) or not value:
            raise ValueError(f"{path}: each feature name and type must be a non-empty string")
    for field in ("required_content_fields", "deduplicate_fields"):
        value = settings[field]
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item in settings["features"] for item in value)
        ):
            raise ValueError(f"{path}: {field} must list known feature names")
    return settings


def validate_feature_schema(features: Any, expected: dict[str, str]) -> None:
    if not isinstance(features, dict):
        raise ValueError("dataset loader did not expose a feature schema")
    actual_schema: dict[str, str] = {}
    for key, feature in features.items():
        if isinstance(feature, Value):
            actual_schema[key] = feature.dtype
        elif isinstance(feature, Sequence) and isinstance(feature.feature, Value):
            actual_schema[key] = f"sequence<{feature.feature.dtype}>"
        else:
            actual_schema[key] = type(feature).__name__
    if actual_schema != expected:
        raise ValueError(f"dataset feature schema mismatch: expected {expected}, found {actual_schema}")


def normalize_record(
    record: dict[str, Any],
    index: int,
    required_content_fields: list[str],
) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        LOGGER.warning("Skipping example %d: row is not an object", index)
        return None
    for key in required_content_fields:
        value = record.get(key)
        if not isinstance(value, str) or not value.strip():
            LOGGER.warning("Skipping example %d: %s is empty or not a string", index, key)
            return None
    return record


def iter_valid_examples(
    settings: dict[str, Any],
    stats: dict[str, int],
    limit: int | None = None,
) -> Iterator[dict[str, Any]]:
    dataset_id = settings["dataset_id"]
    config = settings["config"]
    split = settings["split"]

    LOGGER.info(
        "Loading %s config=%s split=%s (%s, limit=%s)",
        dataset_id,
        config,
        split,
        "streaming" if limit is not None else "complete split",
        limit if limit is not None else "all",
    )
    dataset = load_dataset(
        dataset_id,
        name=config,
        split=split,
        streaming=limit is not None,
    )
    validate_feature_schema(dataset.features, settings["features"])

    seen_examples: set[str] = set()
    yielded = 0
    for index, raw_record in enumerate(dataset):
        if limit is not None and yielded >= limit:
            break
        stats["read"] += 1
        row = normalize_record(raw_record, index, settings["required_content_fields"])
        if row is None:
            stats["empty_or_invalid"] += 1
            continue
        pair = "\0".join(
            str(row[field]).strip()
            for field in settings["deduplicate_fields"]
        )
        example_key = hashlib.sha256(pair.encode("utf-8")).hexdigest()
        if example_key in seen_examples:
            stats["duplicate"] += 1
            continue
        seen_examples.add(example_key)
        yielded += 1
        yield row


def load_sample(settings: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    stats = {"read": 0, "empty_or_invalid": 0, "duplicate": 0}
    rows = list(iter_valid_examples(settings, stats, settings["limit"]))
    if len(rows) != settings["limit"]:
        raise ValueError(
            f"requested {settings['limit']} unique valid examples, found {len(rows)}"
        )
    return rows, stats


def write_full_split(settings: dict[str, Any], output: Path) -> dict[str, int]:
    stats = {"read": 0, "empty_or_invalid": 0, "duplicate": 0}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(output.suffix + ".tmp")
    try:
        with temporary_output.open("w", encoding="utf-8", newline="\n") as stream:
            for row in iter_valid_examples(settings, stats):
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        if stats["read"] == 0:
            raise ValueError("dataset split contains no records")
        temporary_output.replace(output)
    except (
        OSError,
        ValueError,
        ImportError,
        RuntimeError,
        ConnectionError,
        TimeoutError,
        DatasetGenerationError,
        DatasetNotFoundError,
        HfHubHTTPError,
    ):
        temporary_output.unlink(missing_ok=True)
        raise
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_SETTINGS, help="JSON dataset settings file")
    parser.add_argument("--limit", type=int, help="Override the configured sample size")
    parser.add_argument("--output", type=Path, help="Override the configured output JSONL path")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Stream the complete configured split instead of the limited sample",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        settings = read_settings(args.config)
        if args.limit is not None:
            if args.all:
                raise ValueError("--limit and --all cannot be used together")
            if args.limit <= 0:
                raise ValueError("--limit must be positive")
            settings["limit"] = args.limit
        configured_output = Path(__file__).parent / settings["output"]
        if args.all:
            output = args.output or configured_output.with_name(
                f"{configured_output.stem}_full{configured_output.suffix}"
            )
            stats = write_full_split(settings, output)
            count = stats["read"] - stats["empty_or_invalid"] - stats["duplicate"]
        else:
            rows, stats = load_sample(settings)
            output = args.output or configured_output
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("w", encoding="utf-8", newline="\n") as stream:
                for row in rows:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            count = len(rows)
    except (
        OSError,
        ValueError,
        ImportError,
        RuntimeError,
        ConnectionError,
        TimeoutError,
        DatasetGenerationError,
        DatasetNotFoundError,
        HfHubHTTPError,
    ) as exc:
        LOGGER.error("Dataset loading failed: %s", exc)
        return 1

    LOGGER.info(
        "Saved %d examples to %s (read=%d invalid=%d duplicate=%d)",
        count,
        output,
        stats["read"],
        stats["empty_or_invalid"],
        stats["duplicate"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
