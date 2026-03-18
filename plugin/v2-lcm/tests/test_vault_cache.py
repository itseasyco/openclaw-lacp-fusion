#!/usr/bin/env python3
"""Tests for vault cache module."""

import os
import tempfile
import shutil
import time

import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vault_cache import (
    VaultCache,
    LatencyTracker,
    BatchPromoter,
    LazyVaultLoader,
    DEFAULT_TTL,
)


class TestVaultCache:
    """Test the VaultCache class."""

    def test_set_and_get(self):
        cache = VaultCache()
        cache.set("key1", {"data": "value"})
        result = cache.get("key1")
        assert result == {"data": "value"}

    def test_get_missing(self):
        cache = VaultCache()
        assert cache.get("nonexistent") is None

    def test_ttl_expiry(self):
        cache = VaultCache(ttl=1)
        cache.set("key1", {"data": "value"}, ttl=0)
        # Entry should be expired immediately
        time.sleep(0.01)
        assert cache.get("key1") is None

    def test_custom_ttl(self):
        cache = VaultCache(ttl=1)
        cache.set("key1", {"data": "value"}, ttl=300)
        result = cache.get("key1")
        assert result is not None

    def test_invalidate(self):
        cache = VaultCache()
        cache.set("key1", {"data": "value"})
        assert cache.invalidate("key1") is True
        assert cache.get("key1") is None

    def test_invalidate_missing(self):
        cache = VaultCache()
        assert cache.invalidate("nonexistent") is False

    def test_invalidate_prefix(self):
        cache = VaultCache()
        cache.set("project:easy-api:fact1", {"data": "1"})
        cache.set("project:easy-api:fact2", {"data": "2"})
        cache.set("project:easy-dashboard:fact1", {"data": "3"})
        count = cache.invalidate_prefix("project:easy-api:")
        assert count == 2
        assert cache.get("project:easy-api:fact1") is None
        assert cache.get("project:easy-dashboard:fact1") is not None

    def test_clear(self):
        cache = VaultCache()
        cache.set("key1", {"data": "1"})
        cache.set("key2", {"data": "2"})
        cache.clear()
        assert cache.size == 0

    def test_size(self):
        cache = VaultCache()
        assert cache.size == 0
        cache.set("key1", {"data": "1"})
        assert cache.size == 1
        cache.set("key2", {"data": "2"})
        assert cache.size == 2

    def test_max_entries_eviction(self):
        cache = VaultCache(max_entries=3)
        cache.set("key1", {"data": "1"})
        cache.set("key2", {"data": "2"})
        cache.set("key3", {"data": "3"})
        cache.set("key4", {"data": "4"})
        assert cache.size == 3

    def test_hit_rate(self):
        cache = VaultCache()
        cache.set("key1", {"data": "value"})
        cache.get("key1")  # hit
        cache.get("key1")  # hit
        cache.get("key2")  # miss
        assert cache.hit_rate == pytest.approx(2/3, abs=0.01)

    def test_hit_rate_empty(self):
        cache = VaultCache()
        assert cache.hit_rate == 0.0

    def test_stats(self):
        cache = VaultCache()
        cache.set("key1", {"data": "value"})
        cache.get("key1")
        cache.get("missing")
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1


class TestLatencyTracker:
    """Test the LatencyTracker class."""

    def test_record(self):
        tracker = LatencyTracker(target_ms=100)
        entry = tracker.record("query", 50.0)
        assert entry["operation"] == "query"
        assert entry["latency_ms"] == 50.0
        assert entry["within_target"] is True

    def test_record_above_target(self):
        tracker = LatencyTracker(target_ms=100)
        entry = tracker.record("query", 150.0)
        assert entry["within_target"] is False

    def test_context_manager(self):
        tracker = LatencyTracker()
        with tracker.measure("test_op"):
            time.sleep(0.01)
        assert len(tracker.measurements) == 1
        assert tracker.measurements[0]["operation"] == "test_op"
        assert tracker.measurements[0]["latency_ms"] > 0

    def test_report_empty(self):
        tracker = LatencyTracker()
        report = tracker.get_report()
        assert report["count"] == 0

    def test_report_with_data(self):
        tracker = LatencyTracker(target_ms=100)
        tracker.record("op1", 50.0)
        tracker.record("op2", 80.0)
        tracker.record("op3", 120.0)
        report = tracker.get_report()
        assert report["count"] == 3
        assert report["avg_ms"] == pytest.approx(250/3, abs=0.1)
        assert report["min_ms"] == 50.0
        assert report["max_ms"] == 120.0
        assert report["within_target_pct"] == pytest.approx(66.7, abs=0.1)

    def test_measurement_cap(self):
        tracker = LatencyTracker()
        for i in range(1100):
            tracker.record(f"op_{i}", float(i))
        assert len(tracker.measurements) == 1000


class TestBatchPromoter:
    """Test the BatchPromoter class."""

    def test_enqueue(self):
        bp = BatchPromoter()
        bp.enqueue("fact1", "arch", "easy-api", 85.0, "sum_1")
        assert bp.queue_size == 1

    def test_flush(self):
        bp = BatchPromoter()
        bp.enqueue("fact1", "arch", "easy-api", 85.0)
        bp.enqueue("fact2", "ops", "easy-api", 70.0)
        items = bp.flush()
        assert len(items) == 2
        assert bp.queue_size == 0

    def test_flush_empty(self):
        bp = BatchPromoter()
        items = bp.flush()
        assert len(items) == 0

    def test_enqueue_fields(self):
        bp = BatchPromoter()
        bp.enqueue("fact1", "arch", "easy-api", 85.0, "sum_1")
        items = bp.flush()
        assert items[0]["fact"] == "fact1"
        assert items[0]["category"] == "arch"
        assert items[0]["project"] == "easy-api"
        assert items[0]["score"] == 85.0
        assert "queued_at" in items[0]


class TestLazyVaultLoader:
    """Test the LazyVaultLoader class."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.vault_dir = os.path.join(self.tmpdir, "vault")
        os.makedirs(self.vault_dir, exist_ok=True)

        # Create test notes
        with open(os.path.join(self.vault_dir, "payment.md"), "w") as f:
            f.write("# Payment Processing\nFinix handles payments.\n")
        with open(os.path.join(self.vault_dir, "database.md"), "w") as f:
            f.write("# Database\nPostgres with RLS.\n")

        subdir = os.path.join(self.vault_dir, "subdir")
        os.makedirs(subdir, exist_ok=True)
        with open(os.path.join(subdir, "nested.md"), "w") as f:
            f.write("# Nested Note\nSome content.\n")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_note_count(self):
        loader = LazyVaultLoader(self.vault_dir)
        assert loader.note_count == 3

    def test_lazy_loading(self):
        loader = LazyVaultLoader(self.vault_dir)
        assert loader.loaded_count == 0
        content = loader.get_note("payment.md")
        assert content is not None
        assert "Finix" in content
        assert loader.loaded_count == 1

    def test_get_nonexistent_note(self):
        loader = LazyVaultLoader(self.vault_dir)
        assert loader.get_note("nonexistent.md") is None

    def test_search(self):
        loader = LazyVaultLoader(self.vault_dir)
        results = loader.search("payment")
        assert len(results) >= 1
        assert "payment.md" in results

    def test_search_no_results(self):
        loader = LazyVaultLoader(self.vault_dir)
        results = loader.search("zzzznonexistent")
        assert len(results) == 0

    def test_unload(self):
        loader = LazyVaultLoader(self.vault_dir)
        loader.get_note("payment.md")
        assert loader.loaded_count == 1
        loader.unload()
        assert loader.loaded_count == 0

    def test_nonexistent_vault(self):
        loader = LazyVaultLoader("/nonexistent/vault")
        assert loader.note_count == 0

    def test_cached_reads(self):
        loader = LazyVaultLoader(self.vault_dir)
        content1 = loader.get_note("payment.md")
        content2 = loader.get_note("payment.md")
        assert content1 == content2
        assert loader.loaded_count == 1  # only loaded once
