"""
Evaluate a trained code-search embedding model on CodeSearchNet test set.
--------------------------------------------------------------------------
Reports per-language and aggregate:
  - MRR@10   (Mean Reciprocal Rank)
  - Recall@1 / @5 / @10
  - NDCG@10

Compares against the baseline deterministic hash embedder used before training.

Usage:
  python training/evaluate_embedding.py \
      --model training/output/embedding_model \
      --data-dir training/datasets/codesearchnet \
      [--limit 1000]        # rows per language (default: all)
      [--batch-size 64]
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("codetwin.evaluate_embedding")

LANGUAGES = ("python", "java", "javascript", "go", "php", "ruby", "mixed")


# ── Baseline embedder (same as current EmbeddingService) ──────────────────────

class HashEmbedder:
    """Deterministic hash-based embedder — current production baseline."""

    DIMENSION = 384

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        import re
        return [t.lower() for t in re.findall(r"[A-Za-z0-9_]+", text or "") if t]

    @classmethod
    def embed(cls, texts: list[str]) -> list[list[float]]:
        import hashlib, math as _math
        results = []
        for text in texts:
            tokens = cls._tokenize(text)
            if not tokens:
                results.append([0.0] * cls.DIMENSION)
                continue
            vector = [0.0] * cls.DIMENSION
            for idx, token in enumerate(tokens):
                digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
                value = int(digest[:12], 16) / float(0xFFFFFFFFFFFF)
                vector[idx % cls.DIMENSION] += value
            norm = _math.sqrt(sum(v * v for v in vector))
            if norm == 0:
                results.append([0.0] * cls.DIMENSION)
            else:
                results.append([v / norm for v in vector])
        return results


# ── Metrics ────────────────────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-10)


def _retrieval_metrics(
    query_embeds: list[list[float]],
    code_embeds: list[list[float]],
    k_values: tuple[int, ...] = (1, 5, 10),
) -> dict[str, float]:
    """
    For each query i the correct code is at index i.
    Compute MRR and Recall@k over the full corpus.
    """
    n = len(query_embeds)
    mrr_sum = 0.0
    recall = {k: 0 for k in k_values}
    ndcg_sum = 0.0

    for i, qe in enumerate(query_embeds):
        scores = [(j, _cosine(qe, ce)) for j, ce in enumerate(code_embeds)]
        scores.sort(key=lambda x: x[1], reverse=True)
        ranked_ids = [j for j, _ in scores]

        rank = ranked_ids.index(i) + 1  # 1-indexed
        mrr_sum += 1.0 / rank

        # NDCG@10 (binary relevance)
        dcg = 0.0
        for pos, doc_id in enumerate(ranked_ids[:10], start=1):
            if doc_id == i:
                dcg += 1.0 / math.log2(pos + 1)
        ndcg_sum += dcg  # ideal DCG = 1/log2(2)=1.0

        for k in k_values:
            if i in ranked_ids[:k]:
                recall[k] += 1

    return {
        "mrr@10": round(mrr_sum / n, 4),
        **{f"recall@{k}": round(recall[k] / n, 4) for k in k_values},
        "ndcg@10": round(ndcg_sum / n, 4),
        "n_queries": n,
    }


# ── Evaluation loop ────────────────────────────────────────────────────────────

def evaluate(args: argparse.Namespace) -> int:
    # ── Load trained model ────────────────────────────────────────────────────
    model = None
    if args.model:
        model_path = Path(args.model)
        if not model_path.exists():
            LOGGER.error("Model path does not exist: %s", model_path)
            return 1
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(str(model_path))
            LOGGER.info("Loaded trained model from %s", model_path)
        except ImportError:
            LOGGER.error("sentence-transformers not installed")
            return 1

    baseline = HashEmbedder()
    results: dict[str, dict[str, Any]] = {}
    test_path = args.data_dir / "test.jsonl"
    if not test_path.exists():
        LOGGER.error("No test.jsonl found in %s", args.data_dir)
        return 1

    rows: list[dict[str, Any]] = []
    with test_path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                rows.append(json.loads(line))
    languages = args.languages or sorted(
        {row.get("language", "mixed") for row in rows}
    )

    for lang in languages:
        pairs: list[tuple[str, str]] = []
        for row in rows:
            if row.get("language", "mixed") == lang:
                q = (row.get("query") or "").strip()
                c = (row.get("code") or "").strip()
                if q and c:
                    pairs.append((q, c))
            if args.limit and len(pairs) >= args.limit:
                break

        if not pairs:
            LOGGER.warning("No %s examples in test set", lang)
            continue

        LOGGER.info(
            "Evaluating %s: %d pairs …", lang, len(pairs)
        )
        queries = [p[0] for p in pairs]
        codes = [p[1] for p in pairs]

        # Baseline
        bq = baseline.embed(queries)
        bc = baseline.embed(codes)
        base_metrics = _retrieval_metrics(bq, bc)

        row_result: dict[str, Any] = {"baseline": base_metrics}

        # Trained model
        if model is not None:
            tq = model.encode(
                queries,
                batch_size=args.batch_size,
                show_progress_bar=False,
                normalize_embeddings=True,
            ).tolist()
            tc = model.encode(
                codes,
                batch_size=args.batch_size,
                show_progress_bar=False,
                normalize_embeddings=True,
            ).tolist()
            trained_metrics = _retrieval_metrics(tq, tc)
            row_result["trained"] = trained_metrics

            improvement = {
                k: round(trained_metrics.get(k, 0) - base_metrics.get(k, 0), 4)
                for k in trained_metrics
                if k != "n_queries"
            }
            row_result["improvement"] = improvement
            LOGGER.info(
                "  %s — MRR@10: baseline=%.4f trained=%.4f Δ=%.4f",
                lang,
                base_metrics["mrr@10"],
                trained_metrics["mrr@10"],
                improvement["mrr@10"],
            )
        else:
            LOGGER.info(
                "  %s — MRR@10: baseline=%.4f (no trained model provided)",
                lang, base_metrics["mrr@10"],
            )

        results[lang] = row_result

    # ── Aggregate ─────────────────────────────────────────────────────────────
    if results:
        agg_keys = ["mrr@10", "recall@1", "recall@5", "recall@10", "ndcg@10"]
        agg: dict[str, dict[str, float]] = {"baseline": {}, "trained": {}}
        for key in agg_keys:
            for variant in ("baseline", "trained"):
                vals = [
                    results[lang][variant][key]
                    for lang in results
                    if variant in results[lang] and key in results[lang][variant]
                ]
                if vals:
                    agg[variant][key] = round(sum(vals) / len(vals), 4)

        results["_aggregate"] = {
            k: v for k, v in agg.items() if v
        }

        LOGGER.info("\n=== Aggregate metrics (macro avg across languages) ===")
        for variant, metrics in results["_aggregate"].items():
            LOGGER.info(
                "  %s: %s",
                variant,
                "  ".join(f"{k}={v:.4f}" for k, v in metrics.items()),
            )

    # ── Write report ───────────────────────────────────────────────────────────
    report_path = args.output_dir / "evaluation_report.json"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    LOGGER.info("Evaluation report written to %s", report_path)

    return 0


# ── CLI ────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Path to a trained sentence-transformers model directory",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).parent / "datasets" / "codesearchnet",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent / "output",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Evaluate on at most this many pairs per language",
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        choices=list(LANGUAGES),
        default=None,
        help="Languages to evaluate; defaults to language labels found in test.jsonl",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return evaluate(args)


if __name__ == "__main__":
    sys.exit(main())
