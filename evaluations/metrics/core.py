"""Deterministic, label-based CodeTwin metrics."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


REPOSITORY_TASKS = {"repository_understanding", "repository_architecture"}
RAG_TASKS = {"rag_answer", "codebase_qa"}
DOCUMENTATION_TASKS = {"documentation", "code_to_documentation", "documentation_verification"}
TEST_TASKS = {"test_generation", "code_to_test"}
IMPACT_TASKS = {"change_impact"}
SECURITY_TASKS = {"security", "security_evidence_extraction"}


def normalize(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold(), flags=re.UNICODE))


def answer_score(expected: str, actual: str) -> float:
    expected_tokens = normalize(expected).split()
    actual_tokens = normalize(actual).split()
    if not expected_tokens or not actual_tokens:
        return float(expected_tokens == actual_tokens)
    expected_counts: dict[str, int] = defaultdict(int)
    actual_counts: dict[str, int] = defaultdict(int)
    for token in expected_tokens:
        expected_counts[token] += 1
    for token in actual_tokens:
        actual_counts[token] += 1
    overlap = sum(min(count, actual_counts[token]) for token, count in expected_counts.items())
    precision = overlap / len(actual_tokens)
    recall = overlap / len(expected_tokens)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def counts_metric(tp: int, fp: int, fn: int) -> dict[str, Any]:
    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _set(value: Any, *, field: str, example_id: str) -> set[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{example_id}: {field} must be an array of strings")
    return set(value)


def _answer_metrics(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    correct = 0
    scores = []
    for example, prediction in pairs:
        expected = example.get("expected_answer")
        actual = prediction.get("answer")
        if not isinstance(expected, str) or not isinstance(actual, str):
            raise ValueError(f"{example['example_id']}: expected_answer and answer must be strings")
        score = answer_score(expected, actual)
        scores.append(score)
        correct += normalize(expected) == normalize(actual)
    return {
        "exact_match_count": correct,
        "total": len(pairs),
        "exact_match_accuracy": ratio(correct, len(pairs)),
        "mean_token_f1": ratio(sum(scores), len(scores)),
    }


def calculate_metrics(
    examples: list[dict[str, Any]], predictions: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    prediction_by_id = {row["example_id"]: row for row in predictions}
    pairs = [(row, prediction_by_id[row["example_id"]]) for row in examples]
    per_task: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for pair in pairs:
        per_task[pair[0]["task"]].append(pair)

    repository_pairs = [pair for pair in pairs if pair[0]["task"] in REPOSITORY_TASKS]
    rag_pairs = [pair for pair in pairs if pair[0]["task"] in RAG_TASKS]
    documentation_pairs = [pair for pair in pairs if pair[0]["task"] in DOCUMENTATION_TASKS]
    metrics: dict[str, Any] = {
        "example_count": len(examples),
        "repository_understanding_accuracy": _answer_metrics(repository_pairs),
        "rag_answer_accuracy": _answer_metrics(rag_pairs),
        "documentation_correctness": _answer_metrics(documentation_pairs),
        "evidence_accuracy": counts_metric(0, 0, 0),
        "change_impact": counts_metric(0, 0, 0),
        "security": {"true_positive": 0, "false_positive": 0, "false_negative": 0},
        "test_pass_rate": {"passed": 0, "total": 0, "rate": None},
        "coverage_improvement": {"measured": 0, "mean_percentage_point_delta": None},
        "mutation_score": {"mutants_killed": 0, "mutants_total": 0, "score": None},
        "hallucination_rate": {"unsupported": 0, "claims": 0, "rate": None},
        "agent_task_success_rate": {"succeeded": 0, "total": 0, "rate": None},
        "per_task": {},
    }
    ev_tp = ev_fp = ev_fn = 0
    impact_tp = impact_fp = impact_fn = 0
    sec_tp = sec_fp = sec_fn = 0
    coverage_deltas: list[float] = []
    unsupported_total = claims_total = 0
    detail: list[dict[str, Any]] = []

    for example, prediction in pairs:
        example_id = example["example_id"]
        task = example["task"]
        row_result: dict[str, Any] = {"example_id": example_id, "task": task}

        if "expected_evidence" in example:
            expected = _set(example["expected_evidence"], field="expected_evidence", example_id=example_id)
            actual = _set(prediction.get("evidence", []), field="evidence", example_id=example_id)
            ev_tp += len(expected & actual)
            ev_fp += len(actual - expected)
            ev_fn += len(expected - actual)

        unsupported = prediction.get("unsupported_claim_count")
        claims = prediction.get("claim_count")
        if unsupported is None:
            expected_evidence = example.get("available_evidence")
            if expected_evidence is not None:
                available = _set(expected_evidence, field="available_evidence", example_id=example_id)
                citations = _set(prediction.get("evidence", []), field="evidence", example_id=example_id)
                unsupported = len(citations - available)
                claims = claims if claims is not None else len(citations)
        if unsupported is not None or claims is not None:
            if (
                isinstance(unsupported, bool)
                or not isinstance(unsupported, int)
                or isinstance(claims, bool)
                or not isinstance(claims, int)
                or unsupported < 0
                or claims < unsupported
            ):
                raise ValueError(
                    f"{example_id}: claim_count and unsupported_claim_count must be "
                    "non-negative integers with unsupported <= claims"
                )
            unsupported_total += unsupported
            claims_total += claims
            row_result["unsupported_claim_count"] = unsupported
            row_result["claim_count"] = claims

        if task in TEST_TASKS and "test_passed" in prediction:
            if not isinstance(prediction["test_passed"], bool):
                raise ValueError(f"{example_id}: test_passed must be boolean")
            metrics["test_pass_rate"]["total"] += 1
            metrics["test_pass_rate"]["passed"] += prediction["test_passed"]
        before = prediction.get("coverage_before")
        after = prediction.get("coverage_after")
        if before is not None or after is not None:
            if (
                isinstance(before, bool)
                or isinstance(after, bool)
                or not isinstance(before, (int, float))
                or not isinstance(after, (int, float))
                or not 0 <= before <= 100
                or not 0 <= after <= 100
            ):
                raise ValueError(f"{example_id}: coverage_before/after must be percentages from 0 to 100")
            coverage_deltas.append(float(after - before))
            row_result["coverage_delta_percentage_points"] = after - before
        killed = prediction.get("mutants_killed")
        total = prediction.get("mutants_total")
        if killed is not None or total is not None:
            if (
                isinstance(killed, bool)
                or isinstance(total, bool)
                or not isinstance(killed, int)
                or not isinstance(total, int)
                or killed < 0
                or total < killed
            ):
                raise ValueError(f"{example_id}: mutant counts must be integers with 0 <= killed <= total")
            metrics["mutation_score"]["mutants_killed"] += killed
            metrics["mutation_score"]["mutants_total"] += total

        if task in SECURITY_TASKS and "expected_security_findings" in example:
            expected = _set(
                example["expected_security_findings"],
                field="expected_security_findings",
                example_id=example_id,
            )
            actual = _set(
                prediction.get("security_findings", []),
                field="security_findings",
                example_id=example_id,
            )
            sec_tp += len(expected & actual)
            sec_fp += len(actual - expected)
            sec_fn += len(expected - actual)
        if task in IMPACT_TASKS and "expected_impacted_files" in example:
            expected = _set(
                example["expected_impacted_files"],
                field="expected_impacted_files",
                example_id=example_id,
            )
            actual = _set(
                prediction.get("impacted_files", []),
                field="impacted_files",
                example_id=example_id,
            )
            impact_tp += len(expected & actual)
            impact_fp += len(actual - expected)
            impact_fn += len(expected - actual)
        if "task_success" in prediction:
            if not isinstance(prediction["task_success"], bool):
                raise ValueError(f"{example_id}: task_success must be boolean")
            metrics["agent_task_success_rate"]["total"] += 1
            metrics["agent_task_success_rate"]["succeeded"] += prediction["task_success"]
        detail.append(row_result)

    metrics["evidence_accuracy"] = counts_metric(ev_tp, ev_fp, ev_fn)
    metrics["change_impact"] = counts_metric(impact_tp, impact_fp, impact_fn)
    security = counts_metric(sec_tp, sec_fp, sec_fn)
    security["false_positive_rate"] = ratio(sec_fp, sec_fp + len([
        pair for pair in pairs
        if pair[0]["task"] in SECURITY_TASKS
        and pair[0].get("expected_security_findings") == []
        and pair[1].get("security_findings", []) == []
    ]))
    metrics["security"] = security
    test_metric = metrics["test_pass_rate"]
    test_metric["rate"] = ratio(test_metric["passed"], test_metric["total"])
    coverage = metrics["coverage_improvement"]
    coverage["measured"] = len(coverage_deltas)
    coverage["mean_percentage_point_delta"] = ratio(sum(coverage_deltas), len(coverage_deltas))
    mutation = metrics["mutation_score"]
    mutation["score"] = ratio(mutation["mutants_killed"], mutation["mutants_total"])
    hallucination = metrics["hallucination_rate"]
    hallucination["unsupported"] = unsupported_total
    hallucination["claims"] = claims_total
    hallucination["rate"] = ratio(unsupported_total, claims_total)
    success = metrics["agent_task_success_rate"]
    success["rate"] = ratio(success["succeeded"], success["total"])
    metrics["per_task"] = {
        task: {
            "examples": len(task_pairs),
            "answer": _answer_metrics(task_pairs)
            if all(
                isinstance(example.get("expected_answer"), str)
                and isinstance(prediction.get("answer"), str)
                for example, prediction in task_pairs
            )
            else None,
        }
        for task, task_pairs in sorted(per_task.items())
    }
    return metrics, detail
