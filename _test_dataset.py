"""Test that the dill patches allow loading the dataset."""
from datasets import load_dataset
print("Loading sentence-transformers/codesearchnet (5 rows)...")
ds = load_dataset(
    "sentence-transformers/codesearchnet",
    split="train[:5]",
    trust_remote_code=True,
)
print("KEYS:", list(ds[0].keys()))
for k, v in ds[0].items():
    print(f"  {k}: {str(v)[:80]}")
print("SUCCESS: dataset loads correctly")
