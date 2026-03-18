#!/usr/bin/env python3
"""
Vault Cache — Performance-optimized caching for LACP vault queries.

Provides TTL-based caching for vault queries, batch operations,
and lazy-loading for large vaults.

Features:
- In-memory cache with configurable TTL
- Cache invalidation on vault changes
- Batch promote operations
- Lazy-load graph for large vaults
- Query latency measurement (target: <100ms)
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DEFAULT_TTL = 300  # 5 minutes
MAX_CACHE_ENTRIES = 1000
LATENCY_TARGET_MS = 100


class VaultCache:
    """TTL-based cache for vault queries with latency tracking."""

    def __init__(self, ttl: int = DEFAULT_TTL, max_entries: int = MAX_CACHE_ENTRIES):
        self.ttl = ttl
        self.max_entries = max_entries
        self._cache = {}
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "total_queries": 0,
            "total_latency_ms": 0.0,
        }

    def get(self, key: str) -> Optional[dict]:
        """Get a cached value by key. Returns None if expired or missing."""
        self._stats["total_queries"] += 1

        entry = self._cache.get(key)
        if entry is None:
            self._stats["misses"] += 1
            return None

        if time.time() > entry["expires_at"]:
            del self._cache[key]
            self._stats["misses"] += 1
            self._stats["evictions"] += 1
            return None

        self._stats["hits"] += 1
        entry["last_accessed"] = time.time()
        return entry["value"]

    def set(self, key: str, value: dict, ttl: Optional[int] = None) -> None:
        """Set a cache entry with optional custom TTL."""
        if len(self._cache) >= self.max_entries:
            self._evict_oldest()

        self._cache[key] = {
            "value": value,
            "created_at": time.time(),
            "expires_at": time.time() + (ttl if ttl is not None else self.ttl),
            "last_accessed": time.time(),
        }

    def invalidate(self, key: str) -> bool:
        """Invalidate a specific cache entry."""
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def invalidate_prefix(self, prefix: str) -> int:
        """Invalidate all entries matching a key prefix."""
        keys = [k for k in self._cache if k.startswith(prefix)]
        for k in keys:
            del self._cache[k]
        return len(keys)

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()

    def _evict_oldest(self) -> None:
        """Evict the least recently accessed entry."""
        if not self._cache:
            return

        oldest_key = min(self._cache, key=lambda k: self._cache[k]["last_accessed"])
        del self._cache[oldest_key]
        self._stats["evictions"] += 1

    @property
    def size(self) -> int:
        """Current number of cache entries."""
        return len(self._cache)

    @property
    def hit_rate(self) -> float:
        """Cache hit rate (0.0 to 1.0)."""
        total = self._stats["hits"] + self._stats["misses"]
        return self._stats["hits"] / total if total > 0 else 0.0

    def get_stats(self) -> dict:
        """Get cache statistics."""
        return {
            **self._stats,
            "size": self.size,
            "hit_rate": round(self.hit_rate, 4),
            "max_entries": self.max_entries,
            "ttl": self.ttl,
        }


class LatencyTracker:
    """Track and report query latency."""

    def __init__(self, target_ms: float = LATENCY_TARGET_MS):
        self.target_ms = target_ms
        self._measurements = []

    def measure(self, operation: str):
        """Context manager for measuring operation latency."""
        return _LatencyContext(self, operation)

    def record(self, operation: str, latency_ms: float) -> dict:
        """Record a latency measurement."""
        entry = {
            "operation": operation,
            "latency_ms": round(latency_ms, 2),
            "within_target": latency_ms <= self.target_ms,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._measurements.append(entry)

        # Keep only last 1000 measurements
        if len(self._measurements) > 1000:
            self._measurements = self._measurements[-1000:]

        return entry

    def get_report(self) -> dict:
        """Get latency report with percentiles."""
        if not self._measurements:
            return {
                "count": 0,
                "target_ms": self.target_ms,
                "within_target_pct": 0.0,
            }

        latencies = [m["latency_ms"] for m in self._measurements]
        latencies.sort()
        count = len(latencies)

        within = sum(1 for l in latencies if l <= self.target_ms)

        return {
            "count": count,
            "target_ms": self.target_ms,
            "within_target_pct": round(within / count * 100, 1),
            "avg_ms": round(sum(latencies) / count, 2),
            "min_ms": round(latencies[0], 2),
            "max_ms": round(latencies[-1], 2),
            "p50_ms": round(latencies[count // 2], 2),
            "p90_ms": round(latencies[int(count * 0.9)], 2),
            "p99_ms": round(latencies[int(count * 0.99)], 2) if count > 100 else round(latencies[-1], 2),
        }

    @property
    def measurements(self) -> list:
        """All recorded measurements."""
        return list(self._measurements)


class _LatencyContext:
    """Context manager for latency measurement."""

    def __init__(self, tracker: LatencyTracker, operation: str):
        self.tracker = tracker
        self.operation = operation
        self.start = 0.0

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *args):
        elapsed_ms = (time.time() - self.start) * 1000
        self.tracker.record(self.operation, elapsed_ms)


class BatchPromoter:
    """Batch promote operations for efficiency."""

    def __init__(self):
        self._queue = []
        self._results = []

    def enqueue(self, fact: str, category: str, project: str, score: float, summary_id: str = "") -> None:
        """Add a fact to the promotion queue."""
        self._queue.append({
            "fact": fact,
            "category": category,
            "project": project,
            "score": score,
            "summary_id": summary_id,
            "queued_at": datetime.now(timezone.utc).isoformat(),
        })

    def flush(self) -> list:
        """Flush the queue and return all queued items."""
        items = list(self._queue)
        self._queue.clear()
        return items

    @property
    def queue_size(self) -> int:
        """Number of items in the queue."""
        return len(self._queue)

    def get_results(self) -> list:
        """Get results from last flush."""
        return list(self._results)


class LazyVaultLoader:
    """Lazy-load vault notes on demand for large vaults."""

    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)
        self._index = None
        self._loaded_notes = {}

    def _build_index(self) -> dict:
        """Build an index of vault note paths without loading content."""
        if not self.vault_path.exists():
            return {}

        index = {}
        for md_file in self.vault_path.rglob("*.md"):
            rel = str(md_file.relative_to(self.vault_path))
            index[rel] = {
                "path": str(md_file),
                "stem": md_file.stem,
                "size": md_file.stat().st_size,
                "mtime": md_file.stat().st_mtime,
            }
        return index

    @property
    def index(self) -> dict:
        """Get or build the vault index."""
        if self._index is None:
            self._index = self._build_index()
        return self._index

    def get_note(self, rel_path: str) -> Optional[str]:
        """Load a single note by relative path (lazy)."""
        if rel_path in self._loaded_notes:
            return self._loaded_notes[rel_path]

        entry = self.index.get(rel_path)
        if not entry:
            return None

        try:
            content = Path(entry["path"]).read_text(encoding="utf-8", errors="replace")
            self._loaded_notes[rel_path] = content
            return content
        except OSError:
            return None

    def search(self, keyword: str) -> list:
        """Search vault index for notes matching a keyword."""
        results = []
        keyword_lower = keyword.lower()

        for rel_path, info in self.index.items():
            if keyword_lower in info["stem"].lower() or keyword_lower in rel_path.lower():
                results.append(rel_path)

        return results

    @property
    def note_count(self) -> int:
        """Number of notes in the vault."""
        return len(self.index)

    @property
    def loaded_count(self) -> int:
        """Number of notes currently loaded in memory."""
        return len(self._loaded_notes)

    def unload(self) -> None:
        """Unload all cached notes to free memory."""
        self._loaded_notes.clear()
