---
name: evaluation
description: "Prepare and run CodeTwin evaluations on held-out repositories, use licensed benchmarks responsibly, calculate metrics, and produce machine-readable reports."
---
# CodeTwin evaluation

1. Read `evaluations/README.md` and `evaluations/runners/FORMAT.md`. Confirm
   model, benchmark, dataset split, and harness versions.
2. Verify evaluation repository IDs are disjoint from the complete training
   repository manifest. Use repository-level identity, not a random row split.
3. Review benchmark terms and every underlying repository license before
   acquiring or executing data. Do not copy restricted benchmark contents
   into this product.
4. Run external benchmark tools and generated code in isolated environments;
   collect tests, coverage, and mutation outcomes from actual runners.
5. Create normalized, labeled JSONL records and matching predictions/outcomes.
   Keep held-out answers out of training and model selection.
6. Run `python evaluations/runners/run_eval.py --help`, then invoke the runner
   with an explicit license-review note and training-repository manifest.
7. Inspect the generated JSON report, denominators, null metrics, hashes,
   per-example results, and potential label leakage before sharing conclusions.
8. Report exact commands and limitations. Distinguish citation-only
   hallucination proxies from independently reviewed unsupported claims.

Never fabricate scores, license approval, data provenance, or execution results.
