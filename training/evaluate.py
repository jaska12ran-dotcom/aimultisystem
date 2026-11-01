"""Generate held-out predictions and calculate CodeTwin evaluation metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from data_utils import build_prompt, read_jsonl, write_jsonl
from validate_data import validate_records


DOC_TASKS = {"code_to_documentation", "documentation_verification"}
QA_TASKS = {"codebase_qa"}
IMPACT_TASKS = {"change_impact"}
SECURITY_TASKS = {"security_evidence_extraction"}
TEST_TASKS = {"code_to_test"}


def normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def parse_prediction(text: str) -> tuple[dict[str, Any], bool]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {"answer": text.strip(), "evidence": [], "findings": [], "impacted_files": []}, False
    try:
        result = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {"answer": text.strip(), "evidence": [], "findings": [], "impacted_files": []}, False
    if not isinstance(result, dict) or not isinstance(result.get("answer"), str):
        return {"answer": text.strip(), "evidence": [], "findings": [], "impacted_files": []}, False
    for key in ("evidence", "findings", "impacted_files"):
        if not isinstance(result.get(key, []), list):
            result[key] = []
    return result, True


def f1_counts(expected: set[str], actual: set[str]) -> tuple[int, int, int]:
    return len(expected & actual), len(actual - expected), len(expected - actual)


def evaluate_predictions(
    references: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    execution_results: dict[str, bool] | None = None,
) -> dict[str, Any]:
    prediction_by_id = {row["example_id"]: row for row in predictions}
    metrics: dict[str, Any] = {
        "examples": len(references),
        "malformed_output_count": 0,
        "documentation_factual_accuracy": {"correct": 0, "total": 0},
        "evidence_accuracy": {"true_positive": 0, "false_positive": 0, "false_negative": 0},
        "hallucination_rate": {"unsupported_citations": 0, "citations": 0},
        "code_question_accuracy": {"correct": 0, "total": 0},
        "change_impact_accuracy": {"correct": 0, "total": 0},
        "security_false_positive_rate": {"false_positives": 0, "true_negatives": 0},
        "test_pass_rate": {"passed": 0, "total": 0},
    }

    for reference in references:
        prediction = prediction_by_id.get(reference["example_id"])
        if prediction is None:
            continue
        output = prediction["parsed"]
        if not prediction["valid_json"]:
            metrics["malformed_output_count"] += 1

        expected_evidence = set(reference["evidence"])
        available_evidence = expected_evidence
        actual_evidence = {
            item for item in output.get("evidence", []) if isinstance(item, str)
        }
        tp, fp, fn = f1_counts(expected_evidence, actual_evidence)
        evidence_metric = metrics["evidence_accuracy"]
        evidence_metric["true_positive"] += tp
        evidence_metric["false_positive"] += fp
        evidence_metric["false_negative"] += fn
        metrics["hallucination_rate"]["unsupported_citations"] += len(
            actual_evidence - available_evidence
        )
        metrics["hallucination_rate"]["citations"] += len(actual_evidence)

        expected_answer = normalize(reference["expected_output"])
        actual_answer = normalize(output.get("answer", ""))
        if reference["task"] in DOC_TASKS:
            metric = metrics["documentation_factual_accuracy"]
            metric["total"] += 1
            metric["correct"] += actual_answer == expected_answer
        if reference["task"] in QA_TASKS:
            metric = metrics["code_question_accuracy"]
            metric["total"] += 1
            metric["correct"] += actual_answer == expected_answer
        if reference["task"] in IMPACT_TASKS:
            metric = metrics["change_impact_accuracy"]
            metric["total"] += 1
            expected_files = reference.get("expected_impacted_files")
            if expected_files is not None:
                correct = set(output.get("impacted_files", [])) == set(expected_files)
            else:
                correct = actual_answer == expected_answer
            metric["correct"] += correct
        if reference["task"] in SECURITY_TASKS and "expected_findings" in reference:
            expected_findings = set(reference["expected_findings"])
            actual_findings = {
                item for item in output.get("findings", []) if isinstance(item, str)
            }
            if not expected_findings:
                metric = metrics["security_false_positive_rate"]
                metric["false_positives"] += bool(actual_findings)
                metric["true_negatives"] += not actual_findings
        if reference["task"] in TEST_TASKS and execution_results is not None:
            example_id = reference["example_id"]
            if example_id in execution_results:
                metrics["test_pass_rate"]["passed"] += execution_results[example_id]
                metrics["test_pass_rate"]["total"] += 1

    def ratio(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    for name in (
        "documentation_factual_accuracy",
        "code_question_accuracy",
        "change_impact_accuracy",
    ):
        entry = metrics[name]
        entry["rate"] = ratio(entry["correct"], entry["total"])
    evidence = metrics["evidence_accuracy"]
    precision = ratio(evidence["true_positive"], evidence["true_positive"] + evidence["false_positive"])
    recall = ratio(evidence["true_positive"], evidence["true_positive"] + evidence["false_negative"])
    evidence["precision"] = precision
    evidence["recall"] = recall
    evidence["f1"] = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    hallucinations = metrics["hallucination_rate"]
    hallucinations["rate"] = ratio(
        hallucinations["unsupported_citations"], hallucinations["citations"]
    )
    test_pass = metrics["test_pass_rate"]
    test_pass["rate"] = ratio(test_pass["passed"], test_pass["total"])
    security = metrics["security_false_positive_rate"]
    security["rate"] = ratio(security["false_positives"], security["false_positives"] + security["true_negatives"])
    return metrics


def load_execution_results(path: Path | None) -> dict[str, bool] | None:
    if path is None:
        return None
    rows = read_jsonl(path)
    result: dict[str, bool] = {}
    for row in rows:
        example_id = row.get("example_id")
        passed = row.get("test_passed")
        if not isinstance(example_id, str) or not isinstance(passed, bool):
            raise ValueError(f"{path}: each execution result needs example_id and boolean test_passed")
        if example_id in result:
            raise ValueError(f"{path}: duplicate execution result for {example_id!r}")
        result[example_id] = passed
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).parent / "datasets" / "processed" / "test.jsonl",
        help="Held-out test split JSONL",
    )
    parser.add_argument(
        "--adapter",
        type=Path,
        required=True,
        help="Saved PEFT adapter directory produced by train_lora.py",
    )
    parser.add_argument(
        "--base-model",
        default="Qwen/Qwen2.5-Coder-1.5B-Instruct",
        help="The same existing pretrained model used during training",
    )
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "results")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument(
        "--execution-results",
        type=Path,
        help="JSONL from an isolated test runner: {example_id, test_passed}",
    )
    args = parser.parse_args()
    if args.max_new_tokens <= 0:
        parser.error("max-new-tokens must be positive")

    try:
        references = read_jsonl(args.dataset)
        errors = validate_records(references, args.dataset, require_both_labels=False)
        execution_results = load_execution_results(args.execution_results)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    if execution_results is not None:
        known_test_ids = {
            row["example_id"] for row in references if row["task"] in TEST_TASKS
        }
        unknown_ids = set(execution_results) - known_test_ids
        if unknown_ids:
            print(
                "ERROR: execution results contain unknown or non-test example IDs: "
                + ", ".join(sorted(unknown_ids))
            )
            return 1
    if not args.adapter.is_dir():
        print(f"ERROR: adapter directory does not exist: {args.adapter}")
        return 1

    try:
        import torch
        from peft import AutoPeftModelForCausalLM
        from transformers import AutoTokenizer
    except ImportError as exc:
        print(f"ERROR: missing evaluation dependency {exc.name!r}; install training/requirements.txt")
        return 1

    tokenizer = AutoTokenizer.from_pretrained(args.base_model, use_fast=True)
    model = AutoPeftModelForCausalLM.from_pretrained(
        args.adapter,
        torch_dtype="auto",
        device_map="auto",
    )
    model.eval()
    predictions: list[dict[str, Any]] = []
    for record in references:
        prompt = build_prompt(record) + "\n\n### Response\n"
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=4096)
        inputs = {key: value.to(model.device) for key, value in inputs.items()}
        with torch.inference_mode():
            generated = model.generate(
                **inputs,
                max_new_tokens=args.max_new_tokens,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )
        continuation = generated[0, inputs["input_ids"].shape[1] :]
        text = tokenizer.decode(continuation, skip_special_tokens=True)
        parsed, valid_json = parse_prediction(text)
        predictions.append(
            {
                "example_id": record["example_id"],
                "task": record["task"],
                "prediction": text,
                "parsed": parsed,
                "valid_json": valid_json,
            }
        )

    metrics = evaluate_predictions(references, predictions, execution_results)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    serializable_predictions = [
        {key: value for key, value in prediction.items() if key != "valid_json"}
        | {"valid_json": prediction["valid_json"]}
        for prediction in predictions
    ]
    write_jsonl(args.output_dir / "predictions.jsonl", serializable_predictions)
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metrics, indent=2))
    print(f"Predictions and metrics saved to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
