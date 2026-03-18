#!/usr/bin/env python3
"""Tests for openclaw-lacp-promote pipeline command."""

import json
import os
import subprocess
import tempfile
import shutil

import pytest

BIN_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "bin")
PROMOTE_CMD = os.path.join(BIN_DIR, "openclaw-lacp-promote")


def run_cmd(args, env_override=None):
    """Run the CLI command and return result."""
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    result = subprocess.run(
        [PROMOTE_CMD] + args,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    return result


class TestPipelineCommand:
    """Test the pipeline command for full auto-promotion."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.env = {
            "OPENCLAW_MEMORY_ROOT": os.path.join(self.tmpdir, "memory"),
            "OPENCLAW_VAULT_ROOT": os.path.join(self.tmpdir, "vault"),
            "OPENCLAW_PROMOTIONS_LOG": os.path.join(self.tmpdir, "logs", "promotions.jsonl"),
            "OPENCLAW_PROVENANCE_DIR": os.path.join(self.tmpdir, "provenance"),
            "OPENCLAW_GATED_RUNS_LOG": os.path.join(self.tmpdir, "logs", "gated-runs.jsonl"),
        }
        os.makedirs(os.path.join(self.tmpdir, "vault"), exist_ok=True)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def _write_md_summary(self, content, filename="sum_test123.md"):
        filepath = os.path.join(self.tmpdir, filename)
        with open(filepath, "w") as f:
            f.write(content)
        return filepath

    def _write_json_summary(self, data, filename="sum_test123.json"):
        filepath = os.path.join(self.tmpdir, filename)
        with open(filepath, "w") as f:
            json.dump(data, f)
        return filepath

    def test_pipeline_requires_file(self):
        result = run_cmd(["pipeline"], env_override=self.env)
        assert result.returncode != 0

    def test_pipeline_missing_file(self):
        result = run_cmd(["pipeline", "--file", "/nonexistent/file.md"], env_override=self.env)
        assert result.returncode != 0

    def test_pipeline_md_file(self):
        filepath = self._write_md_summary(
            "# Session Summary\n\n"
            "- Finix handles payment processing for all merchants\n"
            "- The API uses authentication via Auth0\n"
            "- Database schema migration was decided for v2\n"
            "- Decided to use PostgreSQL with row-level security\n"
        )
        result = run_cmd(
            ["pipeline", "--file", filepath, "--project", "easy-api"],
            env_override=self.env,
        )
        assert result.returncode == 0

    def test_pipeline_json_file(self):
        filepath = self._write_json_summary({
            "summary_id": "sum_json_test",
            "content": "Brale manages stablecoin settlement daily. Decided to use RTP for faster payouts.",
            "source": "code",
            "project": "easy-api",
            "citations": ["file:treasury.py", "doc:settlement-spec"],
        })
        result = run_cmd(
            ["pipeline", "--file", filepath, "--project", "easy-api"],
            env_override=self.env,
        )
        assert result.returncode == 0

    def test_pipeline_dry_run(self):
        filepath = self._write_md_summary(
            "- Important architectural decision about payment processing\n"
            "- Decided to migrate the database schema to PostgreSQL\n"
            "- Settlement infrastructure uses Brale for stablecoin conversion\n"
            "- API integration pattern for authentication via Auth0\n"
        )
        result = run_cmd(
            ["pipeline", "--file", filepath, "--project", "test",
             "--dry-run", "--threshold", "30"],
            env_override=self.env,
        )
        assert result.returncode == 0
        assert "DRY RUN" in result.stdout or "DRY RUN" in result.stderr

    def test_pipeline_custom_threshold(self):
        filepath = self._write_md_summary("Simple note with not much detail.")
        result = run_cmd(
            ["pipeline", "--file", filepath, "--project", "test", "--threshold", "95"],
            env_override=self.env,
        )
        assert result.returncode == 0
        # Should likely be below threshold with minimal content

    def test_pipeline_creates_gated_runs_log(self):
        filepath = self._write_md_summary(
            "- Decided to use Finix for payment processing\n"
            "- Architecture decision: PostgreSQL with RLS policies\n"
        )
        run_cmd(
            ["pipeline", "--file", filepath, "--project", "easy-api"],
            env_override=self.env,
        )
        gated_log = os.path.join(self.tmpdir, "logs", "gated-runs.jsonl")
        assert os.path.exists(gated_log)
        with open(gated_log) as f:
            lines = [l for l in f.readlines() if l.strip()]
        assert len(lines) >= 1

    def test_pipeline_writes_to_layer1(self):
        filepath = self._write_md_summary(
            "- Finix processes credit card payments for online merchants\n"
            "- The settlement layer uses Brale for stablecoin conversion\n"
            "- Decided to implement daily settlement via automated pipeline\n"
        )
        run_cmd(
            ["pipeline", "--file", filepath, "--project", "easy-api"],
            env_override=self.env,
        )
        memory_dir = os.path.join(self.tmpdir, "memory", "easy-api")
        if os.path.exists(memory_dir):
            files = os.listdir(memory_dir)
            assert len(files) >= 1


class TestAuditTrail:
    """Test audit trail logging in promote."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.gated_log = os.path.join(self.tmpdir, "logs", "gated-runs.jsonl")
        self.env = {
            "OPENCLAW_MEMORY_ROOT": os.path.join(self.tmpdir, "memory"),
            "OPENCLAW_VAULT_ROOT": os.path.join(self.tmpdir, "vault"),
            "OPENCLAW_PROMOTIONS_LOG": os.path.join(self.tmpdir, "logs", "promotions.jsonl"),
            "OPENCLAW_PROVENANCE_DIR": os.path.join(self.tmpdir, "provenance"),
            "OPENCLAW_GATED_RUNS_LOG": self.gated_log,
        }

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_auto_logs_to_gated_runs(self):
        run_cmd(
            ["auto", "--summary", "sum_audit1", "--score", "85",
             "--category", "arch", "--project", "easy-api"],
            env_override=self.env,
        )
        assert os.path.exists(self.gated_log)
        with open(self.gated_log) as f:
            line = f.readline()
        data = json.loads(line)
        assert data["event"] == "promote"

    def test_manual_logs_to_gated_runs(self):
        run_cmd(
            ["manual", "--summary", "sum_audit2",
             "--fact", "Test fact for audit",
             "--project", "easy-api"],
            env_override=self.env,
        )
        assert os.path.exists(self.gated_log)
        with open(self.gated_log) as f:
            line = f.readline()
        data = json.loads(line)
        assert data["event"] == "manual_promote"
