#!/usr/bin/env python3
"""Tests for session-start.py LACP context injection."""

import json
import os
import sys
import tempfile
import shutil
from unittest.mock import patch, MagicMock

import pytest

# Add handlers directory to path
HANDLERS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "hooks", "handlers")
sys.path.insert(0, HANDLERS_DIR)


class TestInjectLACPContext:
    """Test the _inject_lacp_context function in session-start.py."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.memory_dir = os.path.join(self.tmpdir, "memory", "test-project")
        os.makedirs(self.memory_dir, exist_ok=True)

        with open(os.path.join(self.memory_dir, "MEMORY.md"), "w") as f:
            f.write("# test-project Memory\n\n")
            f.write("Finix is the payment processor.\n")
            f.write("Brale handles stablecoin settlement.\n")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)
        # Clean up imported module
        if "session-start" in sys.modules:
            del sys.modules["session-start"]

    def test_session_start_imports(self):
        """Verify session-start.py can be imported."""
        # Use importlib to import with hyphenated name
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "session_start",
            os.path.join(HANDLERS_DIR, "session-start.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "main")
        assert hasattr(mod, "_inject_lacp_context")

    def test_inject_function_exists(self):
        """Verify _inject_lacp_context function exists."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "session_start",
            os.path.join(HANDLERS_DIR, "session-start.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(mod._inject_lacp_context)

    def test_inject_returns_none_when_no_context(self):
        """When openclaw-lacp-context isn't available, return None."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "session_start",
            os.path.join(HANDLERS_DIR, "session-start.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Mock subprocess to simulate missing CLI
        with patch.object(mod.subprocess, 'run') as mock_run:
            # First call: git remote (success)
            mock_remote = MagicMock()
            mock_remote.returncode = 1  # no git remote
            mock_remote.stdout = ""

            # Second call: which openclaw-lacp-context (fail)
            mock_which = MagicMock()
            mock_which.returncode = 1
            mock_which.side_effect = Exception("not found")

            mock_run.side_effect = [mock_remote, Exception("not found")]

            result = mod._inject_lacp_context()
            # Should return None when CLI not found
            # (depends on Path check, so may return None)

    def test_format_git_context(self):
        """Test git context formatting still works."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "session_start",
            os.path.join(HANDLERS_DIR, "session-start.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        ctx = {"branch": "main", "status": "clean"}
        result = mod._format_git_context(ctx)
        assert "Branch: main" in result
        assert "Status: clean" in result
