"""Tests for openclaw-lacp-context CLI — LACP context injection."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
BIN_DIR = REPO_ROOT / "plugin" / "bin"
CONTEXT_SCRIPT = BIN_DIR / "openclaw-lacp-context"


class TestContextScriptExists:
    """Verify the CLI script exists and is executable."""

    def test_script_exists(self):
        assert CONTEXT_SCRIPT.exists()

    def test_script_is_executable(self):
        assert os.access(CONTEXT_SCRIPT, os.X_OK)

    def test_script_has_shebang(self):
        content = CONTEXT_SCRIPT.read_text()
        assert content.startswith("#!/usr/bin/env bash")


class TestContextHelp:
    """Test --help output."""

    def test_help_flag(self):
        result = subprocess.run(
            [str(CONTEXT_SCRIPT), "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "openclaw-lacp-context" in result.stdout
        assert "COMMANDS:" in result.stdout

    def test_help_shows_commands(self):
        result = subprocess.run(
            [str(CONTEXT_SCRIPT), "--help"],
            capture_output=True, text=True, timeout=10,
        )
        for cmd in ["inject", "query", "list"]:
            assert cmd in result.stdout

    def test_version_flag(self):
        result = subprocess.run(
            [str(CONTEXT_SCRIPT), "--version"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "2.0.0" in result.stdout


class TestContextInject:
    """Test the inject command."""

    def test_inject_requires_project(self):
        result = subprocess.run(
            [str(CONTEXT_SCRIPT), "inject"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode != 0

    def test_inject_with_empty_vault(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = os.environ.copy()
            env["OPENCLAW_MEMORY_ROOT"] = str(Path(tmpdir) / "memory")
            env["OPENCLAW_VAULT_ROOT"] = str(Path(tmpdir) / "vault")

            result = subprocess.run(
                [str(CONTEXT_SCRIPT), "inject", "--project", "test-project"],
                capture_output=True, text=True, timeout=10, env=env,
            )
            assert result.returncode == 0

    def test_inject_finds_memory_facts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Set up memory with facts
            memory_dir = Path(tmpdir) / "memory" / "test-project"
            memory_dir.mkdir(parents=True)
            (memory_dir / "MEMORY.md").write_text(
                "# Test Project\n\n"
                "PostgreSQL is the primary database for all services.\n"
                "FastAPI handles the API layer with Pydantic validation.\n"
            )

            env = os.environ.copy()
            env["OPENCLAW_MEMORY_ROOT"] = str(Path(tmpdir) / "memory")
            env["OPENCLAW_VAULT_ROOT"] = str(Path(tmpdir) / "vault")

            result = subprocess.run(
                [str(CONTEXT_SCRIPT), "inject", "--project", "test-project"],
                capture_output=True, text=True, timeout=10, env=env,
            )
            assert result.returncode == 0
            assert "PostgreSQL" in result.stdout or "Injecting" in result.stdout

    def test_inject_with_topic_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_dir = Path(tmpdir) / "memory" / "test-project"
            memory_dir.mkdir(parents=True)
            (memory_dir / "MEMORY.md").write_text(
                "# Test Project\n\n"
                "PostgreSQL is the primary database.\n"
                "Redis is used for caching.\n"
                "Settlement uses Brale infrastructure.\n"
            )

            env = os.environ.copy()
            env["OPENCLAW_MEMORY_ROOT"] = str(Path(tmpdir) / "memory")
            env["OPENCLAW_VAULT_ROOT"] = str(Path(tmpdir) / "vault")

            result = subprocess.run(
                [str(CONTEXT_SCRIPT), "inject", "--project", "test-project", "--topic", "database"],
                capture_output=True, text=True, timeout=10, env=env,
            )
            assert result.returncode == 0

    def test_inject_json_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_dir = Path(tmpdir) / "memory" / "test-project"
            memory_dir.mkdir(parents=True)
            (memory_dir / "MEMORY.md").write_text(
                "# Test\n\nFact about architecture and database design.\n"
            )

            env = os.environ.copy()
            env["OPENCLAW_MEMORY_ROOT"] = str(Path(tmpdir) / "memory")
            env["OPENCLAW_VAULT_ROOT"] = str(Path(tmpdir) / "vault")

            result = subprocess.run(
                [str(CONTEXT_SCRIPT), "inject", "--project", "test-project", "--format", "json"],
                capture_output=True, text=True, timeout=10, env=env,
            )
            assert result.returncode == 0

    def test_inject_markdown_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_dir = Path(tmpdir) / "memory" / "test-project"
            memory_dir.mkdir(parents=True)
            (memory_dir / "MEMORY.md").write_text(
                "# Test\n\nFact about infrastructure and deployment process.\n"
            )

            env = os.environ.copy()
            env["OPENCLAW_MEMORY_ROOT"] = str(Path(tmpdir) / "memory")
            env["OPENCLAW_VAULT_ROOT"] = str(Path(tmpdir) / "vault")

            result = subprocess.run(
                [str(CONTEXT_SCRIPT), "inject", "--project", "test-project", "--format", "markdown"],
                capture_output=True, text=True, timeout=10, env=env,
            )
            assert result.returncode == 0


class TestContextQuery:
    """Test the query command."""

    def test_query_requires_topic(self):
        result = subprocess.run(
            [str(CONTEXT_SCRIPT), "query"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode != 0

    def test_query_with_topic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_dir = Path(tmpdir) / "memory" / "test-project"
            memory_dir.mkdir(parents=True)
            (memory_dir / "MEMORY.md").write_text(
                "# Test\n\nSettlement processing uses Brale.\n"
            )

            env = os.environ.copy()
            env["OPENCLAW_MEMORY_ROOT"] = str(Path(tmpdir) / "memory")
            env["OPENCLAW_VAULT_ROOT"] = str(Path(tmpdir) / "vault")

            result = subprocess.run(
                [str(CONTEXT_SCRIPT), "query", "--topic", "settlement"],
                capture_output=True, text=True, timeout=10, env=env,
            )
            assert result.returncode == 0


class TestContextList:
    """Test the list command."""

    def test_list_requires_project(self):
        result = subprocess.run(
            [str(CONTEXT_SCRIPT), "list"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode != 0

    def test_list_with_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = os.environ.copy()
            env["OPENCLAW_MEMORY_ROOT"] = str(Path(tmpdir) / "memory")
            env["OPENCLAW_VAULT_ROOT"] = str(Path(tmpdir) / "vault")

            result = subprocess.run(
                [str(CONTEXT_SCRIPT), "list", "--project", "test-project"],
                capture_output=True, text=True, timeout=10, env=env,
            )
            assert result.returncode == 0
            assert "Layer 1" in result.stdout or "Layer 2" in result.stdout

    def test_list_with_initialized_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_dir = Path(tmpdir) / "memory" / "my-project"
            memory_dir.mkdir(parents=True)
            (memory_dir / "MEMORY.md").write_text("# My Project\n\nSome facts.\n")

            vault_dir = Path(tmpdir) / "vault" / "my-project"
            vault_dir.mkdir(parents=True)
            (vault_dir / "note.md").write_text("# Note\n\nSome vault note.\n")

            env = os.environ.copy()
            env["OPENCLAW_MEMORY_ROOT"] = str(Path(tmpdir) / "memory")
            env["OPENCLAW_VAULT_ROOT"] = str(Path(tmpdir) / "vault")

            result = subprocess.run(
                [str(CONTEXT_SCRIPT), "list", "--project", "my-project"],
                capture_output=True, text=True, timeout=10, env=env,
            )
            assert result.returncode == 0
            assert "1" in result.stdout  # Should show file counts
