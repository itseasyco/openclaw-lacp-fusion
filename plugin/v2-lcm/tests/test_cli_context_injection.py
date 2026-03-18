#!/usr/bin/env python3
"""Tests for openclaw-lacp-context auto-injection and history."""

import json
import os
import subprocess
import tempfile
import shutil

import pytest

BIN_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "bin")
CONTEXT_CMD = os.path.join(BIN_DIR, "openclaw-lacp-context")


def run_cmd(args, env_override=None):
    """Run the CLI command and return result."""
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    result = subprocess.run(
        [CONTEXT_CMD] + args,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    return result


class TestAutoInject:
    """Test the auto-inject command."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.memory_dir = os.path.join(self.tmpdir, "memory", "easy-api")
        os.makedirs(self.memory_dir, exist_ok=True)

        with open(os.path.join(self.memory_dir, "MEMORY.md"), "w") as f:
            f.write("# easy-api Memory\n\n")
            f.write("Finix is the payment processor.\n")
            f.write("Brale handles stablecoin settlement.\n")
            f.write("Auth0 manages authentication.\n")
            f.write("PostgreSQL with row-level security.\n")
            f.write("Daily settlement via automated pipeline.\n")

        self.env = {
            "OPENCLAW_MEMORY_ROOT": os.path.join(self.tmpdir, "memory"),
            "OPENCLAW_VAULT_ROOT": os.path.join(self.tmpdir, "vault"),
            "OPENCLAW_INJECTION_LOG": os.path.join(self.tmpdir, "logs", "injections.jsonl"),
            "OPENCLAW_GATED_RUNS_LOG": os.path.join(self.tmpdir, "logs", "gated-runs.jsonl"),
        }

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_auto_inject_requires_project(self):
        result = run_cmd(["auto-inject"], env_override=self.env)
        assert result.returncode != 0

    def test_auto_inject_basic(self):
        result = run_cmd(
            ["auto-inject", "--project", "easy-api"],
            env_override=self.env,
        )
        assert result.returncode == 0

    def test_auto_inject_max_facts(self):
        result = run_cmd(
            ["auto-inject", "--project", "easy-api", "--max-facts", "2"],
            env_override=self.env,
        )
        assert result.returncode == 0
        # Should output at most 2 facts
        lines = [l for l in result.stdout.strip().split("\n") if l.strip() and not l.startswith("[")]
        assert len(lines) <= 2

    def test_auto_inject_with_topic(self):
        result = run_cmd(
            ["auto-inject", "--project", "easy-api", "--topic", "payment"],
            env_override=self.env,
        )
        assert result.returncode == 0

    def test_auto_inject_creates_injection_log(self):
        run_cmd(
            ["auto-inject", "--project", "easy-api", "--session-id", "sess_test"],
            env_override=self.env,
        )
        log_file = os.path.join(self.tmpdir, "logs", "injections.jsonl")
        assert os.path.exists(log_file)
        with open(log_file) as f:
            data = json.loads(f.readline())
        assert data["event"] == "context_inject"
        assert data["project"] == "easy-api"

    def test_auto_inject_creates_gated_runs_entry(self):
        run_cmd(
            ["auto-inject", "--project", "easy-api", "--session-id", "sess_test2"],
            env_override=self.env,
        )
        gated_log = os.path.join(self.tmpdir, "logs", "gated-runs.jsonl")
        assert os.path.exists(gated_log)

    def test_auto_inject_writes_context_json(self):
        run_cmd(
            ["auto-inject", "--project", "easy-api", "--session-id", "sess_ctx"],
            env_override=self.env,
        )
        ctx_file = os.path.join(self.tmpdir, "memory", "easy-api", "context.json")
        if os.path.exists(ctx_file):
            with open(ctx_file) as f:
                data = json.load(f)
            assert "last_injection" in data
            assert data["last_session_id"] == "sess_ctx"

    def test_auto_inject_empty_project(self):
        result = run_cmd(
            ["auto-inject", "--project", "nonexistent"],
            env_override=self.env,
        )
        assert result.returncode == 0

    def test_auto_inject_session_id(self):
        run_cmd(
            ["auto-inject", "--project", "easy-api", "--session-id", "custom_sess"],
            env_override=self.env,
        )
        log_file = os.path.join(self.tmpdir, "logs", "injections.jsonl")
        if os.path.exists(log_file):
            with open(log_file) as f:
                data = json.loads(f.readline())
            assert data["session_id"] == "custom_sess"


class TestHistory:
    """Test the history command."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmpdir, "logs", "injections.jsonl")
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)

        entries = [
            {"timestamp": "2026-03-18T10:00:00Z", "event": "context_inject", "project": "easy-api", "agent": "wren", "facts_injected": 3, "topic": "payment"},
            {"timestamp": "2026-03-18T11:00:00Z", "event": "context_inject", "project": "easy-dashboard", "agent": "zoe", "facts_injected": 2, "topic": "all"},
        ]
        with open(self.log_file, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        self.env = {
            "OPENCLAW_INJECTION_LOG": self.log_file,
            "OPENCLAW_MEMORY_ROOT": os.path.join(self.tmpdir, "memory"),
            "OPENCLAW_VAULT_ROOT": os.path.join(self.tmpdir, "vault"),
        }

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_history_basic(self):
        result = run_cmd(["history"], env_override=self.env)
        assert result.returncode == 0
        assert "2" in result.stdout or "2" in result.stderr

    def test_history_with_project_filter(self):
        result = run_cmd(["history", "--project", "easy-api"], env_override=self.env)
        assert result.returncode == 0

    def test_history_with_since(self):
        result = run_cmd(["history", "--since", "2026-03-18T10:30:00Z"], env_override=self.env)
        assert result.returncode == 0

    def test_history_no_log(self):
        env = {"OPENCLAW_INJECTION_LOG": "/nonexistent/injections.jsonl"}
        result = run_cmd(["history"], env_override=env)
        assert result.returncode == 0


class TestCLIDedupIntegration:
    """Test openclaw-lacp-dedup CLI."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.vault_dir = os.path.join(self.tmpdir, "vault")
        os.makedirs(self.vault_dir, exist_ok=True)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_dedup_help(self):
        dedup_cmd = os.path.join(BIN_DIR, "openclaw-lacp-dedup")
        result = subprocess.run(
            [dedup_cmd, "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "openclaw-lacp-dedup" in result.stdout

    def test_dedup_version(self):
        dedup_cmd = os.path.join(BIN_DIR, "openclaw-lacp-dedup")
        result = subprocess.run(
            [dedup_cmd, "--version"],
            capture_output=True, text=True, timeout=10,
        )
        assert "2.0.0" in result.stdout

    def test_dedup_check(self):
        dedup_cmd = os.path.join(BIN_DIR, "openclaw-lacp-dedup")
        result = subprocess.run(
            [dedup_cmd, "check", "--fact", "Test fact about payments",
             "--vault", self.vault_dir],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0


class TestCLICalibrateIntegration:
    """Test openclaw-lacp-calibrate CLI."""

    def test_calibrate_help(self):
        cal_cmd = os.path.join(BIN_DIR, "openclaw-lacp-calibrate")
        result = subprocess.run(
            [cal_cmd, "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "openclaw-lacp-calibrate" in result.stdout

    def test_calibrate_version(self):
        cal_cmd = os.path.join(BIN_DIR, "openclaw-lacp-calibrate")
        result = subprocess.run(
            [cal_cmd, "--version"],
            capture_output=True, text=True, timeout=10,
        )
        assert "2.0.0" in result.stdout

    def test_calibrate_status(self):
        cal_cmd = os.path.join(BIN_DIR, "openclaw-lacp-calibrate")
        tmpdir = tempfile.mkdtemp()
        try:
            result = subprocess.run(
                [cal_cmd, "status"],
                capture_output=True, text=True, timeout=10,
                env={**os.environ, "OPENCLAW_CALIBRATION_CONFIG": os.path.join(tmpdir, "cal.json")},
            )
            assert result.returncode == 0
        finally:
            shutil.rmtree(tmpdir)
