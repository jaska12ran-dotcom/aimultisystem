"""Download and prepare SWE-bench/SWE-bench_Verified for CodeTwin training."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

if __package__:
    from .load_swebench_dataset import main as download_swebench
    from .prepare_swebench_data import main as prepare_swebench
else:
    from load_swebench_dataset import main as download_swebench
    from prepare_swebench_data import main as prepare_swebench

DEFAULT_OUTPUT = Path(__file__).parent / "datasets" / "processed" / "swebench"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="SWE-bench/SWE-bench_Verified", help="Hugging Face dataset name")
    parser.add_argument("--split", default="test", help="Dataset split (default: test)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of instances")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT, help="Directory for processed splits")
    parser.add_argument("--seed", type=int, default=42, help="Seed for repository isolation")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="codetwin-swebench-") as temp_dir:
        raw_output = Path(temp_dir) / "swebench_raw.jsonl"
        download_args = ["--dataset", args.dataset, "--split", args.split, "--output", str(raw_output)]
        if args.limit:
            download_args.extend(["--limit", str(args.limit)])

        print(f"1. Downloading instances from {args.dataset}...")
        if download_swebench(download_args) != 0:
            return 1

        print("2. Formatting records and generating repository-isolated splits...")
        prep_args = [
            "--input",
            str(raw_output),
            "--output-dir",
            str(args.output_dir),
            "--seed",
            str(args.seed),
        ]
        return prepare_swebench(prep_args)


if __name__ == "__main__":
    raise SystemExit(main())

