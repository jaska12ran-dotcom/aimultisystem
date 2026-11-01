"""Convert CodeSearchNet documentation/code pairs to repo-isolated SFT JSONL."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger("codetwin.codegen_data")
DEFAULT_INPUT = (
    Path(__file__).parent
    / "datasets"
    / "processed"
    / "codesearchnet_java_train_sample_full.jsonl"
)
DEFAULT_OUTPUT = Path(__file__).parent / "datasets" / "processed" / "codegen_java"


def repository_split(repository_id: str) -> str:
    bucket = int.from_bytes(hashlib.sha256(repository_id.encode("utf-8")).digest()[:4], "big") % 100
    if bucket < 80:
        return "train"
    if bucket < 90:
        return "validation"
    return "test"


def convert_record(record: dict[str, Any], line_number: int) -> dict[str, str]:
    required = (
        "repository_name",
        "func_path_in_repository",
        "func_name",
        "func_code_string",
        "func_documentation_string",
        "func_code_url",
    )
    for field in required:
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"line {line_number}: {field} must be a non-empty string")

    prompt = (
        "Implement the Java function described below. Return only the complete "
        "function implementation; do not add explanations or Markdown fences.\n\n"
        f"Function name: {record['func_name'].strip()}\n"
        f"Repository path: {record['func_path_in_repository'].strip()}\n"
        f"Documentation:\n{record['func_documentation_string'].strip()}"
    )
    return {
        "repository_id": record["repository_name"].strip(),
        "instruction": prompt,
        "completion": record["func_code_string"].strip(),
        "source_url": record["func_code_url"].strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Full raw JSONL split from the loader")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--min-examples",
        type=int,
        default=1000,
        help="Reject ingestion-test-sized inputs; lower only for an intentional smoke test",
    )
    args = parser.parse_args()

    if args.min_examples <= 0:
        parser.error("--min-examples must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    temporary_paths: dict[str, Path] = {}
    streams = {}
    counts = {"train": 0, "validation": 0, "test": 0}
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for split in counts:
            temporary_paths[split] = args.output_dir / f"{split}.jsonl.tmp"
            streams[split] = temporary_paths[split].open("w", encoding="utf-8", newline="\n")

        with args.input.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{args.input}:{line_number}: invalid JSON: {exc.msg}") from exc
                if not isinstance(raw, dict):
                    raise ValueError(f"{args.input}:{line_number}: each row must be a JSON object")
                row = convert_record(raw, line_number)
                split = repository_split(row["repository_id"])
                streams[split].write(json.dumps(row, ensure_ascii=False) + "\n")
                counts[split] += 1
    except (OSError, ValueError) as exc:
        for stream in streams.values():
            stream.close()
        LOGGER.error("Code-generation dataset preparation failed: %s", exc)
        for path in temporary_paths.values():
            path.unlink(missing_ok=True)
        return 1
    for stream in streams.values():
        stream.close()

    total = sum(counts.values())
    if not all(counts.values()) or total < args.min_examples:
        LOGGER.error(
            "Preparation requires non-empty splits and at least %d rows; found %s (%d total)",
            args.min_examples,
            counts,
            total,
        )
        for path in temporary_paths.values():
            path.unlink(missing_ok=True)
        return 1
    for split, temporary_path in temporary_paths.items():
        temporary_path.replace(args.output_dir / f"{split}.jsonl")
    LOGGER.info("Repository-isolated SFT data written to %s: %s", args.output_dir, counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
