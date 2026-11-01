"""Download, validate, and save instances from SWE-bench/SWE-bench_Verified."""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("codetwin.swebench_loader")

DEFAULT_DATASET = "SWE-bench/SWE-bench_Verified"
DEFAULT_SPLIT = "test"
DEFAULT_OUTPUT = Path(__file__).parent / "datasets" / "swebench" / "swebench_verified_raw.jsonl"


def extract_modified_files(patch: str) -> list[str]:
    """Extract touched filenames from a unified diff patch."""
    if not patch:
        return []
    files: list[str] = []
    # Match +++ b/filepath or --- a/filepath
    matches = re.findall(r"^\+\+\+\s+b/(.*?)$", patch, flags=re.MULTILINE)
    for m in matches:
        f = m.strip()
        if f and f != "/dev/null" and f not in files:
            files.append(f)
    if not files:
        # Fallback to diff --git a/file b/file
        git_matches = re.findall(r"^diff --git a/(\S+) b/(\S+)", patch, flags=re.MULTILINE)
        for _, b_path in git_matches:
            if b_path not in files:
                files.append(b_path)
    return files


def parse_test_list(raw: Any) -> list[str]:
    """Parse a test list which might be a list or a JSON-encoded string."""
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        raw_str = raw.strip()
        if not raw_str:
            return []
        try:
            parsed = json.loads(raw_str)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            pass
        return [raw_str]
    return []


def normalize_swebench_record(record: dict[str, Any], index: int) -> dict[str, Any] | None:
    """Validate and normalize a raw SWE-bench instance."""
    instance_id = record.get("instance_id")
    repo = record.get("repo")
    problem_statement = record.get("problem_statement")
    patch = record.get("patch")

    if not instance_id or not isinstance(instance_id, str):
        LOGGER.warning("Skipping instance %d: missing instance_id", index)
        return None
    if not repo or not isinstance(repo, str):
        LOGGER.warning("Skipping instance %s: missing repo", instance_id)
        return None
    if not problem_statement or not isinstance(problem_statement, str):
        LOGGER.warning("Skipping instance %s: missing problem_statement", instance_id)
        return None
    if not patch or not isinstance(patch, str):
        LOGGER.warning("Skipping instance %s: missing patch", instance_id)
        return None

    fail_to_pass = parse_test_list(record.get("FAIL_TO_PASS"))
    pass_to_pass = parse_test_list(record.get("PASS_TO_PASS"))
    modified_files = extract_modified_files(patch)

    return {
        "instance_id": instance_id.strip(),
        "repo": repo.strip(),
        "base_commit": str(record.get("base_commit", "")).strip(),
        "problem_statement": problem_statement.strip(),
        "patch": patch.strip(),
        "test_patch": str(record.get("test_patch", "")).strip(),
        "hints_text": str(record.get("hints_text", "")).strip(),
        "created_at": str(record.get("created_at", "")).strip(),
        "version": str(record.get("version", "")).strip(),
        "fail_to_pass": fail_to_pass,
        "pass_to_pass": pass_to_pass,
        "modified_files": modified_files,
        "environment_setup_commit": str(record.get("environment_setup_commit", "")).strip(),
    }


def load_swebench_dataset(
    dataset_name: str = DEFAULT_DATASET,
    split: str = DEFAULT_SPLIT,
    limit: int | None = None,
    output_path: Path | None = None,
) -> list[dict[str, Any]]:
    """
    Load SWE-bench Verified dataset from Hugging Face datasets and save to JSONL.
    """
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise RuntimeError("datasets library is not installed. Install with: pip install datasets") from exc

    LOGGER.info("Loading %s (split=%s)...", dataset_name, split)
    ds = load_dataset(dataset_name, split=split)

    normalized_records: list[dict[str, Any]] = []
    for idx, item in enumerate(ds):
        if limit is not None and len(normalized_records) >= limit:
            break
        row = dict(item)
        normalized = normalize_swebench_record(row, idx)
        if normalized:
            normalized_records.append(normalized)

    LOGGER.info("Loaded and normalized %d instances from %s", len(normalized_records), dataset_name)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="\n") as f:
            for rec in normalized_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        LOGGER.info("Saved records to %s", output_path)

    return normalized_records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help="Hugging Face dataset identifier")
    parser.add_argument("--split", default=DEFAULT_SPLIT, help="Dataset split (default: test)")
    parser.add_argument("--limit", type=int, default=None, help="Maximum instances to load")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSONL path")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        records = load_swebench_dataset(
            dataset_name=args.dataset,
            split=args.split,
            limit=args.limit,
            output_path=args.output,
        )
        print(f"Successfully loaded and saved {len(records)} SWE-bench Verified records to {args.output}")
        return 0
    except Exception as exc:
        LOGGER.error("Failed to load SWE-bench dataset: %s", exc)
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

