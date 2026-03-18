#!/usr/bin/env python3
"""Tests for semantic deduplication module."""

import json
import os
import tempfile
import shutil
import math

import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from semantic_dedup import (
    SemanticDedup,
    EmbeddingCache,
    cosine_similarity,
    _tokenize,
    _ngram_embedding,
    _cosine_similarity_counters,
    _text_to_key,
)


class TestTokenize:
    """Test text tokenization."""

    def test_basic_tokenize(self):
        tokens = _tokenize("The quick brown fox jumps over lazy dog")
        assert "quick" in tokens
        assert "brown" in tokens
        assert "the" in tokens  # simple word tokenizer, lowercase

    def test_lowercase(self):
        tokens = _tokenize("Hello WORLD")
        assert "hello" in tokens
        assert "world" in tokens

    def test_empty_string(self):
        assert _tokenize("") == []

    def test_special_characters(self):
        tokens = _tokenize("payment-processing and api_gateway")
        assert "payment" in tokens
        assert "processing" in tokens
        assert "api_gateway" in tokens

    def test_numbers(self):
        tokens = _tokenize("version 2 release 3")
        assert "version" in tokens
        assert "2" in tokens


class TestNgramEmbedding:
    """Test character n-gram embedding."""

    def test_basic_ngrams(self):
        ngrams = _ngram_embedding("hello", n=3)
        assert "hel" in ngrams
        assert "ell" in ngrams
        assert "llo" in ngrams
        assert len(ngrams) == 3

    def test_empty_string(self):
        ngrams = _ngram_embedding("", n=3)
        assert len(ngrams) == 0

    def test_short_string(self):
        ngrams = _ngram_embedding("hi", n=3)
        assert len(ngrams) == 0

    def test_repeated_chars(self):
        ngrams = _ngram_embedding("aaa", n=3)
        assert ngrams["aaa"] == 1

    def test_case_insensitive(self):
        ngrams = _ngram_embedding("Hello", n=3)
        assert "hel" in ngrams


class TestCosineSimilarity:
    """Test cosine similarity with Counter vectors."""

    def test_identical_counters(self):
        from collections import Counter
        a = Counter({"x": 3, "y": 4})
        sim = _cosine_similarity_counters(a, a)
        assert sim == pytest.approx(1.0)

    def test_orthogonal_counters(self):
        from collections import Counter
        a = Counter({"x": 1})
        b = Counter({"y": 1})
        assert _cosine_similarity_counters(a, b) == pytest.approx(0.0)

    def test_empty_counters(self):
        from collections import Counter
        assert _cosine_similarity_counters(Counter(), Counter({"a": 1})) == 0.0
        assert _cosine_similarity_counters(Counter({"a": 1}), Counter()) == 0.0
        assert _cosine_similarity_counters(Counter(), Counter()) == 0.0

    def test_partial_overlap(self):
        from collections import Counter
        a = Counter({"x": 1, "y": 1})
        b = Counter({"x": 1, "z": 1})
        sim = _cosine_similarity_counters(a, b)
        assert 0.0 < sim < 1.0

    def test_list_cosine_identical(self):
        vec = [1.0, 2.0, 3.0]
        assert cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_list_cosine_orthogonal(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_list_cosine_empty(self):
        assert cosine_similarity([], [1.0]) == 0.0
        assert cosine_similarity([1.0], []) == 0.0

    def test_list_cosine_different_length(self):
        assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0


class TestTextToKey:
    """Test cache key generation."""

    def test_deterministic(self):
        key1 = _text_to_key("hello world")
        key2 = _text_to_key("hello world")
        assert key1 == key2

    def test_case_insensitive(self):
        key1 = _text_to_key("Hello World")
        key2 = _text_to_key("hello world")
        assert key1 == key2

    def test_strips_whitespace(self):
        key1 = _text_to_key("  hello  ")
        key2 = _text_to_key("hello")
        assert key1 == key2

    def test_different_texts(self):
        key1 = _text_to_key("hello")
        key2 = _text_to_key("world")
        assert key1 != key2


class TestEmbeddingCache:
    """Test the EmbeddingCache class."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cache_dir = os.path.join(self.tmpdir, "cache")
        os.makedirs(self.cache_dir, exist_ok=True)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_put_and_get(self):
        from pathlib import Path
        cache = EmbeddingCache(Path(self.cache_dir))
        cache.put("key1", [1.0, 2.0, 3.0])
        assert cache.get("key1") == [1.0, 2.0, 3.0]

    def test_get_missing(self):
        from pathlib import Path
        cache = EmbeddingCache(Path(self.cache_dir))
        assert cache.get("nonexistent") is None

    def test_eviction(self):
        from pathlib import Path
        cache = EmbeddingCache(Path(self.cache_dir), max_size=2)
        cache.put("key1", [1.0])
        cache.put("key2", [2.0])
        cache.put("key3", [3.0])
        assert cache.get("key1") is None  # evicted
        assert cache.get("key3") == [3.0]
        assert len(cache) == 2

    def test_persistence(self):
        from pathlib import Path
        cache = EmbeddingCache(Path(self.cache_dir))
        cache.put("key1", [1.0, 2.0])
        cache.save()

        cache2 = EmbeddingCache(Path(self.cache_dir))
        assert cache2.get("key1") == [1.0, 2.0]

    def test_clear(self):
        from pathlib import Path
        cache = EmbeddingCache(Path(self.cache_dir))
        cache.put("key1", [1.0])
        cache.clear()
        assert len(cache) == 0

    def test_lru_order(self):
        from pathlib import Path
        cache = EmbeddingCache(Path(self.cache_dir), max_size=2)
        cache.put("key1", [1.0])
        cache.put("key2", [2.0])
        cache.get("key1")  # touch key1, making key2 oldest
        cache.put("key3", [3.0])
        assert cache.get("key1") is not None
        assert cache.get("key2") is None  # evicted


class TestSemanticDedup:
    """Test the SemanticDedup class."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.vault_dir = os.path.join(self.tmpdir, "vault")
        os.makedirs(self.vault_dir, exist_ok=True)
        self.cache_dir = os.path.join(self.tmpdir, "cache")
        os.makedirs(self.cache_dir, exist_ok=True)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_empty_vault(self):
        dedup = SemanticDedup(vault_path=self.vault_dir, cache_dir=self.cache_dir)
        assert dedup.is_duplicate("some new fact") is False

    def test_identical_fact(self):
        with open(os.path.join(self.vault_dir, "test.md"), "w") as f:
            f.write("Finix handles payment processing for all merchants.\n")

        dedup = SemanticDedup(
            vault_path=self.vault_dir, cache_dir=self.cache_dir, threshold=0.5
        )
        assert dedup.is_duplicate("Finix handles payment processing for all merchants.") is True

    def test_different_fact(self):
        with open(os.path.join(self.vault_dir, "test.md"), "w") as f:
            f.write("The database uses PostgreSQL with row-level security.\n")

        dedup = SemanticDedup(
            vault_path=self.vault_dir, cache_dir=self.cache_dir, threshold=0.85
        )
        assert dedup.is_duplicate("Deploy the frontend to Vercel CDN") is False

    def test_similar_fact(self):
        with open(os.path.join(self.vault_dir, "test.md"), "w") as f:
            f.write("Finix processes credit card payments for online merchants.\n")

        dedup = SemanticDedup(
            vault_path=self.vault_dir, cache_dir=self.cache_dir, threshold=0.3
        )
        # Should find some similarity
        matches = dedup.find_similar("Finix handles payment processing for merchants", threshold=0.1)
        assert len(matches) > 0
        assert matches[0]["similarity"] > 0.0

    def test_find_similar_returns_sorted(self):
        with open(os.path.join(self.vault_dir, "a.md"), "w") as f:
            f.write("Payment processing handles transactions.\n")
        with open(os.path.join(self.vault_dir, "b.md"), "w") as f:
            f.write("Stablecoin settlement via Brale infrastructure.\n")

        dedup = SemanticDedup(
            vault_path=self.vault_dir, cache_dir=self.cache_dir, threshold=0.1
        )
        matches = dedup.find_similar("Payment processing for merchants", threshold=0.1)
        if len(matches) >= 2:
            assert matches[0]["similarity"] >= matches[1]["similarity"]

    def test_find_similar_max_results(self):
        for i in range(10):
            with open(os.path.join(self.vault_dir, f"note_{i}.md"), "w") as f:
                f.write(f"Some content about topic number {i} with details.\n")

        dedup = SemanticDedup(
            vault_path=self.vault_dir, cache_dir=self.cache_dir, threshold=0.01
        )
        matches = dedup.find_similar("Some content about topic", threshold=0.01, max_results=3)
        assert len(matches) <= 3

    def test_nonexistent_vault(self):
        dedup = SemanticDedup(
            vault_path="/nonexistent/vault", cache_dir=self.cache_dir
        )
        assert dedup.is_duplicate("anything") is False

    def test_similarity_method(self):
        dedup = SemanticDedup(
            vault_path=self.vault_dir, cache_dir=self.cache_dir
        )
        sim = dedup.similarity("hello world", "hello world")
        assert sim == pytest.approx(1.0)

    def test_similarity_different_texts(self):
        dedup = SemanticDedup(
            vault_path=self.vault_dir, cache_dir=self.cache_dir
        )
        sim = dedup.similarity("hello world", "goodbye moon")
        assert sim < 1.0

    def test_similarity_range(self):
        dedup = SemanticDedup(
            vault_path=self.vault_dir, cache_dir=self.cache_dir
        )
        sim = dedup.similarity("payment processing", "payment handling")
        assert 0.0 <= sim <= 1.0

    def test_threshold_customization(self):
        dedup = SemanticDedup(
            vault_path=self.vault_dir, cache_dir=self.cache_dir, threshold=0.99
        )
        assert dedup.threshold == 0.99

    def test_cache_stats(self):
        dedup = SemanticDedup(
            vault_path=self.vault_dir, cache_dir=self.cache_dir
        )
        stats = dedup.cache_stats()
        assert "cached_embeddings" in stats
        assert "max_size" in stats
        assert stats["using_transformer"] is False

    def test_skips_headings_and_receipts(self):
        with open(os.path.join(self.vault_dir, "test.md"), "w") as f:
            f.write("# Heading\n---\n_Receipt: abc123..._\nActual fact content here.\n")

        dedup = SemanticDedup(
            vault_path=self.vault_dir, cache_dir=self.cache_dir, threshold=0.1
        )
        matches = dedup.find_similar("Actual fact content", threshold=0.1)
        # Should find the actual fact, not the heading or receipt
        for m in matches:
            assert not m["fact"].startswith("#")
            assert not m["fact"].startswith("_Receipt:")

    def test_bullet_points_stripped(self):
        with open(os.path.join(self.vault_dir, "test.md"), "w") as f:
            f.write("- Finix handles payment processing\n* Brale handles settlement\n")

        dedup = SemanticDedup(
            vault_path=self.vault_dir, cache_dir=self.cache_dir, threshold=0.1
        )
        matches = dedup.find_similar("Finix handles payment", threshold=0.1)
        for m in matches:
            assert not m["fact"].startswith("- ")
            assert not m["fact"].startswith("* ")
