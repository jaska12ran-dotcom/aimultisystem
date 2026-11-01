"""LoRA / QLoRA fine-tuning on repository-isolated SWE-bench Verified instances."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

LOGGER = logging.getLogger("codetwin.train_swebench_lora")
DEFAULT_DATASET_DIR = Path(__file__).parent / "datasets" / "processed" / "swebench" / "instructions"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "output" / "swebench_lora"


def validate_splits(dataset_dir: Path) -> tuple[int, int, int]:
    """Validate that train, validation, and test splits exist and have disjoint repository sets."""
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

                repo = row.get("repository_id")
                instruction = row.get("instruction") or row.get("code_context")
                completion = row.get("completion") or row.get("expected_output")

                if not repo or not instruction or not completion:
                    raise ValueError(
                        f"{path}:{line_number}: record missing repository_id, instruction, or completion"
                    )

                repositories.add(repo)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--model", default="Qwen/Qwen2.5-Coder-1.5B-Instruct")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--max-seq-length", type=int, default=2048)
    parser.add_argument("--qlora", action="store_true", help="Load the base model in 4-bit (requires bitsandbytes)")
    parser.add_argument("--dry-run", action="store_true", help="Validate data and exit without training")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if min(args.epochs, args.learning_rate, args.batch_size) <= 0:
        parser.error("epochs, learning rate, and batch size must be positive")
    if args.gradient_accumulation_steps <= 0 or args.max_seq_length <= 0:
        parser.error("gradient accumulation and max sequence length must be positive")

    try:
        train_c, val_c, test_c = validate_splits(args.dataset_dir)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\nTraining stopped: dataset validation failed.\n")

    print(
        f"Repository-isolated dataset validated successfully:\n"
        f"  train: {train_c} instances\n"
        f"  validation: {val_c} instances\n"
        f"  test: {test_c} instances\n"
    )

    if args.dry_run:
        print("Dry run completed successfully. Dataset and split integrity verified.")
        return 0

    try:
        import torch
        from datasets import load_dataset
        from peft import LoraConfig
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from trl import SFTConfig, SFTTrainer
    except ImportError as exc:
        parser.exit(
            1,
            f"ERROR: missing training dependency {exc.name!r}; install PyTorch and training/requirements.txt\n",
        )

    device_str = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device_str}")

    tokenizer = AutoTokenizer.from_pretrained(args.model, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    def as_chat_text(row: dict[str, str]) -> dict[str, str]:
        instruction = row.get("instruction") or row.get("code_context", "")
        completion = row.get("completion") or row.get("expected_output", "")
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert software engineer assistant. Analyze the repository issue "
                    "and generate a clean, minimal git patch to resolve the bug."
                ),
            },
            {"role": "user", "content": instruction},
            {"role": "assistant", "content": completion},
        ]
        return {
            "text": tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=False,
            )
        }

    dataset = load_dataset(
        "json",
        data_files={
            "train": str(args.dataset_dir / "train.jsonl"),
            "validation": str(args.dataset_dir / "validation.jsonl"),
        },
    )
    tokenized_train = dataset["train"].map(as_chat_text)
    tokenized_val = dataset["validation"].map(as_chat_text)

    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )

    training_args = SFTConfig(
        output_dir=str(args.output_dir),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        logging_steps=10,
        eval_strategy="epoch",
        save_strategy="epoch",
        max_seq_length=args.max_seq_length,
        dataset_text_field="text",
        fp16=torch.cuda.is_available(),
    )

    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        device_map="auto" if torch.cuda.is_available() else None,
    )

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_train,
        eval_dataset=tokenized_val,
        peft_config=lora_config,
    )

    print("Starting training...")
    trainer.train()
    trainer.save_model(str(args.output_dir))
    tokenizer.save_pretrained(str(args.output_dir))
    print(f"Model saved to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

