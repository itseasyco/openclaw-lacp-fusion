#!/usr/bin/env python3
"""Tests for the File backend — file-based context engine (default fallback)."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backends.file_backend import FileBackend


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

class TestFileBackendInit:
    """Constructor and config handling."""

    def test_init_with_defaults(self):
        backend = FileBackend({})
        assert backend._threshold == 70
        assert backend._files == []

    def test_init_with_custom_paths(self, tmp_path):
        vault = tmp_path / "vault"
        memory = tmp_path / "memory"
        backend = FileBackend({
            "vaultPath": str(vault),
            "memoryRoot": str(memory),
            "promotionThreshold": 80,
            "files": ["/some/file.md"],
        })
        assert str(backend._vault_path) == str(vault)
        assert str(backend._memory_root) == str(memory)
        assert backend._threshold == 80
        assert backend._files == ["/some/file.md"]


# ---------------------------------------------------------------------------
# backend_name / is_available
# ---------------------------------------------------------------------------

class TestFileBackendIdentity:
    """backend_name and is_available."""

    def test_backend_name(self):
        assert FileBackend({}).backend_name() == "file"

    def test_is_available_always_true(self):
        assert FileBackend({}).is_available() is True

    def test_is_available_true_even_with_bad_paths(self):
        backend = FileBackend({"vaultPath": "/nonexistent", "memoryRoot": "/nonexistent"})
        assert backend.is_available() is True


# ---------------------------------------------------------------------------
# fetch_summary
# ---------------------------------------------------------------------------

class TestFetchSummary:
    """fetch_summary searches explicit files, memory root, and vault."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        # Set up memory root with an md file containing a summary ID
        self.memory = tmp_path / "memory"
        self.memory.mkdir()
        (self.memory / "session-abc.md").write_text(
            "# Session ABC\nThis is summary SUM-MEMORY-001.\n"
        )

        # Set up vault
        self.vault = tmp_path / "vault"
        self.vault.mkdir()
        (self.vault / "note.md").write_text("Vault note referencing SUM-VAULT-001 here.\n")

        # Set up a JSON file in memory
        (self.memory / "sum.json").write_text(
            json.dumps({"summary_id": "SUM-JSON-001", "content": "JSON summary"})
        )

        # Set up explicit file
        self.explicit = tmp_path / "explicit.md"
        self.explicit.write_text("Explicit file with SUM-EXPLICIT-001.\n")

        self.backend = FileBackend({
            "memoryRoot": str(self.memory),
            "vaultPath": str(self.vault),
            "files": [str(self.explicit)],
        })

    def test_finds_in_explicit_files(self):
        result = self.backend.fetch_summary("SUM-EXPLICIT-001")
        assert result != {}
        assert result["summary_id"] == "SUM-EXPLICIT-001"

    def test_finds_in_memory_root(self):
        result = self.backend.fetch_summary("SUM-MEMORY-001")
        assert result != {}
        assert result["summary_id"] == "SUM-MEMORY-001"

    def test_finds_in_vault(self):
        result = self.backend.fetch_summary("SUM-VAULT-001")
        assert result != {}
        assert result["summary_id"] == "SUM-VAULT-001"

    def test_returns_empty_when_not_found(self):
        result = self.backend.fetch_summary("NO-SUCH-SUMMARY")
        assert result == {}

    def test_finds_json_summary_by_id(self):
        result = self.backend.fetch_summary("SUM-JSON-001")
        assert result != {}
        assert result["summary_id"] == "SUM-JSON-001"


# ---------------------------------------------------------------------------
# discover_summaries
# ---------------------------------------------------------------------------

class TestDiscoverSummaries:
    """discover_summaries from various sources with filters."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.memory = tmp_path / "memory"
        self.memory.mkdir()

        # Create project sub-dir
        proj = self.memory / "easy-api"
        proj.mkdir()

        # JSON summaries with timestamps
        (proj / "s1.json").write_text(json.dumps({
            "summary_id": "s1",
            "content": "First summary",
            "timestamp": "2026-03-10T10:00:00Z",
        }))
        (proj / "s2.json").write_text(json.dumps({
            "summary_id": "s2",
            "content": "Second summary",
            "timestamp": "2026-03-18T10:00:00Z",
        }))

        # An md file in memory root
        (self.memory / "general.md").write_text(
            "# General Notes\n\nSome substantial content for testing discovery.\n"
        )

        self.vault = tmp_path / "vault"
        self.vault.mkdir()
        (self.vault / "vault-note.md").write_text(
            "# Vault Note\n\nSubstantial vault content that should be discovered.\n"
        )

        self.backend = FileBackend({
            "memoryRoot": str(self.memory),
            "vaultPath": str(self.vault),
            "files": [],
        })

    def test_from_memory_root(self):
        results = self.backend.discover_summaries({})
        assert len(results) >= 1

    def test_filtered_by_project(self):
        results = self.backend.discover_summaries({"project": "easy-api"})
        # Should include at least the json files from the project dir
        ids = {r.get("summary_id") for r in results}
        assert "s1" in ids or "s2" in ids

    def test_filtered_by_since(self):
        results = self.backend.discover_summaries({"since": "2026-03-15"})
        for r in results:
            ts = r.get("timestamp", "")
            if ts:
                assert ts >= "2026-03-15"

    def test_filtered_by_until(self):
        results = self.backend.discover_summaries({"until": "2026-03-12"})
        for r in results:
            ts = r.get("timestamp", "")
            if ts:
                assert ts <= "2026-03-12"

    def test_from_json_files(self):
        results = self.backend.discover_summaries({})
        ids = {r.get("summary_id") for r in results}
        assert "s1" in ids or "s2" in ids

    def test_deduplicates(self):
        results = self.backend.discover_summaries({})
        ids = [r.get("summary_id") for r in results if r.get("summary_id")]
        assert len(ids) == len(set(ids))

    def test_respects_limit(self):
        results = self.backend.discover_summaries({"limit": 1})
        assert len(results) <= 1

    def test_sorted_by_timestamp_descending(self):
        results = self.backend.discover_summaries({})
        timestamps = [r.get("timestamp", "") for r in results]
        assert timestamps == sorted(timestamps, reverse=True)


# ---------------------------------------------------------------------------
# find_context
# ---------------------------------------------------------------------------

class TestFindContext:
    """find_context keyword-based search."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.memory = tmp_path / "memory"
        self.memory.mkdir()
        (self.memory / "treasury.md").write_text(
            "# Treasury Design\n\nSettlement flow for Brale integration and Finix payments.\n"
        )
        (self.memory / "marketing.md").write_text(
            "# Marketing Plan\n\nSocial media campaigns and content strategy.\n"
        )

        self.vault = tmp_path / "vault"
        self.vault.mkdir()

        self.backend = FileBackend({
            "memoryRoot": str(self.memory),
            "vaultPath": str(self.vault),
            "files": [],
        })

    def test_finds_keyword_matches(self):
        results = self.backend.find_context("treasury settlement")
        assert len(results) >= 1
        ids = {r["summary_id"] for r in results}
        assert "treasury" in ids

    def test_respects_project_filter(self, tmp_path):
        proj = self.memory / "easy-api"
        proj.mkdir()
        (proj / "deploy.md").write_text(
            "# Deploy Notes\n\nTreasury deployment instructions for settlement.\n"
        )
        backend = FileBackend({
            "memoryRoot": str(self.memory),
            "vaultPath": str(self.vault),
            "files": [],
        })
        results = backend.find_context("treasury", project="easy-api")
        assert len(results) >= 1

    def test_respects_limit(self):
        results = self.backend.find_context("treasury settlement", limit=1)
        assert len(results) <= 1

    def test_no_matches(self):
        results = self.backend.find_context("quantum blockchain")
        assert results == []

    def test_relevance_score_present(self):
        results = self.backend.find_context("treasury settlement")
        for r in results:
            assert "relevance_score" in r
            assert isinstance(r["relevance_score"], float)

    def test_source_is_file(self):
        results = self.backend.find_context("treasury")
        for r in results:
            assert r["source"] == "file"

    def test_sorted_by_score_descending(self):
        results = self.backend.find_context("treasury settlement Brale Finix")
        if len(results) >= 2:
            scores = [r["relevance_score"] for r in results]
            assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# traverse_dag
# ---------------------------------------------------------------------------

class TestTraverseDag:
    """File backend traverse_dag returns single-node chain."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.memory = tmp_path / "memory"
        self.memory.mkdir()
        (self.memory / "note.md").write_text(
            "# Note\n\nContent referencing SUM-TRAV-001 for testing.\n"
        )
        self.backend = FileBackend({
            "memoryRoot": str(self.memory),
            "vaultPath": str(tmp_path / "vault"),
            "files": [],
        })

    def test_returns_single_node_chain(self):
        result = self.backend.traverse_dag("SUM-TRAV-001")
        assert len(result["chain"]) == 1
        assert result["depth_reached"] == 1
        assert result["root"] != {}

    def test_returns_empty_for_missing(self):
        result = self.backend.traverse_dag("NONEXISTENT")
        assert result["chain"] == []
        assert result["root"] == {}
        assert result["depth_reached"] == 0

    def test_result_has_required_keys(self):
        result = self.backend.traverse_dag("SUM-TRAV-001")
        assert "root" in result
        assert "chain" in result
        assert "depth_reached" in result


# ---------------------------------------------------------------------------
# _extract_keywords
# ---------------------------------------------------------------------------

class TestExtractKeywords:
    """Private _extract_keywords helper."""

    def setup_method(self):
        self.backend = FileBackend({})

    def test_works_correctly(self):
        keywords = self.backend._extract_keywords("deploy the treasury settlement")
        assert "deploy" in keywords
        assert "treasury" in keywords
        assert "settlement" in keywords
        assert "the" not in keywords

    def test_empty_input(self):
        assert self.backend._extract_keywords("") == []

    def test_short_words_filtered(self):
        keywords = self.backend._extract_keywords("ab cd treasury")
        assert "ab" not in keywords
        assert "treasury" in keywords


# ---------------------------------------------------------------------------
# _load_json_file
# ---------------------------------------------------------------------------

class TestLoadJsonFile:
    """Private _load_json_file helper."""

    def setup_method(self):
        self.backend = FileBackend({})

    def test_loads_valid_json(self, tmp_path):
        f = tmp_path / "valid.json"
        f.write_text(json.dumps({"key": "value"}))
        result = self.backend._load_json_file(str(f))
        assert result == {"key": "value"}

    def test_handles_invalid_json(self, tmp_path):
        f = tmp_path / "invalid.json"
        f.write_text("not json at all {{{")
        result = self.backend._load_json_file(str(f))
        assert result == {}

    def test_handles_missing_file(self):
        result = self.backend._load_json_file("/nonexistent/file.json")
        assert result == {}

    def test_handles_non_dict_json(self, tmp_path):
        f = tmp_path / "array.json"
        f.write_text(json.dumps([1, 2, 3]))
        result = self.backend._load_json_file(str(f))
        assert result == {}


# ---------------------------------------------------------------------------
# _parse_md_as_summary
# ---------------------------------------------------------------------------

class TestParseMdAsSummary:
    """Private _parse_md_as_summary helper."""

    def setup_method(self):
        self.backend = FileBackend({})

    def test_parses_valid_md(self, tmp_path):
        f = tmp_path / "note.md"
        f.write_text("# Title\n\nSome content that is long enough to pass the minimum.\n")
        result = self.backend._parse_md_as_summary(str(f))
        assert result != {}
        assert result["summary_id"] == "note"
        assert result["source"] == "file"
        assert "timestamp" in result

    def test_skips_short_content(self, tmp_path):
        f = tmp_path / "tiny.md"
        f.write_text("hi")
        result = self.backend._parse_md_as_summary(str(f))
        assert result == {}

    def test_handles_missing_file(self):
        result = self.backend._parse_md_as_summary("/nonexistent/file.md")
        assert result == {}

    def test_content_truncated_to_2000(self, tmp_path):
        f = tmp_path / "long.md"
        f.write_text("x" * 5000)
        result = self.backend._parse_md_as_summary(str(f))
        assert len(result["content"]) <= 2000
