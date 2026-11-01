import argparse
import json
from pathlib import Path

import pytest

from training.evaluate_embedding import evaluate
from training import prepare_codesearchnet
from training.prepare_embedding_data import prepare_records, write_splits
from training.train_embedding import _read_pairs


def test_prepare_records_deduplicates_code_before_splitting():
    records = [
        {"comment": f"description {index}", "code": f"code {index}"}
        for index in range(10)
    ]
    records.append({"comment": "duplicate description", "code": "code 0"})

    splits = prepare_records(
        records,
        validation_fraction=0.2,
        test_fraction=0.2,
        seed=13,
    )

    assert {split: len(rows) for split, rows in splits.items()} == {
        "train": 6,
        "validation": 2,
        "test": 2,
    }
    codes_by_split = {
        split: {row["code"] for row in rows}
        for split, rows in splits.items()
    }
    assert codes_by_split["train"].isdisjoint(codes_by_split["validation"])
    assert codes_by_split["train"].isdisjoint(codes_by_split["test"])
    assert codes_by_split["validation"].isdisjoint(codes_by_split["test"])
    assert all(row["language"] == "mixed" and row["query"] for rows in splits.values() for row in rows)


def test_prepare_records_is_deterministic_for_same_seed():
    records = [
        {"comment": f"description {index}", "code": f"code {index}"}
        for index in range(12)
    ]

    first = prepare_records(
        records, validation_fraction=0.2, test_fraction=0.2, seed=7
    )
    second = prepare_records(
        records, validation_fraction=0.2, test_fraction=0.2, seed=7
    )

    assert first == second


def test_prepared_pairs_flow_through_trainer_and_evaluator(tmp_path):
    records = [
        {"comment": f"description {index}", "code": f"code {index}"}
        for index in range(20)
    ]
    splits = prepare_records(
        records,
        validation_fraction=0.2,
        test_fraction=0.2,
        seed=21,
    )
    write_splits(tmp_path, splits)

    train_pairs = _read_pairs(tmp_path, "train", limit=4, seed=42)
    assert len(train_pairs) == 4
    assert all(query.startswith("description ") for query, _ in train_pairs)

    args = argparse.Namespace(
        model=None,
        data_dir=tmp_path,
        output_dir=tmp_path / "evaluation",
        batch_size=4,
        limit=None,
        languages=None,
    )
    assert evaluate(args) == 0
    report = json.loads((args.output_dir / "evaluation_report.json").read_text())
    assert "mixed" in report


def test_one_shot_downloader_passes_download_into_preparation(tmp_path, monkeypatch):
    calls = {}

    def fake_download(argv):
        output_path = Path(argv[argv.index("--output") + 1])
        output_path.write_text(
            '{"comment":"description","code":"source code"}\n',
            encoding="utf-8",
        )
        calls["raw_output"] = output_path
        return 0

    def fake_prepare(argv):
        input_path = Path(argv[argv.index("--input") + 1])
        calls["input_exists"] = input_path.is_file()
        calls["output_dir"] = Path(argv[argv.index("--output-dir") + 1])
        calls["seed"] = argv[argv.index("--seed") + 1]
        return 0

    monkeypatch.setattr(prepare_codesearchnet, "download_sample", fake_download)
    monkeypatch.setattr(prepare_codesearchnet, "prepare_sample", fake_prepare)

    result = prepare_codesearchnet.main(
        ["--limit", "10", "--output-dir", str(tmp_path), "--seed", "9"]
    )

    assert result == 0
    assert calls["input_exists"]
    assert calls["output_dir"] == tmp_path
    assert calls["seed"] == "9"
    assert not calls["raw_output"].exists()


@pytest.mark.parametrize(
    ("validation_fraction", "test_fraction"),
    [(0, 0.1), (0.1, 0), (0.5, 0.5), (-0.1, 0.1)],
)
def test_prepare_records_rejects_invalid_split_fractions(
    validation_fraction, test_fraction
):
    records = [
        {"comment": f"description {index}", "code": f"code {index}"}
        for index in range(4)
    ]

    with pytest.raises(ValueError):
        prepare_records(
            records,
            validation_fraction=validation_fraction,
            test_fraction=test_fraction,
            seed=42,
        )


def test_prepare_records_rejects_missing_pair_fields():
    with pytest.raises(ValueError, match="comment"):
        prepare_records(
            [{"code": "valid code"}],
            validation_fraction=0.1,
            test_fraction=0.1,
            seed=42,
        )
