#!/usr/bin/env python3
"""Tests for the LCM (lossless-claw) backend — SQLite-based context engine."""

import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backends.lcm_backend import LCMBackend


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def create_test_db(path, summaries=None):
    """Create a test SQLite database with the summaries table."""
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE summaries (
            summary_id TEXT PRIMARY KEY,
            content TEXT,
            source TEXT DEFAULT 'lcm',
            citations TEXT DEFAULT '[]',
            project TEXT DEFAULT '',
            agent TEXT DEFAULT '',
            timestamp TEXT DEFAULT '',
            conversation_id TEXT DEFAULT '',
            parent_id TEXT DEFAULT '',
            tags TEXT DEFAULT '[]',
            metadata TEXT DEFAULT '{}'
        )
    """)
    for s in (summaries or []):
        conn.execute(
            "INSERT INTO summaries VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                s.get("summary_id", ""),
                s.get("content", ""),
                s.get("source", "lcm"),
                json.dumps(s.get("citations", [])),
                s.get("project", ""),
                s.get("agent", ""),
                s.get("timestamp", ""),
                s.get("conversation_id", ""),
                s.get("parent_id", ""),
                json.dumps(s.get("tags", [])),
                json.dumps(s.get("metadata", {})),
            ),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

class TestLCMBackendInit:
    """Constructor and config handling."""

    def test_init_with_defaults(self):
        backend = LCMBackend({})
        assert backend._batch_size == 50
        assert backend._threshold == 70

    def test_init_with_custom_db_path(self, tmp_path):
        db_path = str(tmp_path / "custom.db")
        backend = LCMBackend({"lcmDbPath": db_path})
        assert str(backend._db_path) == db_path

    def test_init_with_custom_batch_size(self):
        backend = LCMBackend({"lcmQueryBatchSize": 100})
        assert backend._batch_size == 100

    def test_init_with_custom_threshold(self):
        backend = LCMBackend({"promotionThreshold": 85})
        assert backend._threshold == 85


# ---------------------------------------------------------------------------
# backend_name / is_available
# ---------------------------------------------------------------------------

class TestLCMBackendIdentity:
    """backend_name and is_available checks."""

    def test_backend_name(self):
        assert LCMBackend({}).backend_name() == "lossless-claw"

    def test_is_available_with_valid_db(self, tmp_path):
        db = tmp_path / "lcm.db"
        create_test_db(db)
        backend = LCMBackend({"lcmDbPath": str(db)})
        assert backend.is_available() is True

    def test_is_available_missing_db(self):
        backend = LCMBackend({"lcmDbPath": "/nonexistent/lcm.db"})
        assert backend.is_available() is False

    def test_is_available_no_summaries_table(self, tmp_path):
        db = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE other (id TEXT)")
        conn.commit()
        conn.close()
        backend = LCMBackend({"lcmDbPath": str(db)})
        assert backend.is_available() is False


# ---------------------------------------------------------------------------
# fetch_summary
# ---------------------------------------------------------------------------

class TestFetchSummary:
    """fetch_summary reads a single row by ID."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.db = tmp_path / "lcm.db"
        create_test_db(
            self.db,
            [
                {
                    "summary_id": "sum-001",
                    "content": "Treasury settlement design",
                    "project": "easy-api",
                    "timestamp": "2026-03-18T10:00:00Z",
                    "tags": ["treasury", "settlement"],
                    "metadata": {"score": 95},
                },
            ],
        )
        self.backend = LCMBackend({"lcmDbPath": str(self.db)})

    def test_returns_dict_for_existing_id(self):
        result = self.backend.fetch_summary("sum-001")
        assert isinstance(result, dict)
        assert result["summary_id"] == "sum-001"
        assert result["content"] == "Treasury settlement design"

    def test_returns_empty_dict_for_missing_id(self):
        result = self.backend.fetch_summary("no-such-id")
        assert result == {}

    def test_parses_json_fields(self):
        result = self.backend.fetch_summary("sum-001")
        assert result["tags"] == ["treasury", "settlement"]
        assert result["metadata"] == {"score": 95}

    def test_handles_db_error_gracefully(self, tmp_path):
        backend = LCMBackend({"lcmDbPath": "/nonexistent/lcm.db"})
        result = backend.fetch_summary("sum-001")
        assert result == {}


# ---------------------------------------------------------------------------
# discover_summaries
# ---------------------------------------------------------------------------

class TestDiscoverSummaries:
    """discover_summaries with various filter combinations."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.db = tmp_path / "lcm.db"
        create_test_db(
            self.db,
            [
                {
                    "summary_id": "s1",
                    "content": "Alpha",
                    "project": "easy-api",
                    "timestamp": "2026-03-10T10:00:00Z",
                    "conversation_id": "conv-a",
                },
                {
                    "summary_id": "s2",
                    "content": "Beta",
                    "project": "easy-checkout",
                    "timestamp": "2026-03-15T10:00:00Z",
                    "conversation_id": "conv-b",
                },
                {
                    "summary_id": "s3",
                    "content": "Gamma",
                    "project": "easy-api",
                    "timestamp": "2026-03-18T10:00:00Z",
                    "conversation_id": "conv-a",
                },
            ],
        )
        self.backend = LCMBackend({"lcmDbPath": str(self.db)})

    def test_no_filters(self):
        results = self.backend.discover_summaries({})
        assert len(results) == 3

    def test_filtered_by_since(self):
        results = self.backend.discover_summaries({"since": "2026-03-14"})
        ids = {r["summary_id"] for r in results}
        assert "s1" not in ids
        assert "s2" in ids
        assert "s3" in ids

    def test_filtered_by_until(self):
        results = self.backend.discover_summaries({"until": "2026-03-12"})
        ids = {r["summary_id"] for r in results}
        assert ids == {"s1"}

    def test_filtered_by_project(self):
        results = self.backend.discover_summaries({"project": "easy-api"})
        assert all(r["project"] == "easy-api" for r in results)
        assert len(results) == 2

    def test_filtered_by_conversation_id(self):
        results = self.backend.discover_summaries({"conversation_id": "conv-a"})
        assert len(results) == 2
        assert all(r["conversation_id"] == "conv-a" for r in results)

    def test_respects_limit(self):
        results = self.backend.discover_summaries({"limit": 1})
        assert len(results) == 1

    def test_returns_empty_list_on_db_error(self):
        backend = LCMBackend({"lcmDbPath": "/nonexistent/lcm.db"})
        assert backend.discover_summaries({}) == []

    def test_sorted_by_timestamp_descending(self):
        results = self.backend.discover_summaries({})
        timestamps = [r["timestamp"] for r in results]
        assert timestamps == sorted(timestamps, reverse=True)


# ---------------------------------------------------------------------------
# find_context
# ---------------------------------------------------------------------------

class TestFindContext:
    """find_context keyword search and scoring."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.db = tmp_path / "lcm.db"
        create_test_db(
            self.db,
            [
                {
                    "summary_id": "ctx1",
                    "content": "Deploy the treasury settlement flow for Brale integration",
                    "project": "easy-api",
                    "timestamp": "2026-03-18T10:00:00Z",
                },
                {
                    "summary_id": "ctx2",
                    "content": "Unrelated topic about marketing campaigns",
                    "project": "marketing",
                    "timestamp": "2026-03-17T10:00:00Z",
                },
                {
                    "summary_id": "ctx3",
                    "content": "Treasury settlement test cases and validation",
                    "project": "easy-api",
                    "timestamp": "2026-03-16T10:00:00Z",
                },
            ],
        )
        self.backend = LCMBackend({"lcmDbPath": str(self.db)})

    def test_finds_matching_keywords(self):
        results = self.backend.find_context("treasury settlement")
        assert len(results) >= 1
        ids = {r["summary_id"] for r in results}
        assert "ctx1" in ids

    def test_no_matches(self):
        results = self.backend.find_context("quantum computing blockchain")
        assert results == []

    def test_with_project_filter(self):
        results = self.backend.find_context("treasury", project="easy-api")
        assert all(r.get("project") == "easy-api" for r in results)

    def test_scores_by_keyword_overlap(self):
        results = self.backend.find_context("treasury settlement")
        # ctx1 and ctx3 both have treasury and settlement; ctx2 has neither
        ids = {r["summary_id"] for r in results}
        assert "ctx2" not in ids

    def test_respects_limit(self):
        results = self.backend.find_context("treasury settlement", limit=1)
        assert len(results) <= 1

    def test_handles_missing_db(self):
        backend = LCMBackend({"lcmDbPath": "/nonexistent/lcm.db"})
        results = backend.find_context("anything")
        assert results == []

    def test_relevance_score_present(self):
        results = self.backend.find_context("treasury settlement")
        for r in results:
            assert "relevance_score" in r
            assert isinstance(r["relevance_score"], float)

    def test_source_is_lossless_claw(self):
        results = self.backend.find_context("treasury")
        for r in results:
            assert r["source"] == "lossless-claw"


# ---------------------------------------------------------------------------
# traverse_dag
# ---------------------------------------------------------------------------

class TestTraverseDag:
    """traverse_dag parent-chain walking."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.db = tmp_path / "lcm.db"
        create_test_db(
            self.db,
            [
                {"summary_id": "root", "content": "Root node", "parent_id": ""},
                {"summary_id": "child", "content": "Child node", "parent_id": "root"},
                {"summary_id": "grandchild", "content": "Grandchild", "parent_id": "child"},
                {"summary_id": "loop", "content": "Self-loop", "parent_id": "loop"},
            ],
        )
        self.backend = LCMBackend({"lcmDbPath": str(self.db)})

    def test_single_node(self):
        result = self.backend.traverse_dag("root")
        assert len(result["chain"]) == 1
        assert result["root"]["summary_id"] == "root"

    def test_follows_parent_chain(self):
        result = self.backend.traverse_dag("grandchild", depth=5)
        ids = [s["summary_id"] for s in result["chain"]]
        assert ids == ["grandchild", "child", "root"]
        assert result["root"]["summary_id"] == "root"
        assert result["depth_reached"] == 3

    def test_respects_depth_limit(self):
        result = self.backend.traverse_dag("grandchild", depth=1)
        assert len(result["chain"]) == 1
        assert result["depth_reached"] == 1

    def test_handles_missing_summary(self):
        result = self.backend.traverse_dag("no-such-id")
        assert result["chain"] == []
        assert result["root"] == {}
        assert result["depth_reached"] == 0

    def test_handles_circular_reference(self):
        result = self.backend.traverse_dag("loop", depth=10)
        assert len(result["chain"]) == 1
        assert result["depth_reached"] == 1

    def test_default_depth_is_3(self):
        result = self.backend.traverse_dag("grandchild")
        # depth=3 is enough for grandchild->child->root
        assert len(result["chain"]) == 3


# ---------------------------------------------------------------------------
# _extract_keywords
# ---------------------------------------------------------------------------

class TestExtractKeywords:
    """Private _extract_keywords helper."""

    def setup_method(self):
        self.backend = LCMBackend({})

    def test_filters_stopwords(self):
        keywords = self.backend._extract_keywords("the quick brown fox is very fast")
        assert "the" not in keywords
        assert "is" not in keywords
        assert "very" not in keywords
        assert "quick" in keywords
        assert "brown" in keywords

    def test_empty_input(self):
        assert self.backend._extract_keywords("") == []

    def test_short_words_filtered(self):
        keywords = self.backend._extract_keywords("ab cd ef ghi")
        assert "ab" not in keywords
        assert "cd" not in keywords
        assert "ghi" in keywords

    def test_lowercased(self):
        keywords = self.backend._extract_keywords("Treasury Settlement")
        assert "treasury" in keywords
        assert "settlement" in keywords


# ---------------------------------------------------------------------------
# _row_to_dict
# ---------------------------------------------------------------------------

class TestRowToDict:
    """Private _row_to_dict helper."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.db = tmp_path / "lcm.db"
        create_test_db(
            self.db,
            [
                {
                    "summary_id": "dict-test",
                    "content": "Test content",
                    "citations": ["ref1", "ref2"],
                    "tags": ["tag1"],
                    "metadata": {"key": "value"},
                },
            ],
        )
        self.backend = LCMBackend({"lcmDbPath": str(self.db)})

    def test_parses_json_fields(self):
        result = self.backend.fetch_summary("dict-test")
        assert result["citations"] == ["ref1", "ref2"]
        assert result["tags"] == ["tag1"]
        assert result["metadata"] == {"key": "value"}

    def test_handles_invalid_json_gracefully(self, tmp_path):
        db = tmp_path / "bad.db"
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE summaries (
                summary_id TEXT PRIMARY KEY,
                content TEXT,
                source TEXT DEFAULT 'lcm',
                citations TEXT DEFAULT '[]',
                project TEXT DEFAULT '',
                agent TEXT DEFAULT '',
                timestamp TEXT DEFAULT '',
                conversation_id TEXT DEFAULT '',
                parent_id TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}'
            )
        """)
        conn.execute(
            "INSERT INTO summaries VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("bad-json", "content", "lcm", "not-valid-json", "", "", "", "", "", "[", "{"),
        )
        conn.commit()
        conn.close()

        backend = LCMBackend({"lcmDbPath": str(db)})
        result = backend.fetch_summary("bad-json")
        # Should not crash; invalid JSON fields remain as strings
        assert result["summary_id"] == "bad-json"
        assert result["citations"] == "not-valid-json"
