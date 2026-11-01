"""Convert SWE-bench/SWE-bench_Verified dataset into repository-isolated training splits."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from training.data_utils import write_jsonl
    from training.load_swebench_dataset import DEFAULT_OUTPUT as DEFAULT_RAW_INPUT, extract_modified_files
except ModuleNotFoundError:
    from data_utils import write_jsonl
    from load_swebench_dataset import DEFAULT_OUTPUT as DEFAULT_RAW_INPUT, extract_modified_files

LOGGER = logging.getLogger("codetwin.prepare_swebench")
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "datasets" / "processed" / "swebench"


def partition_repositories(
    repositories: list[str],
    seed: int = 42,
    val_pct: int = 15,
    test_pct: int = 15,
) -> dict[str, set[str]]:
    """
    Partition unique repositories deterministically into disjoint sets for test, validation, and train.
    Guarantees zero repository leakage across splits.
    """
    import random
    unique_repos = sorted(list(set(repositories)))
    if len(unique_repos) < 3:
        return {
            "test": set(),
            "validation": set(unique_repos[1:]) if len(unique_repos) == 2 else set(),
            "train": set(unique_repos[:1]),
        }

    rng = random.Random(seed)
    shuffled = list(unique_repos)
    rng.shuffle(shuffled)

    n = len(shuffled)
    test_count = max(1, round(n * test_pct / 100))
    val_count = max(1, round(n * val_pct / 100))
    if test_count + val_count >= n:
        test_count = 1
        val_count = 1

    test_repos = set(shuffled[:test_count])
    val_repos = set(shuffled[test_count : test_count + val_count])
    train_repos = set(shuffled[test_count + val_count :])

    return {
        "test": test_repos,
        "validation": val_repos,
        "train": train_repos,
    }


def repository_split(repository_id: str, seed: int = 42, val_pct: int = 15, test_pct: int = 15) -> str:
    """
    Deterministically assign a single repository to a split.
    """
    key = f"{seed}:{repository_id}".encode("utf-8")
    bucket = int.from_bytes(hashlib.sha256(key).digest()[:4], "big") % 100
    if bucket < test_pct:
        return "test"
    if bucket < test_pct + val_pct:
        return "validation"
    return "train"


def format_as_multitask_record(item: dict[str, Any]) -> dict[str, Any]:
    """
    Format a SWE-bench record to match CodeTwin's 10-task SFT schema.
    Task: test_failure_diagnosis
    """
    repo = item["repo"]
    instance_id = item["instance_id"]
    problem = item.get("problem_statement", "")
    patch = item.get("patch", "")
    fail_to_pass = item.get("fail_to_pass", [])
    version = item.get("version", "")
    base_commit = item.get("base_commit", "")
    hints = item.get("hints_text", "")
    files = item.get("modified_files") or extract_modified_files(patch)
    if not files:
        files = [f"src/{repo.split('/')[-1]}"]

    repo_context_obj = {
        "repository": repo,
        "instance_id": instance_id,
        "base_commit": base_commit,
        "version": version,
    }
    if hints:
        repo_context_obj["hints"] = hints

    failing_text = "\n".join(f"- {t}" for t in fail_to_pass) if fail_to_pass else "Issue tests specified in issue"

    code_context = (
        f"Problem Description:\n{problem}\n\n"
        f"Failing Tests to Fix:\n{failing_text}"
    )

    record = {
        "example_id": f"swebench_{instance_id}",
        "repository_id": repo,
        "task": "test_failure_diagnosis",
        "repository_context": json.dumps(repo_context_obj, ensure_ascii=False),
        "code_context": code_context,
        "expected_output": patch,
        "evidence": files,
        "verification_result": {
            "status": "passed",
            "method": "swebench_verified_harness",
        },
        "confidence": 1.0,
        "example_type": "positive",
        "expected_impacted_files": files,
    }
    return record


def format_as_instruction_record(item: dict[str, Any]) -> dict[str, Any]:
    """
    Format as an instruction-completion pair for direct causal language model fine-tuning.
    """
    repo = item["repo"]
    instance_id = item["instance_id"]
    problem = item.get("problem_statement", "")
    patch = item.get("patch", "")
    base_commit = item.get("base_commit", "")
    fail_to_pass = item.get("fail_to_pass", [])
    failing_text = "\n".join(f"- {t}" for t in fail_to_pass) if fail_to_pass else "See problem statement"

    instruction = (
        f"Fix the bug described below in repository {repo}.\n"
        f"Instance ID: {instance_id}\n\n"
        f"Issue Description:\n{problem}\n\n"
        f"Target Failing Tests:\n{failing_text}\n\n"
        "Generate only the git unified diff patch that resolves the issue."
    )

    return {
        "instance_id": instance_id,
        "repository_id": repo,
        "instruction": instruction,
        "completion": patch,
        "source_url": f"https://github.com/{repo}/tree/{base_commit}" if base_commit else f"https://github.com/{repo}",
    }


def prepare_swebench_splits(
    records: list[dict[str, Any]],
    output_dir: Path,
    seed: int = 42,
    val_pct: int = 15,
    test_pct: int = 15,
) -> dict[str, int]:
    """
    Split records by repository into train, validation, and test.
    Ensures zero repository leakage between splits.
    Writes both multitask schema and instruction format JSONL files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    inst_dir = output_dir / "instructions"
    inst_dir.mkdir(parents=True, exist_ok=True)

    multitask_splits: dict[str, list[dict[str, Any]]] = defaultdict(list)
    instruction_splits: dict[str, list[dict[str, Any]]] = defaultdict(list)
    repos_by_split = partition_repositories(
        [item["repo"] for item in records],
        seed=seed,
        val_pct=val_pct,
        test_pct=test_pct,
    )
    repo_to_split = {}
    for s_name, s_repos in repos_by_split.items():
        for r in s_repos:
            repo_to_split[r] = s_name

    for item in records:
        repo = item["repo"]
        split = repo_to_split.get(repo, "train")

        mt_record = format_as_multitask_record(item)
        inst_record = format_as_instruction_record(item)

        multitask_splits[split].append(mt_record)
        instruction_splits[split].append(inst_record)

    # Verify repository isolation
    train_repos = repos_by_split["train"]
    val_repos = repos_by_split["validation"]
    test_repos = repos_by_split["test"]

    assert train_repos.isdisjoint(val_repos), f"Repository leakage between train and val: {train_repos & val_repos}"
    assert train_repos.isdisjoint(test_repos), f"Repository leakage between train and test: {train_repos & test_repos}"
    assert val_repos.isdisjoint(test_repos), f"Repository leakage between val and test: {val_repos & test_repos}"

    counts = {}
    for split_name in ("train", "validation", "test"):
        mt_file = output_dir / f"{split_name}.jsonl"
        inst_file = inst_dir / f"{split_name}.jsonl"

        mt_rows = multitask_splits[split_name]
        inst_rows = instruction_splits[split_name]

        write_jsonl(mt_file, mt_rows)
        write_jsonl(inst_file, inst_rows)

        counts[split_name] = len(mt_rows)
        LOGGER.info(
            "Split %s: %d instances across %d repositories",
            split_name,
            len(mt_rows),
            len(repos_by_split[split_name]),
        )

    summary_file = output_dir / "split_summary.json"
    with summary_file.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "counts": counts,
                "repositories": {s: sorted(list(r)) for s, r in repos_by_split.items()},
                "seed": seed,
            },
            f,
            indent=2,
        )

    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_RAW_INPUT, help="Raw SWE-bench JSONL input")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for split outputs")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for repo partitioning")
    parser.add_argument("--val-pct", type=int, default=15, help="Validation percentage (default: 15)")
    parser.add_argument("--test-pct", type=int, default=15, help="Test percentage (default: 15)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if not args.input.is_file():
        parser.error(f"Input file not found: {args.input}. Run load_swebench_dataset.py first or pass --input.")

    records = []
    with args.input.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    counts = prepare_swebench_splits(
        records,
        output_dir=args.output_dir,
        seed=args.seed,
        val_pct=args.val_pct,
        test_pct=args.test_pct,
    )
    print(f"SWE-bench splits prepared successfully: train={counts.get('train', 0)}, validation={counts.get('validation', 0)}, test={counts.get('test', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

