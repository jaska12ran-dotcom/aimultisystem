"""LoRA fine-tune a code-generation model on prepared instruction/code pairs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def validate_splits(dataset_dir: Path) -> tuple[int, int, int]:
    repo_sets: dict[str, set[str]] = {}
    row_counts: dict[str, int] = {}
    for split in ("train", "validation", "test"):
        path = dataset_dir / f"{split}.jsonl"
        if not path.is_file():
            raise ValueError(f"{path}: split file does not exist")
        repositories: set[str] = set()
        count = 0
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
                if not isinstance(row, dict) or any(
                    not isinstance(row.get(field), str) or not row[field].strip()
                    for field in ("repository_id", "instruction", "completion", "source_url")
                ):
                    raise ValueError(
                        f"{path}:{line_number}: expected non-empty repository_id, instruction, "
                        "completion, and source_url"
                    )
                repositories.add(row["repository_id"])
                count += 1
        if count == 0:
            raise ValueError(f"{path}: split contains no rows")
        repo_sets[split] = repositories
        row_counts[split] = count

    for first, second in (("train", "validation"), ("train", "test"), ("validation", "test")):
        overlap = repo_sets[first] & repo_sets[second]
        if overlap:
            raise ValueError(
                f"repository leakage between {first} and {second}: {', '.join(sorted(overlap)[:10])}"
            )
    return row_counts["train"], row_counts["validation"], row_counts["test"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=Path(__file__).parent / "datasets" / "processed" / "codegen_java",
    )
    parser.add_argument("--model", default="Qwen/Qwen2.5-Coder-1.5B-Instruct")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "output_codegen_java")
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--max-seq-length", type=int, default=2048)
    args = parser.parse_args()

    if min(args.epochs, args.learning_rate, args.batch_size) <= 0:
        parser.error("epochs, learning rate, and batch size must be positive")
    if args.gradient_accumulation_steps <= 0 or args.max_seq_length <= 0:
        parser.error("gradient accumulation and maximum sequence length must be positive")
    try:
        counts = validate_splits(args.dataset_dir)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\nTraining stopped: dataset validation did not succeed.\n")
    print(
        "Repository-isolated dataset validated: "
        f"train={counts[0]} validation={counts[1]} test={counts[2]}"
    )

    try:
        import torch
        from datasets import load_dataset
        from peft import LoraConfig
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from trl import SFTConfig, SFTTrainer
    except ImportError as exc:
        parser.exit(
            1,
            f"ERROR: missing training dependency {exc.name!r}; install PyTorch for your hardware "
            "and training/requirements.txt.\n",
        )

    if not torch.cuda.is_available():
        parser.exit(
            1,
            "ERROR: full Java fine-tuning requires a CUDA GPU in this workflow; "
            "no training was started.\n",
        )

    tokenizer = AutoTokenizer.from_pretrained(args.model, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    def as_chat_text(row: dict[str, str]) -> dict[str, str]:
        messages = [
            {
                "role": "system",
                "content": "You are a Java code-generation assistant. Return only valid Java code.",
            },
            {"role": "user", "content": row["instruction"]},
            {"role": "assistant", "content": row["completion"]},
        ]
        return {
            "text": tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=False,
            )
        }

    train_dataset = load_dataset(
        "json",
        data_files=str(args.dataset_dir / "train.jsonl"),
        split="train",
    )
    validation_dataset = load_dataset(
        "json",
        data_files=str(args.dataset_dir / "validation.jsonl"),
        split="train",
    )
    train_dataset = train_dataset.map(as_chat_text, remove_columns=train_dataset.column_names)
    validation_dataset = validation_dataset.map(
        as_chat_text,
        remove_columns=validation_dataset.column_names,
    )

    model = AutoModelForCausalLM.from_pretrained(args.model, device_map="auto")
    model.config.use_cache = False
    trainer = SFTTrainer(
        model=model,
        args=SFTConfig(
            output_dir=str(args.output_dir),
            num_train_epochs=args.epochs,
            learning_rate=args.learning_rate,
            per_device_train_batch_size=args.batch_size,
            per_device_eval_batch_size=args.batch_size,
            gradient_accumulation_steps=args.gradient_accumulation_steps,
            logging_steps=10,
            eval_strategy="epoch",
            save_strategy="epoch",
            save_total_limit=2,
            load_best_model_at_end=True,
            metric_for_best_model="eval_loss",
            greater_is_better=False,
            report_to="none",
            max_seq_length=args.max_seq_length,
            dataset_text_field="text",
        ),
        train_dataset=train_dataset,
        eval_dataset=validation_dataset,
        processing_class=tokenizer,
        peft_config=LoraConfig(
            r=16,
            lora_alpha=32,
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules="all-linear",
        ),
    )
    trainer.train()
    trainer.save_model(str(args.output_dir / "adapter"))
    tokenizer.save_pretrained(str(args.output_dir / "adapter"))
    print(f"LoRA adapter saved to {args.output_dir / 'adapter'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
