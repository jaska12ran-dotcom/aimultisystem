# CodeTwin Training & Evaluation

This directory contains two separate training pipelines:

1. **Embedding model** (new) — trains a semantic code-search model on CodeSearchNet
2. **LLM fine-tuning** (existing) — LoRA-tunes Qwen 2.5 Coder on task examples

---

## 1. Embedding Model Training (CodeSearchNet)

The production system uses the trained embedding model for all semantic code search,
RAG retrieval, and NL→code matching. Without training, it falls back to a
deterministic hash embedder (functional but no semantic understanding).

### How it works

The `sentence-transformers/codesearchnet` `pair` config provides positive
**(comment, code)** pairs in a mixed-language stream. Its published schema has
no repository IDs or upstream validation/test splits.

Training uses **MultipleNegativesRankingLoss** (contrastive learning):
- Each batch of N pairs is a (query_i, code_i) set
- For every pair, all other N-1 codes act as **in-batch negatives**
- The model learns to pull docstrings and their code together in embedding space
- No hard negatives needed — the dataset structure is sufficient

The result is a sentence-transformers model you can load anywhere with:
```python
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("training/output/embedding_model")
embeddings = model.encode(["your query here"])
```

The production `EmbeddingService` in `backend/app/services/rag/service.py`
auto-loads this model when present (checks `CODETWIN_EMBEDDING_MODEL` env var
or the default output path).

### Quick start

```powershell
# Step 0: install dependencies
pip install -r training\requirements_embedding.txt

# Step 1: download a sample from the Hugging Face train split
python training\load_hf_dataset.py --limit 100000

# Step 2: normalize comment/code fields and create code-disjoint development splits
python training\prepare_embedding_data.py
# Or run Steps 1–2 as a single command:
# python training\prepare_codesearchnet.py --limit 100000

# Step 3: train the embedding model
python training\train_embedding.py
# On CPU / limited memory (smoke-test):
python training\train_embedding.py --limit 20000 --batch-size 32 --epochs 1

# Step 4: compare against the baseline hash embedder on the development test partition
python training\evaluate_embedding.py --model training\output\embedding_model

# Step 5: activate in production
# Option A — set env var (recommended):
$env:CODETWIN_EMBEDDING_MODEL = "training\output\embedding_model"
# Option B — model is auto-detected at the default output path

# Step 6: re-index your repositories to use the new embeddings
# POST /api/v1/repositories/{id}/index
```

The train/validation/test partitions are for development only. Exact duplicate
code is kept within one partition, but the source does not expose repository
identity, so these are not repository-isolated benchmark splits. Review the
dataset and underlying repository licenses before full training or
redistribution.

### Training configuration

| Argument | Default | Notes |
|---|---|---|
| `--base-model` | `microsoft/unixcoder-base` | Good alternatives: `sentence-transformers/all-MiniLM-L6-v2` (smaller), `Salesforce/codet5p-110m-embedding` |
| `--epochs` | `3` | 1–3 is enough; more rarely helps |
| `--batch-size` | `64` | Larger = more in-batch negatives = better. Use 128–256 on GPU. |
| `--learning-rate` | `2e-5` | Lower for larger models |
| `--limit` | all | Cap training rows for quick experiments |

### Dataset structure

After `prepare_embedding_data.py`, each line in `datasets/codesearchnet/{split}.jsonl`:
```json
{
  "language": "mixed",
  "query": "Compute cosine similarity between two vectors.",
  "code": "def cosine_similarity(a, b):\n    ..."
}
```

---

## 2. LLM Fine-tuning (Qwen 2.5 Coder)

Fine-tunes `Qwen/Qwen2.5-Coder-1.5B-Instruct` with LoRA for CodeTwin's 10
reasoning tasks (documentation generation, test generation, impact analysis, etc.).

### Quick start

```powershell
pip install -r training\requirements.txt

# Prepare only the curated CodeTwin task examples; the CodeSearchNet pair
# loader produces embedding-training data, not this SFT task schema.
python training\prepare_data.py --input training\datasets\examples.jsonl

# Train
python training\train_lora.py --dataset-dir training\datasets\processed

# With QLoRA (4-bit, requires CUDA + bitsandbytes)
pip install bitsandbytes
python training\train_lora.py --dataset-dir training\datasets\processed --qlora
```

### Data format (`datasets/examples.jsonl`)

| Field | Required | Notes |
|---|---|---|
| `example_id` | ✓ | Unique ID |
| `repository_id` | ✓ | Used for train/val/test split isolation |
| `task` | ✓ | One of 10 task types |
| `repository_context` | ✓ | Architecture / metadata |
| `code_context` | ✓ | Code snippets / diffs |
| `expected_output` | ✓ | Gold answer |
| `evidence` | ✓ | File/symbol/commit references |
| `verification_result` | ✓ | `{status: passed/failed/not_run, method: ...}` |
| `confidence` | ✓ | Float 0–1 |
| `example_type` | ✓ | `positive` or `negative` |

### Evaluation

```powershell
python training\evaluate.py \
  --dataset training\datasets\processed\test.jsonl \
  --adapter training\output\adapter \
  --base-model Qwen/Qwen2.5-Coder-1.5B-Instruct
```

Outputs `training/results/metrics.json` with documentation accuracy,
evidence precision/recall, hallucination rate, and security false-positive rate.

---

## License note

The `sentence-transformers/codesearchnet` dataset is derived from GitHub
repositories. Review the [dataset card](https://huggingface.co/datasets/sentence-transformers/codesearchnet)
and source repository licenses before training or distributing models.
