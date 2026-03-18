#!/usr/bin/env python3
"""Tests for the backend abstraction layer — interface contract and factory."""

import os
import sys
from abc import ABC
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backends import ContextBackend, get_backend
from backends.lcm_backend import LCMBackend
from backends.file_backend import FileBackend


# ---------------------------------------------------------------------------
# Subclass checks
# ---------------------------------------------------------------------------

class TestSubclassRelationship:
    """Both backends must be proper subclasses of ContextBackend."""

    def test_context_backend_is_abstract(self):
        assert issubclass(ContextBackend, ABC)

    def test_lcm_backend_is_subclass(self):
        assert issubclass(LCMBackend, ContextBackend)

    def test_file_backend_is_subclass(self):
        assert issubclass(FileBackend, ContextBackend)

    def test_cannot_instantiate_context_backend(self):
        with pytest.raises(TypeError):
            ContextBackend()


# ---------------------------------------------------------------------------
# Abstract method presence
# ---------------------------------------------------------------------------

class TestAbstractMethods:
    """Both backends must implement every abstract method."""

    REQUIRED_METHODS = [
        "fetch_summary",
        "discover_summaries",
        "find_context",
        "traverse_dag",
        "backend_name",
        "is_available",
    ]

    @pytest.mark.parametrize("method_name", REQUIRED_METHODS)
    def test_lcm_backend_has_method(self, method_name):
        assert callable(getattr(LCMBackend, method_name, None))

    @pytest.mark.parametrize("method_name", REQUIRED_METHODS)
    def test_file_backend_has_method(self, method_name):
        assert callable(getattr(FileBackend, method_name, None))


# ---------------------------------------------------------------------------
# get_backend factory
# ---------------------------------------------------------------------------

class TestGetBackendFactory:
    """Tests for the get_backend() config-driven factory."""

    @patch("backends.lcm_backend.LCMBackend.is_available", return_value=True)
    def test_returns_lcm_backend_for_lossless_claw(self, _mock_avail):
        backend = get_backend({"contextEngine": "lossless-claw"})
        assert isinstance(backend, LCMBackend)

    def test_returns_file_backend_for_none_engine(self):
        backend = get_backend({"contextEngine": None})
        assert isinstance(backend, FileBackend)

    def test_returns_file_backend_for_missing_engine(self):
        backend = get_backend({})
        assert isinstance(backend, FileBackend)

    @patch("backends.lcm_backend.LCMBackend.is_available", return_value=False)
    def test_raises_value_error_when_lcm_unavailable(self, _mock_avail):
        with pytest.raises(ValueError, match="lossless-claw backend requested"):
            get_backend({"contextEngine": "lossless-claw"})

    def test_file_backend_never_raises(self):
        backend = get_backend({"contextEngine": None, "vaultPath": "/nonexistent"})
        assert isinstance(backend, FileBackend)


# ---------------------------------------------------------------------------
# backend_name
# ---------------------------------------------------------------------------

class TestBackendNames:
    """backend_name() must return the expected identifier string."""

    def test_lcm_backend_name(self):
        backend = LCMBackend({})
        assert backend.backend_name() == "lossless-claw"

    def test_file_backend_name(self):
        backend = FileBackend({})
        assert backend.backend_name() == "file"


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------

class TestIsAvailable:
    """Basic is_available() contract checks."""

    def test_file_backend_always_available(self):
        backend = FileBackend({})
        assert backend.is_available() is True

    def test_lcm_backend_unavailable_without_db(self):
        backend = LCMBackend({"lcmDbPath": "/nonexistent/lcm.db"})
        assert backend.is_available() is False


# ---------------------------------------------------------------------------
# Interface consistency — return types
# ---------------------------------------------------------------------------

class TestInterfaceConsistency:
    """Both backends should return the same types for the same operations."""

    def test_fetch_summary_returns_dict(self):
        fb = FileBackend({"files": [], "memoryRoot": "/nonexistent", "vaultPath": "/nonexistent"})
        result = fb.fetch_summary("no-such-id")
        assert isinstance(result, dict)

    def test_discover_summaries_returns_list(self):
        fb = FileBackend({"files": [], "memoryRoot": "/nonexistent", "vaultPath": "/nonexistent"})
        result = fb.discover_summaries({})
        assert isinstance(result, list)

    def test_find_context_returns_list(self):
        fb = FileBackend({"files": [], "memoryRoot": "/nonexistent", "vaultPath": "/nonexistent"})
        result = fb.find_context("deploy treasury")
        assert isinstance(result, list)

    def test_traverse_dag_returns_dict(self):
        fb = FileBackend({"files": [], "memoryRoot": "/nonexistent", "vaultPath": "/nonexistent"})
        result = fb.traverse_dag("no-such-id")
        assert isinstance(result, dict)
        assert "root" in result
        assert "chain" in result
        assert "depth_reached" in result
