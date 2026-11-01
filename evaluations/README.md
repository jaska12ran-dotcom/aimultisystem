# CodeTwin evaluation framework

This framework evaluates CodeTwin on held-out repositories and writes
machine-readable JSON reports. Benchmark inputs and execution are intentionally
not bundled: benchmark owners' terms, source repository licenses, and instance
licenses can differ. The registry links upstream sources and flags every entry
for review. No benchmark dataset is downloaded or copied into this product.

## Included

- `benchmarks/catalog.json`: registry for SWE-bench, SWE-bench Lite,
  CodeSearchNet, CodeXGLUE, Defects4J, BugsInPy, and QuixBugs. This is a source
  and task catalog, not a dataset mirror or a representation that legal review
  has passed.
- `runners/run_eval.py`: validates normalized records and model predictions,
  checks repository disjointness against a training manifest, calculates
  metrics, and writes a provenance-bearing JSON report.
- `runners/FORMAT.md`: input/output contract for benchmark-specific adapters.
- `metrics/core.py`: deterministic metric implementation.
- `reports/`: default report destination.

The pipeline is model-agnostic. Run the appropriate upstream benchmark harness
and CodeTwin integration in a disposable/isolated environment, convert only
permitted labels and outcomes to the documented JSONL contract, then run the
reporter. Test execution, coverage instrumentation, mutation testing, and
benchmark-specific patch acceptance must be measured by the respective
upstream or sandbox tools, not inferred from generated text.

## Licensing and benchmark use

Before acquiring or evaluating a benchmark:

1. Read the current benchmark dataset license/terms and cite the version or
   access route used.
2. Review licenses and terms for every underlying repository, code sample,
   patch, and dependency in the selected subset. Dataset permission does not
   automatically license repository contents.
3. Use the upstream release and official evaluation/split procedure. Observe
   access restrictions, attribution, non-commercial terms, retention rules, and
   redistribution limits where applicable.
4. Do not commit downloaded data, repository checkouts, issue text, patches, or
   benchmark answers to this project unless their exact terms permit it.
5. Pass `--license-reviewed` and a concise `--license-note` only after completing
   this review. These flags record an operator attestation; they are not legal
   advice or an automatic license clearance.

The registry deliberately says `license_review: required`: licenses can change,
aggregated benchmarks may contain differently licensed subdatasets, and the
framework cannot establish whether a particular deployment's use is permitted.
If permission is unclear, do not use that data.

## Held-out repositories

Maintain a complete manifest of repositories used for model training. Include
canonical upstream IDs and known aliases; do not rely only on individual
example IDs or a random record split. The evaluator requires the manifest and
fails if an evaluation `repository_id` overlaps it. Repository IDs should be
stable canonical names, preferably `owner/repository`. Also keep evaluation
instances and labels out of training and model selection.

This checks separation from the recorded CodeTwin fine-tuning repositories; it
cannot establish whether an upstream pretrained base model saw those
repositories during its original pretraining.

Training manifest formats are documented in `runners/FORMAT.md`. For the
existing LoRA data, the generated training split can be supplied as JSONL:

```powershell
python evaluations\runners\run_eval.py `
  --benchmark codesearchnet `
  --dataset C:\eval-data\codesearchnet-test.jsonl `
  --predictions C:\eval-results\codesearchnet-predictions.jsonl `
  --training-repositories training\datasets\processed\train.jsonl `
  --model codetwin-lora:2026-10-10 `
  --license-reviewed `
  --license-note "Reviewed upstream terms and source repository licenses for this exact test subset."
```

The paths above for external data/results are examples only; the files are not
included. Benchmark-specific adapters should preserve upstream split IDs and
record code revision, instance IDs, harness version, and execution environment
alongside their normalized inputs/outcomes. The current runner records input
file hashes and model identifier; pass `--dataset-version`,
`--harness-version`, and `--code-revision` to record the corresponding
benchmark, evaluator, and CodeTwin revisions.

## Input data and outcomes

Each labeled JSONL row requires `example_id`, `repository_id`, and `task`.
Provide the applicable expected labels such as `expected_answer`,
`expected_evidence`, `available_evidence`, `expected_impacted_files`, and
`expected_security_findings`. A prediction row is keyed by `example_id` and may
include the generated `answer`, `evidence`, `impacted_files`,
`security_findings`, and independently measured outcomes. Exact fields and
semantics are in `runners/FORMAT.md`.

Use an independent review or calibrated verifier for unsupported-claim
annotations. If only evidence references are available, the reported
hallucination metric is explicitly a citation-only proxy. Do not use model
self-reports for test pass, coverage, mutation, or task success. Run generated
code and upstream harnesses with resource/network boundaries appropriate to
untrusted code.

## Metrics

Metrics are deterministic and each is accompanied by counts/denominators where
meaningful. Unavailable measurements are `null`, never silently treated as
zero.

| Metric | Computation |
| --- | --- |
| Repository understanding accuracy | Exact normalized answer match and mean token F1 for repository understanding/architecture tasks |
| RAG answer accuracy | Exact normalized answer match and mean token F1 for RAG/codebase-QA tasks |
| Evidence accuracy | Micro precision, recall, and F1 between expected and emitted evidence references |
| Documentation correctness | Exact normalized match and mean token F1 against gold documentation/verification answers |
| Test pass rate | Passed generated-test runs divided by test cases with measured `test_passed` results |
| Coverage improvement | Mean `coverage_after - coverage_before` in percentage points |
| Mutation score | Total killed mutants divided by total mutants |
| Security precision | True-positive findings divided by emitted findings; false-positive rate is also reported when negative security labels exist |
| Change-impact precision/recall | Micro precision and recall between expected and predicted impacted-file sets |
| Hallucination rate | Independently labeled unsupported claims divided by assessed claims; otherwise citation-only unsupported/total ratio when available evidence is supplied |
| Agent task success rate | Successful tasks divided by tasks with a measured boolean `task_success` |

Exact answer match is intentionally strict; token F1 is a supplementary lexical
score, not semantic equivalence. Security finding IDs should use a consistent
taxonomy such as CWE identifiers. For fair comparisons, keep benchmark
versions, prompts, model settings, harnesses, resource limits, and label policy
fixed and record them with each run.

## Example local smoke run

No external benchmark data or model is needed to test metric/report generation.
Create permitted local JSONL fixtures following the format guide, plus a
training-repository manifest that is disjoint from them, and execute the
command above with an appropriate registered benchmark key. For fast
validation, the metrics module can also be imported directly:

```powershell
python -c "import sys; sys.path.insert(0, 'evaluations'); from metrics.core import calculate_metrics; print(calculate_metrics([], []))"
```

The runner rejects malformed JSONL, duplicate or unmatched IDs, empty training
manifests, and repository leakage. Reports include schema version, report ID,
UTC creation time, benchmark/model identifiers, license-review note, dataset
and prediction hashes, repository counts, aggregate metrics, and per-example
measurement details.
