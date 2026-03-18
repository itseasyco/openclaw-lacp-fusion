#!/usr/bin/env python3
"""Tests for openclaw-memory-status CLI."""

import json
import os
import subprocess
import tempfile
import shutil

import pytest

BIN_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "bin")
STATUS_CMD = os.path.join(BIN_DIR, "openclaw-memory-status")


def run_cmd(args, env_override=None):
    """Run the CLI command and return result."""
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    result = subprocess.run(
        [STATUS_CMD] + args,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    return result


class TestStatusHelp:
    """Test help and version."""

    def test_help(self):
        result = run_cmd(["--help"])
        assert result.returncode == 0
        assert "openclaw-memory-status" in result.stdout

    def test_version(self):
        result = run_cmd(["--version"])
        assert "2.0.0" in result.stdout


class TestStatusDashboard:
    """Test the dashboard output."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.env = {
            "OPENCLAW_MEMORY_ROOT": os.path.join(self.tmpdir, "memory"),
            "OPENCLAW_VAULT_ROOT": os.path.join(self.tmpdir, "vault"),
            "OPENCLAW_PROMOTIONS_LOG": os.path.join(self.tmpdir, "logs", "promotions.jsonl"),
            "OPENCLAW_GATED_RUNS_LOG": os.path.join(self.tmpdir, "logs", "gated-runs.jsonl"),
            "OPENCLAW_CACHE_DIR": os.path.join(self.tmpdir, "cache"),
        }

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_empty_dashboard(self):
        result = run_cmd([], env_override=self.env)
        assert result.returncode == 0

    def test_with_vault_data(self):
        vault_dir = os.path.join(self.tmpdir, "vault")
        os.makedirs(vault_dir, exist_ok=True)
        with open(os.path.join(vault_dir, "test.md"), "w") as f:
            f.write("# Test\n[[link]]\n")

        result = run_cmd([], env_override=self.env)
        assert result.returncode == 0

    def test_with_promotions_log(self):
        log_dir = os.path.join(self.tmpdir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "promotions.jsonl"), "w") as f:
            f.write(json.dumps({"summary_id": "s1", "score": 85, "category": "arch", "timestamp": "2026-03-18T10:00:00Z"}) + "\n")

        result = run_cmd([], env_override=self.env)
        assert result.returncode == 0

    def test_json_output(self):
        result = run_cmd(["--json"], env_override=self.env)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "version" in data
        assert "graph" in data

    def test_project_filter(self):
        result = run_cmd(["--project", "easy-api"], env_override=self.env)
        assert result.returncode == 0
