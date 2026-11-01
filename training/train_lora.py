"""Fine-tune an existing open-weight causal language model with LoRA or QLoRA."""

from __future__ import annotations

import argparse
from pathlib import Path

from data_utils import SPLIT_NAMES, build_prompt, build_target, read_jsonl
from validate_data import validate_records, validate_splits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=Path(__file__).parent / "datasets" / "processed",
        help="Directory containing validated train/validation/test JSONL splits",
    )
    parser.add_argument(
        "--model",
        default="Qwen/Qwen2.5-Coder-1.5B-Instruct",
        help="Existing Hugging Face model ID or local pretrained model directory",
    )
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "output")
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--max-seq-length", type=int, default=2048)
    parser.add_argument("--qlora", action="store_true", help="Load the pretrained base in 4-bit")
    parser.add_argument(
        "--require-verified",
        action="store_true",
        help="Refuse to train if any example has verification status not_run",
    )
    args = parser.parse_args()

    if args.epochs <= 0 or args.learning_rate <= 0 or args.batch_size <= 0:
        parser.error("epochs, learning rate, and batch size must be positive")
    if args.gradient_accumulation_steps <= 0 or args.max_seq_length <= 0:
        parser.error("gradient accumulation and maximum sequence length must be positive")

    errors = validate_splits(args.dataset_dir, require_verified=args.require_verified)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print("Training stopped: dataset validation did not succeed.")
        return 1

    datasets: dict[str, list[dict]] = {}
    for split in SPLIT_NAMES:
        path = args.dataset_dir / f"{split}.jsonl"
        try:
            rows = read_jsonl(path)
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}")
            return 1
        row_errors = validate_records(
            rows,
            path,
            require_both_labels=False,
            require_verified=args.require_verified,
        )
        if row_errors:
            for error in row_errors:
                print(f"ERROR: {error}")
            print("Training stopped: dataset validation did not succeed.")
            return 1
        datasets[split] = rows
    print("Dataset validation succeeded; loading the existing pretrained model.")

    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from trl import SFTConfig, SFTTrainer
    except ImportError as exc:
        print(
            f"ERROR: missing training dependency {exc.name!r}; install training/requirements.txt "
            "in a compatible environment."
        )
        return 1

    if args.qlora and not torch.cuda.is_available():
        parser.error("QLoRA requires a CUDA-enabled PyTorch environment")

    tokenizer = AutoTokenizer.from_pretrained(args.model, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model_kwargs = {"device_map": "auto"}
    if args.qlora:
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
        )
    model = AutoModelForCausalLM.from_pretrained(args.model, **model_kwargs)
    if args.qlora:
        model = prepare_model_for_kbit_training(model)
    model.config.use_cache = False

    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules="all-linear",
    )

    def format_rows(rows: list[dict]) -> Dataset:
        texts = [
            f"{build_prompt(row)}\n\n### Response\n{build_target(row)}{tokenizer.eos_token}"
            for row in rows
        ]
        return Dataset.from_dict({"text": texts})

    train_dataset = format_rows(datasets["train"])
    validation_dataset = format_rows(datasets["validation"])
    training_args = SFTConfig(
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
        gradient_checkpointing=args.qlora,
        fp16=args.qlora and not torch.cuda.is_bf16_supported(),
        bf16=args.qlora and torch.cuda.is_bf16_supported(),
        max_seq_length=args.max_seq_length,
        dataset_text_field="text",
    )
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=validation_dataset,
        processing_class=tokenizer,
        peft_config=lora_config,
    )
    trainer.train()
    trainer.save_model(str(args.output_dir / "adapter"))
    tokenizer.save_pretrained(str(args.output_dir / "adapter"))
    print(f"LoRA adapter saved to {args.output_dir / 'adapter'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
