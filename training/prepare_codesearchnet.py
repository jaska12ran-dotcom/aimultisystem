"""Download and prepare a CodeSearchNet sample for embedding-model training."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

if __package__:
    from .load_hf_dataset import main as download_sample
    from .prepare_embedding_data import main as prepare_sample
else:
    from load_hf_dataset import main as download_sample
    from prepare_embedding_data import main as prepare_sample

DEFAULT_OUTPUT = Path(__file__).parent / "datasets" / "codesearchnet"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=100000,
        help="Number of unique valid pairs to download (default: 100000)",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validation-fraction", type=float, default=0.1)
    parser.add_argument("--test-fraction", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    if args.limit <= 0:
        parser.error("--limit must be positive")
    if (
        args.validation_fraction <= 0
        or args.test_fraction <= 0
        or args.validation_fraction + args.test_fraction >= 1
    ):
        parser.error("validation/test fractions must be positive and sum to less than one")

    with tempfile.TemporaryDirectory(prefix="codetwin-codesearchnet-") as temporary_dir:
        raw_output = Path(temporary_dir) / "pairs.jsonl"
        if download_sample(["--limit", str(args.limit), "--output", str(raw_output)]):
            return 1
        return prepare_sample(
            [
                "--input",
                str(raw_output),
                "--output-dir",
                str(args.output_dir),
                "--validation-fraction",
                str(args.validation_fraction),
                "--test-fraction",
                str(args.test_fraction),
                "--seed",
                str(args.seed),
            ]
        )


if __name__ == "__main__":
    raise SystemExit(main())
