"""Tests for semantic_dedup.py — Embedding-based fact deduplication."""

import json
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
V2_LCM_DIR = REPO_ROOT / "plugin" / "v2-lcm"
sys.path.insert(0, str(V2_LCM_DIR))

from semantic_dedup import (
    SemanticDedup,
    EmbeddingCache,
    cosine_similarity,
    _text_to_key,
    _ngram_embedding,
    _cosine_similarity_counters,
    _tokenize,
)


class TestEmbeddingCache:
    """Test the LRU embedding cache."""

    def test_cache_put_and_get(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = EmbeddingCache(Path(tmpdir), max_size=10)
            cache.put("key1", [1.0, 2.0, 3.0])
            result = cache.get("key1")
            assert result == [1.0, 2.0, 3.0]

    def test_cache_miss_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = EmbeddingCache(Path(tmpdir), max_size=10)
            assert cache.get("nonexistent") is None

    def test_cache_lru_eviction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = EmbeddingCache(Path(tmpdir), max_size=3)
            cache.put("a", [1.0])
            cache.put("b", [2.0])
            cache.put("c", [3.0])
            cache.put("d", [4.0])  # Should evict "a"
            assert cache.get("a") is None
            assert cache.get("d") == [4.0]

    def test_cache_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache1 = EmbeddingCache(Path(tmpdir), max_size=10)
            cache1.put("key1", [1.0, 2.0])
            cache1.save()

            cache2 = EmbeddingCache(Path(tmpdir), max_size=10)
            assert cache2.get("key1") == [1.0, 2.0]

    def test_cache_len(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = EmbeddingCache(Path(tmpdir), max_size=10)
            assert len(cache) == 0
            cache.put("a", [1.0])
            cache.put("b", [2.0])
            assert len(cache) == 2

    def test_cache_clear(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = EmbeddingCache(Path(tmpdir), max_size=10)
            cache.put("a", [1.0])
            cache.clear()
            assert len(cache) == 0


class TestSimilarityFunctions:
    """Test low-level similarity functions."""

    def test_cosine_identical_vectors(self):
        vec = [1.0, 2.0, 3.0]
        sim = cosine_similarity(vec, vec)
        assert abs(sim - 1.0) < 0.001

    def test_cosine_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        sim = cosine_similarity(a, b)
        assert abs(sim) < 0.001

    def test_cosine_empty_vectors(self):
        assert cosine_similarity([], []) == 0.0

    def test_ngram_same_text(self):
        a = _ngram_embedding("hello world")
        sim = _cosine_similarity_counters(a, a)
        assert abs(sim - 1.0) < 0.001

    def test_tokenize(self):
        tokens = _tokenize("Hello World! This is a test.")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens

    def test_text_to_key_deterministic(self):
        k1 = _text_to_key("test fact")
        k2 = _text_to_key("test fact")
        assert k1 == k2

    def test_text_to_key_different_texts(self):
        k1 = _text_to_key("fact one")
        k2 = _text_to_key("fact two")
        assert k1 != k2


class TestSemanticDedup:
    """Test the SemanticDedup class."""

    def test_init_with_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sd = SemanticDedup(vault_path=tmpdir)
            assert sd.threshold == 0.85

    def test_init_custom_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sd = SemanticDedup(vault_path=tmpdir, threshold=0.90)
            assert sd.threshold == 0.90

    def test_similarity_identical_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sd = SemanticDedup(vault_path=tmpdir)
            sim = sd.similarity("PostgreSQL is the primary database", "PostgreSQL is the primary database")
            assert sim > 0.99

    def test_similarity_different_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sd = SemanticDedup(vault_path=tmpdir)
            sim = sd.similarity(
                "PostgreSQL is the primary database for all services",
                "The weather today is sunny and warm outside"
            )
            assert sim < 0.5

    def test_find_similar_empty_vault(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sd = SemanticDedup(vault_path=tmpdir)
            matches = sd.find_similar("New fact about architecture")
            assert matches == []

    def test_find_similar_with_vault_facts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_dir = Path(tmpdir) / "vault"
            vault_dir.mkdir()
            (vault_dir / "facts.md").write_text(
                "# Facts\n\n"
                "PostgreSQL is the primary database for all services.\n"
                "Redis handles caching across the platform.\n"
                "FastAPI powers the API layer.\n"
            )

            sd = SemanticDedup(vault_path=str(vault_dir), threshold=0.5)
            matches = sd.find_similar("PostgreSQL is the primary database for all services", threshold=0.5)
            assert len(matches) > 0
            assert matches[0]["similarity"] > 0.5

    def test_is_duplicate_true(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_dir = Path(tmpdir) / "vault"
            vault_dir.mkdir()
            (vault_dir / "facts.md").write_text(
                "# Facts\n\nPostgreSQL is the primary database for all services.\n"
            )

            sd = SemanticDedup(vault_path=str(vault_dir), threshold=0.85)
            assert sd.is_duplicate("PostgreSQL is the primary database for all services") is True

    def test_is_duplicate_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_dir = Path(tmpdir) / "vault"
            vault_dir.mkdir()
            (vault_dir / "facts.md").write_text(
                "# Facts\n\nPostgreSQL is the primary database for all services.\n"
            )

            sd = SemanticDedup(vault_path=str(vault_dir), threshold=0.85)
            assert sd.is_duplicate("The weather is sunny today and very warm") is False

    def test_cache_stats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sd = SemanticDedup(vault_path=tmpdir)
            stats = sd.cache_stats()
            assert "cached_embeddings" in stats
            assert "max_size" in stats
            assert "using_transformer" in stats

    def test_save_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sd = SemanticDedup(vault_path=tmpdir)
            sd.similarity("test text one", "test text two")
            sd.save_cache()
            # Verify cache file was created
            cache_dir = Path(tmpdir) / ".openclaw-lacp-embeddings"
            assert cache_dir.exists()
