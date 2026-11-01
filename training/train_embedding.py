"""
Train a code-search embedding model on CodeSearchNet.
------------------------------------------------------
Uses sentence-transformers with MultipleNegativesRankingLoss (MNR) —
the standard contrastive approach for (query, code) retrieval tasks.

Architecture
  Base model : microsoft/unixcoder-base  (or any ST-compatible model)
  Loss        : MultipleNegativesRankingLoss
                Each batch contains (query_i, code_i) pairs; for every pair,
                all other codes in the batch act as in-batch negatives.
  Output      : a sentence-transformers model saved to --output-dir

Why MNR?
  The CodeSearchNet dataset only has positive (docstring, code) pairs — no
  hard negatives. MNR efficiently mines in-batch negatives, which is exactly
  what this structure supports, and achieves strong MRR on code-search benchmarks
  without needing explicit negative examples.

Usage (CPU, quick smoke-test):
  python training/train_embedding.py \
      --data-dir training/datasets/codesearchnet \
      --output-dir training/output/embedding_model \
      --epochs 1 --batch-size 32 --limit 20000

Usage (GPU, full training):
  python training/train_embedding.py \
      --data-dir training/datasets/codesearchnet \
      --output-dir training/output/embedding_model \
      --epochs 3 --batch-size 128

The saved model is a standard sentence-transformers directory that can be
loaded with SentenceTransformer("training/output/embedding_model").
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from pathlib import Path

LOGGER = logging.getLogger("codetwin.train_embedding")


# ── Data loading ───────────────────────────────────────────────────────────────

def _read_pairs(
    data_dir: Path,
    split: str,
    limit: int | None,
    seed: int,
) -> list[tuple[str, str]]:
    """Return (query, code) pairs from a JSONL split file."""
    path = data_dir / f"{split}.jsonl"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — run prepare_codesearchnet.py first"
        )

    pairs: list[tuple[str, str]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            query = (row.get("query") or "").strip()
            code = (row.get("code") or "").strip()
            if query and code:
                pairs.append((query, code))

    random.Random(seed).shuffle(pairs)
    if limit is not None:
        pairs = pairs[:limit]
    return pairs


# ── Training ───────────────────────────────────────────────────────────────────

def train(args: argparse.Namespace) -> int:
    try:
        from sentence_transformers import InputExample, SentenceTransformer, losses
        from sentence_transformers.evaluation import InformationRetrievalEvaluator
        from torch.utils.data import DataLoader
    except ImportError as exc:
        LOGGER.error(
            "Missing dependency: %s — install training/requirements_embedding.txt", exc
        )
        return 1

    # ── Load data ─────────────────────────────────────────────────────────────
    LOGGER.info("Loading training pairs …")
    try:
        train_pairs = _read_pairs(args.data_dir, "train", args.limit, args.seed)
        val_pairs = _read_pairs(
            args.data_dir,
            "validation",
            min(args.limit, 5000) if args.limit else 5000,
            args.seed,
        )
    except FileNotFoundError as exc:
        LOGGER.error(str(exc))
        return 1

    if len(train_pairs) < 2:
        LOGGER.error("Need at least 2 training pairs; found %d", len(train_pairs))
        return 1
    if len(train_pairs) < args.batch_size:
        LOGGER.error(
            "Need at least one full training batch of %d pairs; found %d",
            args.batch_size,
            len(train_pairs),
        )
        return 1
    if not val_pairs:
        LOGGER.error("Validation split contains no usable query/code pairs")
        return 1

    LOGGER.info(
        "Training pairs: %d | Validation pairs: %d", len(train_pairs), len(val_pairs)
    )

    # ── Model ─────────────────────────────────────────────────────────────────
    LOGGER.info("Loading base model: %s", args.base_model)
    model = SentenceTransformer(args.base_model)

    # ── Dataset ───────────────────────────────────────────────────────────────
    train_examples = [
        InputExample(texts=[query, code]) for query, code in train_pairs
    ]
    train_dataloader = DataLoader(
        train_examples,
        shuffle=True,
        batch_size=args.batch_size,
        drop_last=True,          # MNR requires uniform batch sizes
        num_workers=4,
        prefetch_factor=2,
    )

    # ── Loss ──────────────────────────────────────────────────────────────────
    # MultipleNegativesRankingLoss: for each (query_i, code_i) pair, treats
    # all other code_j in the batch as negatives. This is the correct loss for
    # datasets that only contain positive pairs.
    train_loss = losses.MultipleNegativesRankingLoss(model=model)

    # ── Evaluator ─────────────────────────────────────────────────────────────
    # Build an IR evaluator: queries → relevant docs mapping.
    # We use the validation pairs as queries+corpus.
    queries: dict[str, str] = {}
    corpus: dict[str, str] = {}
    relevant: dict[str, set[str]] = {}

    for idx, (query, code) in enumerate(val_pairs):
        qid = f"q{idx}"
        cid = f"c{idx}"
        queries[qid] = query
        corpus[cid] = code
        relevant[qid] = {cid}

    evaluator = InformationRetrievalEvaluator(
        queries=queries,
        corpus=corpus,
        relevant_docs=relevant,
        name="codesearchnet_val",
        show_progress_bar=False,
        batch_size=args.batch_size,
        score_functions={"cos_sim": losses.util.cos_sim},
        precision_recall_at_k=[1, 5, 10],
        accuracy_at_k=[1, 5, 10],
        mrr_at_k=[10],
    )

    # ── Training schedule ─────────────────────────────────────────────────────
    steps_per_epoch = len(train_examples) // args.batch_size
    warmup_steps = max(1, int(steps_per_epoch * args.warmup_ratio))
    total_steps = int(steps_per_epoch * args.epochs)

    LOGGER.info(
        "Training for %d epochs | %d steps/epoch | %d warmup steps | "
        "batch=%d | lr=%.2e",
        args.epochs, steps_per_epoch, warmup_steps, args.batch_size, args.learning_rate,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    model.fit(
        train_objectives=[(train_dataloader, train_loss)],
        evaluator=evaluator,
        epochs=args.epochs,
        warmup_steps=warmup_steps,
        evaluation_steps=max(1, steps_per_epoch // 2),  # evaluate twice per epoch
        output_path=str(args.output_dir),
        save_best_model=True,
        optimizer_params={"lr": args.learning_rate},
        show_progress_bar=True,
        checkpoint_path=str(args.output_dir / "checkpoints"),
        checkpoint_save_steps=max(1, steps_per_epoch),
        checkpoint_save_total_limit=2,
    )

    # ── Save metadata ─────────────────────────────────────────────────────────
    meta = {
        "base_model": args.base_model,
        "training_pairs": len(train_pairs),
        "validation_pairs": len(val_pairs),
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "loss": "MultipleNegativesRankingLoss",
        "dataset": "sentence-transformers/codesearchnet",
        "languages": "all6",
        "output_dir": str(args.output_dir),
    }
    (args.output_dir / "training_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False)
    )

    LOGGER.info("Model saved to %s", args.output_dir)
    return 0


# ── CLI ────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).parent / "datasets" / "codesearchnet",
        help="Directory containing train/validation/test JSONL files",
    )
    parser.add_argument(
        "--base-model",
        default="microsoft/unixcoder-base",
        help=(
            "sentence-transformers-compatible base model. "
            "Good choices: microsoft/unixcoder-base, "
            "sentence-transformers/all-MiniLM-L6-v2 (smaller/faster), "
            "Salesforce/codet5p-110m-embedding (code-optimised)"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent / "output" / "embedding_model",
        help="Where to save the trained sentence-transformers model",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=3,
        help="Number of training epochs (default: 3)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help=(
            "Per-device batch size. Larger batches = more in-batch negatives = "
            "better MNR training. Use 64-256 on GPU, 16-32 on CPU."
        ),
    )
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=2e-5,
        help="Peak learning rate for AdamW (default: 2e-5)",
    )
    parser.add_argument(
        "--warmup-ratio",
        type=float,
        default=0.1,
        help="Fraction of steps to use for linear warmup (default: 0.1)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20000,
        help="Cap training examples at this many rows (for smoke tests; use None for full dataset)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for shuffling",
    )
    args = parser.parse_args(argv)

    if args.epochs <= 0 or args.batch_size <= 0 or args.learning_rate <= 0:
        parser.error("epochs, batch-size, and learning-rate must be positive")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return train(args)


if __name__ == "__main__":
    sys.exit(main())
