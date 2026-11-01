# Normalized runner input

Benchmark-specific acquisition and execution remain in their upstream tools.
Adapters must produce UTF-8 JSONL in these formats; do not commit upstream
benchmark datasets or repository snapshots here.

## Labeled examples

Every example requires `example_id`, `repository_id`, and `task`. `repository_id`
must use the same stable identity as the training-repository manifest (for
example, the canonical upstream owner/name); this lets the runner reject any
repository overlap with training.

Optional gold fields:

```json
{
  "expected_answer": "gold response",
  "expected_evidence": ["src/module.py:function"],
  "available_evidence": ["src/module.py:function", "README.md"],
  "expected_impacted_files": ["src/caller.py"],
  "expected_security_findings": ["CWE-89"],
  "task": "rag_answer"
}
```

Tasks recognized for stratified metrics: `repository_understanding`,
`repository_architecture`, `rag_answer`, `codebase_qa`, `documentation`,
`code_to_documentation`, `documentation_verification`, `test_generation`,
`code_to_test`, `change_impact`, `security`, and
`security_evidence_extraction`. Other task names remain in per-task report
counts.

## Predictions and measured outcomes

Each prediction has `example_id` matching exactly one example. Supply applicable
fields such as:

```json
{
  "example_id": "case-001",
  "answer": "model response",
  "evidence": ["src/module.py:function"],
  "unsupported_claim_count": 1,
  "claim_count": 4,
  "test_passed": true,
  "coverage_before": 42.0,
  "coverage_after": 48.5,
  "mutants_killed": 7,
  "mutants_total": 10,
  "security_findings": ["CWE-89"],
  "impacted_files": ["src/caller.py"],
  "task_success": true
}
```

`unsupported_claim_count` and `claim_count` should be produced by an independent
reviewer or calibrated verifier; the runner does not treat the model's
self-assessment as evidence. If they are omitted, `available_evidence` permits
a citation-only hallucination proxy. Coverage values are percentages and
report improvement in percentage points. Test and mutation outcomes must come
from a sandbox/upstream harness, not model assertions. Missing measurements are
reported as `null` rather than as zero.

## Training repository manifest

Pass `--training-repositories` as JSONL records with `repository_id`, a JSON
string array, an object with a `repositories` array, or a text file with one ID
per line. Include every repository used in model fine-tuning, including
repository-level deduplication aliases. Evaluation stops if any repository ID
appears in both manifests.
