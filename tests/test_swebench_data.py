"""Tests for SWE-bench Verified dataset loader, preparation, and repository isolation."""

import json
from pathlib import Path
import pytest

from training.load_swebench_dataset import (
    extract_modified_files,
    parse_test_list,
    normalize_swebench_record,
)
from training.prepare_swebench_data import (
    format_as_multitask_record,
    prepare_swebench_splits,
)
from training.train_swebench_lora import validate_splits
from training.data_utils import REQUIRED_FIELDS, TASKS


SAMPLE_PATCH = """diff --git a/django/db/models/fields/__init__.py b/django/db/models/fields/__init__.py
--- a/django/db/models/fields/__init__.py
+++ b/django/db/models/fields/__init__.py
@@ -100,6 +100,8 @@ def to_python(self, value):
+    if value is None:
+        return None
diff --git a/django/utils/text.py b/django/utils/text.py
--- a/django/utils/text.py
+++ b/django/utils/text.py
@@ -50,3 +50,4 @@ def slugify(value):
+    return value.strip()
"""


def test_extract_modified_files():
    files = extract_modified_files(SAMPLE_PATCH)
    assert "django/db/models/fields/__init__.py" in files
    assert "django/utils/text.py" in files
    assert len(files) == 2


def test_parse_test_list():
    assert parse_test_list(["test_a", "test_b"]) == ["test_a", "test_b"]
    assert parse_test_list('["tests.test_model.test_save", "tests.test_query"]') == [
        "tests.test_model.test_save",
        "tests.test_query",
    ]
    assert parse_test_list("") == []
    assert parse_test_list(None) == []


def test_normalize_swebench_record():
    raw = {
        "instance_id": "django__django-11099",
        "repo": "django/django",
        "base_commit": "abc12345",
        "problem_statement": "UsernameValidator accepts trailing newline.",
        "patch": SAMPLE_PATCH,
        "test_patch": "--- a/tests/test_auth.py\n+++ b/tests/test_auth.py\n",
        "FAIL_TO_PASS": '["tests.test_auth.test_trailing_newline"]',
        "version": "3.0",
    }
    norm = normalize_swebench_record(raw, 0)
    assert norm is not None
    assert norm["instance_id"] == "django__django-11099"
    assert norm["repo"] == "django/django"
    assert norm["fail_to_pass"] == ["tests.test_auth.test_trailing_newline"]
    assert len(norm["modified_files"]) == 2


def test_format_as_multitask_record_schema():
    item = {
        "instance_id": "django__django-11099",
        "repo": "django/django",
        "base_commit": "abc12345",
        "problem_statement": "UsernameValidator accepts trailing newline.",
        "patch": SAMPLE_PATCH,
        "version": "3.0",
        "fail_to_pass": ["tests.test_auth.test_trailing_newline"],
        "modified_files": ["django/db/models/fields/__init__.py"],
    }
    mt = format_as_multitask_record(item)
    assert REQUIRED_FIELDS.issubset(mt.keys())
    assert mt["task"] in TASKS
    assert mt["task"] == "test_failure_diagnosis"
    assert mt["repository_id"] == "django/django"
    assert mt["confidence"] == 1.0
    assert mt["verification_result"]["status"] == "passed"


def test_prepare_swebench_splits_repository_isolation(tmp_path: Path):
    # Create sample records across multiple repositories
    repos = ["repo/alpha", "repo/beta", "repo/gamma", "repo/delta", "repo/epsilon"]
    records = []
    for r_idx, repo in enumerate(repos):
        for i in range(4):
            records.append({
                "instance_id": f"{repo.replace('/', '__')}-{i}",
                "repo": repo,
                "base_commit": f"commit_{r_idx}_{i}",
                "problem_statement": f"Bug {i} in {repo}",
                "patch": SAMPLE_PATCH,
                "version": "1.0",
                "fail_to_pass": [f"test_{i}"],
                "modified_files": ["file.py"],
            })

    output_dir = tmp_path / "processed_swebench"
    counts = prepare_swebench_splits(records, output_dir, seed=42, val_pct=20, test_pct=20)

    assert counts["train"] > 0
    assert counts["validation"] > 0
    assert counts["test"] > 0

    # Test repository isolation with validate_splits from train_swebench_lora
    inst_dir = output_dir / "instructions"
    tr_c, val_c, te_c = validate_splits(inst_dir)
    assert tr_c == counts["train"]
    assert val_c == counts["validation"]
    assert te_c == counts["test"]


def test_validate_splits_detects_leakage(tmp_path: Path):
    split_dir = tmp_path / "leaky_splits"
    split_dir.mkdir(parents=True)

    # Train and test share repo "repo/shared"
    row1 = {"repository_id": "repo/shared", "instruction": "fix bug", "completion": "diff"}
    row2 = {"repository_id": "repo/shared", "instruction": "fix bug 2", "completion": "diff"}
    row3 = {"repository_id": "repo/other", "instruction": "fix bug 3", "completion": "diff"}

    (split_dir / "train.jsonl").write_text(json.dumps(row1) + "\n", encoding="utf-8")
    (split_dir / "validation.jsonl").write_text(json.dumps(row3) + "\n", encoding="utf-8")
    (split_dir / "test.jsonl").write_text(json.dumps(row2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="repository leakage"):
        validate_splits(split_dir)

