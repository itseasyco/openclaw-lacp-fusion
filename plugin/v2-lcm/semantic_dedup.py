#!/usr/bin/env python3
"""
Semantic Deduplication — Embedding-based fact deduplication for LACP.

Prevents duplicate facts from being promoted by computing semantic similarity
between new facts and existing vault facts.

Uses character n-gram + word overlap similarity (no external deps required).
"""

import hashlib
import json
import math
import os
import re
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class EmbeddingCache:
    """LRU cache for fact embeddings, persisted to disk."""

    def __init__(self, cache_dir: Path, max_size: int = 500):
        self.cache_dir = cache_dir
        self.max_size = max_size
        self._cache: OrderedDict = OrderedDict()
        self._load()

    def _cache_file(self) -> Path:
        return self.cache_dir / "embedding_cache.json"

    def _load(self) -> None:
        """Load cache from disk."""
        try:
            if self._cache_file().exists():
                data = json.loads(self._cache_file().read_text())
                for key, value in data.items():
                    self._cache[key] = value
        except (json.JSONDecodeError, OSError):
            self._cache = OrderedDict()

    def save(self) -> None:
        """Persist cache to disk."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            items = list(self._cache.items())[-self.max_size:]
            self._cache_file().write_text(json.dumps(dict(items), indent=2))
        except OSError:
            pass

    def get(self, key: str) -> Optional[list]:
        """Get embedding from cache, updating LRU order."""
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, key: str, embedding: list) -> None:
        """Add embedding to cache, evicting oldest if full."""
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = embedding
        while len(self._cache) > self.max_size:
            self._cache.popitem(last=False)

    def __len__(self) -> int:
        return len(self._cache)

    def clear(self) -> None:
        self._cache.clear()


def _text_to_key(text: str) -> str:
    """Generate a cache key from text."""
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()[:16]


def _tokenize(text: str) -> list[str]:
    """Simple word tokenization."""
    return re.findall(r'\b\w+\b', text.lower())


def _ngram_embedding(text: str, n: int = 3) -> Counter:
    """Create character n-gram frequency vector."""
    text = text.lower().strip()
    ngrams: Counter = Counter()
    for i in range(len(text) - n + 1):
        ngrams[text[i:i + n]] += 1
    return ngrams


def _cosine_similarity_counters(a: Counter, b: Counter) -> float:
    """Compute cosine similarity between two Counter vectors."""
    if not a or not b:
        return 0.0

    common_keys = set(a.keys()) & set(b.keys())
    dot_product = sum(a[k] * b[k] for k in common_keys)

    mag_a = math.sqrt(sum(v * v for v in a.values()))
    mag_b = math.sqrt(sum(v * v for v in b.values()))

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot_product / (mag_a * mag_b)


def cosine_similarity(vec_a: list, vec_b: list) -> float:
    """Compute cosine similarity between two vectors (list of floats)."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = math.sqrt(sum(a * a for a in vec_a))
    mag_b = math.sqrt(sum(b * b for b in vec_b))

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot / (mag_a * mag_b)


class SemanticDedup:
    """Embedding-based deduplication for LACP facts."""

    def __init__(
        self,
        vault_path: Optional[str] = None,
        cache_dir: Optional[str] = None,
        threshold: float = 0.85,
        max_cache_size: int = 500,
    ):
        self.vault_path = Path(vault_path) if vault_path else Path.home() / ".openclaw" / "vault"
        cache_path = Path(cache_dir) if cache_dir else self.vault_path / ".openclaw-lacp-embeddings"
        self.threshold = threshold
        self.cache = EmbeddingCache(cache_path, max_size=max_cache_size)

    def similarity(self, text_a: str, text_b: str) -> float:
        """Compute semantic similarity between two texts."""
        # Combine n-gram and word overlap
        ngram_sim = _cosine_similarity_counters(
            _ngram_embedding(text_a), _ngram_embedding(text_b)
        )
        words_a = Counter(_tokenize(text_a))
        words_b = Counter(_tokenize(text_b))
        word_sim = _cosine_similarity_counters(words_a, words_b)
        return 0.6 * ngram_sim + 0.4 * word_sim

    def find_similar(
        self,
        new_fact: str,
        threshold: Optional[float] = None,
        max_results: int = 10,
    ) -> list[dict]:
        """
        Find facts in vault that are semantically similar to new_fact.

        Returns list of dicts with keys: fact, source_file, similarity, should_skip
        """
        if threshold is None:
            threshold = self.threshold

        existing_facts = self._load_vault_facts()
        matches = []

        for fact_entry in existing_facts:
            sim = self.similarity(new_fact, fact_entry["fact"])
            if sim >= threshold:
                matches.append({
                    "fact": fact_entry["fact"],
                    "source_file": fact_entry.get("source_file", "unknown"),
                    "similarity": round(sim, 4),
                    "should_skip": sim >= self.threshold,
                })

        matches.sort(key=lambda x: x["similarity"], reverse=True)
        return matches[:max_results]

    def is_duplicate(self, new_fact: str, threshold: Optional[float] = None) -> bool:
        """Check if a fact is a duplicate of any existing vault fact."""
        matches = self.find_similar(new_fact, threshold=threshold, max_results=1)
        return len(matches) > 0 and matches[0]["should_skip"]

    def _load_vault_facts(self) -> list[dict]:
        """Load all facts from vault markdown files."""
        facts = []
        if not self.vault_path.exists():
            return facts

        for md_file in self.vault_path.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
                rel_path = str(md_file.relative_to(self.vault_path))

                lines = content.split("\n")
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("---"):
                        continue
                    if line.startswith(("- ", "* ", "+ ")):
                        line = line[2:]
                    if len(line) > 15 and not line.startswith("_Receipt:"):
                        facts.append({"fact": line, "source_file": rel_path})
            except (OSError, UnicodeDecodeError):
                continue

        return facts

    def save_cache(self) -> None:
        """Persist the embedding cache to disk."""
        self.cache.save()

    def cache_stats(self) -> dict:
        """Return cache statistics."""
        return {
            "cached_embeddings": len(self.cache),
            "max_size": self.cache.max_size,
            "cache_dir": str(self.cache.cache_dir),
            "using_transformer": False,
        }
