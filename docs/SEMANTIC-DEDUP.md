# Semantic Deduplication — OpenClaw LACP v2.0.0

Embedding-based fact deduplication for the LACP vault using TF-IDF cosine similarity.

## Overview

When LCM session facts are promoted to persistent LACP memory, duplicate or near-duplicate facts waste storage and dilute signal. The semantic dedup module compares each candidate fact against existing vault content and flags duplicates before they are written.

## How It Works

1. **Tokenization** — Input text is lowercased, split into words, filtered for stopwords, and tokens shorter than 3 characters are removed. Hyphenated technical terms (e.g., `api-gateway`) are preserved.

2. **TF-IDF Vectorization** — Term frequency (TF) is computed per document, and inverse document frequency (IDF) is computed across the full corpus. Each document becomes a sparse TF-IDF vector.

3. **Cosine Similarity** — The candidate fact's TF-IDF vector is compared against every document in the corpus using cosine similarity. If the maximum similarity exceeds the threshold, the fact is flagged as a duplicate.

4. **Decision Logging** — Every check is logged to a JSONL audit trail with the similarity score, decision (`promote` or `skip`), timestamp, and SHA-256 hash of the fact.

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `threshold` | `0.85` | Cosine similarity threshold (0.0–1.0) |
| `log_path` | `~/.openclaw/logs/dedup.jsonl` | Audit trail path |

## Python API

```python
from semantic_dedup import SemanticDedup, check_fact_duplicate

# One-shot check against vault
result = check_fact_duplicate(
    "Finix handles payment processing",
    vault_path="/path/to/vault",
    threshold=0.85,
)
print(result["is_duplicate"])  # True/False
print(result["max_similarity"])  # 0.0–1.0

# Batch workflow
dedup = SemanticDedup(threshold=0.85)
dedup.load_vault("/path/to/vault")

results = dedup.batch_check([
    "Finix handles payment processing",
    "Brale manages stablecoin settlement",
    "Finix processes payments for merchants",  # likely duplicate of first
])

for r in results:
    print(f"{r['decision']} — sim={r['max_similarity']:.3f}")
```

## CLI Usage

```bash
# Check a single fact
openclaw-lacp-dedup check --fact "Finix handles payment processing" --threshold 0.90

# Batch check from file
openclaw-lacp-dedup batch --file facts.txt --vault /path/to/vault

# View statistics
openclaw-lacp-dedup stats
```

## Integration with Promote Pipeline

The `openclaw-lacp-promote pipeline` command integrates dedup via `--similarity-threshold`:

```bash
openclaw-lacp-promote pipeline \
  --file summary.json \
  --project easy-api \
  --similarity-threshold 0.90
```

Facts exceeding the similarity threshold are automatically skipped during promotion.

## Design Decisions

- **No external dependencies** — Uses TF-IDF + cosine similarity from Python stdlib only. No OpenAI embeddings or ML models required.
- **Incremental corpus updates** — `batch_check` adds unique facts to the corpus as it processes, so later facts in the batch can detect duplicates from earlier ones.
- **Configurable threshold** — 0.85 default balances precision (avoiding false duplicates) with recall (catching true duplicates). Lower for aggressive dedup, higher for conservative.
- **Append-only logging** — JSONL format allows simple auditing and analysis without database dependencies.
