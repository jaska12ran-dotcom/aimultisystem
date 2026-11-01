from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluations"))
from metrics.core import calculate_metrics  # noqa: E402


class MetricTests(unittest.TestCase):
    def test_metrics_report_all_measured_dimensions(self) -> None:
        examples = [
            {
                "example_id": "repo",
                "repository_id": "eval/repo",
                "task": "repository_understanding",
                "expected_answer": "Uses a service layer.",
                "expected_evidence": ["src/service.py"],
                "available_evidence": ["src/service.py"],
            },
            {
                "example_id": "rag",
                "repository_id": "eval/repo",
                "task": "rag_answer",
                "expected_answer": "The timeout is 5 seconds.",
            },
            {
                "example_id": "docs",
                "repository_id": "eval/repo",
                "task": "documentation",
                "expected_answer": "Returns the normalized name.",
            },
            {
                "example_id": "test",
                "repository_id": "eval/repo",
                "task": "test_generation",
            },
            {
                "example_id": "security",
                "repository_id": "eval/repo",
                "task": "security",
                "expected_security_findings": [],
            },
            {
                "example_id": "impact",
                "repository_id": "eval/repo",
                "task": "change_impact",
                "expected_impacted_files": ["src/caller.py", "tests/test_service.py"],
            },
        ]
        predictions = [
            {
                "example_id": "repo",
                "answer": "Uses a service layer.",
                "evidence": ["src/service.py", "README.md"],
                "claim_count": 2,
                "unsupported_claim_count": 1,
                "task_success": True,
            },
            {"example_id": "rag", "answer": "The timeout is five seconds."},
            {"example_id": "docs", "answer": "Returns the normalized name."},
            {
                "example_id": "test",
                "test_passed": True,
                "coverage_before": 40,
                "coverage_after": 55,
                "mutants_killed": 3,
                "mutants_total": 4,
            },
            {
                "example_id": "security",
                "security_findings": ["CWE-89"],
            },
            {
                "example_id": "impact",
                "impacted_files": ["src/caller.py"],
            },
        ]
        metrics, details = calculate_metrics(examples, predictions)
        self.assertEqual(metrics["repository_understanding_accuracy"]["exact_match_accuracy"], 1)
        self.assertEqual(metrics["rag_answer_accuracy"]["exact_match_accuracy"], 0)
        self.assertEqual(metrics["documentation_correctness"]["exact_match_accuracy"], 1)
        self.assertEqual(metrics["evidence_accuracy"]["precision"], 0.5)
        self.assertEqual(metrics["test_pass_rate"]["rate"], 1)
        self.assertEqual(metrics["coverage_improvement"]["mean_percentage_point_delta"], 15)
        self.assertEqual(metrics["mutation_score"]["score"], 0.75)
        self.assertEqual(metrics["security"]["false_positive_rate"], 1)
        self.assertEqual(metrics["change_impact"]["recall"], 0.5)
        self.assertEqual(metrics["hallucination_rate"]["rate"], 0.5)
        self.assertEqual(metrics["agent_task_success_rate"]["rate"], 1)
        self.assertEqual(len(details), len(examples))


class RunnerTests(unittest.TestCase):
    def test_runner_writes_provenance_report_and_rejects_repository_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            dataset = directory / "dataset.jsonl"
            predictions = directory / "predictions.jsonl"
            training = directory / "training.jsonl"
            report = directory / "report.json"
            dataset.write_text(
                json.dumps(
                    {
                        "example_id": "one",
                        "repository_id": "eval/project",
                        "task": "rag_answer",
                        "expected_answer": "Returns 42.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            predictions.write_text(
                json.dumps({"example_id": "one", "answer": "Returns 42."}) + "\n",
                encoding="utf-8",
            )
            training.write_text(
                json.dumps({"repository_id": "train/project"}) + "\n",
                encoding="utf-8",
            )
            command = [
                sys.executable,
                str(ROOT / "evaluations" / "runners" / "run_eval.py"),
                "--benchmark",
                "codesearchnet",
                "--dataset",
                str(dataset),
                "--predictions",
                str(predictions),
                "--training-repositories",
                str(training),
                "--model",
                "unit-test-model",
                "--license-reviewed",
                "--license-note",
                "Test-only synthetic fixture",
                "--output",
                str(report),
            ]
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(result["metrics"]["rag_answer_accuracy"]["exact_match_accuracy"], 1)
            self.assertEqual(result["provenance"]["dataset_sha256"], __import__("hashlib").sha256(dataset.read_bytes()).hexdigest())

            training.write_text(
                json.dumps({"repository_id": "eval/project"}) + "\n",
                encoding="utf-8",
            )
            leaked = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(leaked.returncode, 2)
            self.assertIn("not held out", leaked.stderr)


if __name__ == "__main__":
    unittest.main()
