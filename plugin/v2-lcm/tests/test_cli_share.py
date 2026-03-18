#!/usr/bin/env python3
"""Tests for openclaw-lacp-share CLI (Phase D — full implementation)."""

import json
import os
import subprocess
import tempfile
import shutil

import pytest

BIN_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "bin")
SHARE_CMD = os.path.join(BIN_DIR, "openclaw-lacp-share")


def run_cmd(args, policy_file=None):
    """Run the CLI command and return result."""
    cmd = [SHARE_CMD]
    if policy_file:
        cmd += ["--policy-file", policy_file]
    cmd += args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result


class TestShareHelp:
    """Test help and version."""

    def test_help(self):
        result = run_cmd(["--help"])
        assert result.returncode == 0
        assert "Multi-Agent Memory Sharing" in result.stdout

    def test_version(self):
        result = run_cmd(["--version"])
        assert "2.0.0" in result.stdout

    def test_no_args_shows_help(self):
        result = run_cmd([])
        assert result.returncode == 0
        assert "COMMANDS" in result.stdout


class TestShareRegister:
    """Test agent registration via CLI."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.policy_file = os.path.join(self.tmpdir, "sharing.json")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_register_agent(self):
        result = run_cmd(
            ["register", "--agent", "wren"],
            policy_file=self.policy_file,
        )
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "Registered" in combined or "wren" in combined

    def test_register_with_json(self):
        result = run_cmd(
            ["--json", "register", "--agent", "zoe"],
            policy_file=self.policy_file,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["agent"] == "zoe"
        assert data["registered"] is True


class TestShareGrant:
    """Test granting access via CLI."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.policy_file = os.path.join(self.tmpdir, "sharing.json")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_grant_access(self):
        result = run_cmd(
            ["grant", "--agent", "wren", "--project", "easy-api", "--role", "writer"],
            policy_file=self.policy_file,
        )
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "Granted" in combined or "writer" in combined

    def test_grant_json(self):
        result = run_cmd(
            ["--json", "grant", "--agent", "wren", "--project", "easy-api", "--role", "reader"],
            policy_file=self.policy_file,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["success"] is True


class TestShareCheck:
    """Test permission checking via CLI."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.policy_file = os.path.join(self.tmpdir, "sharing.json")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_check_no_access(self):
        result = run_cmd(
            ["check", "--agent", "nobody", "--project", "easy-api"],
            policy_file=self.policy_file,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["can_read"] is False

    def test_check_with_access(self):
        run_cmd(
            ["grant", "--agent", "wren", "--project", "easy-api", "--role", "writer"],
            policy_file=self.policy_file,
        )
        result = run_cmd(
            ["check", "--agent", "wren", "--project", "easy-api"],
            policy_file=self.policy_file,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["role"] == "writer"
        assert data["can_read"] is True
        assert data["can_promote"] is True


class TestShareList:
    """Test listing agents and projects."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.policy_file = os.path.join(self.tmpdir, "sharing.json")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_list_agents_empty(self):
        result = run_cmd(
            ["list-agents"],
            policy_file=self.policy_file,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data == []

    def test_list_agents_with_data(self):
        run_cmd(
            ["grant", "--agent", "wren", "--project", "easy-api", "--role", "writer"],
            policy_file=self.policy_file,
        )
        result = run_cmd(
            ["list-agents"],
            policy_file=self.policy_file,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert data[0]["agent_id"] == "wren"

    def test_list_projects(self):
        run_cmd(
            ["grant", "--agent", "wren", "--project", "easy-api", "--role", "writer"],
            policy_file=self.policy_file,
        )
        result = run_cmd(
            ["list-projects"],
            policy_file=self.policy_file,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) >= 1


class TestShareSummary:
    """Test summary command."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.policy_file = os.path.join(self.tmpdir, "sharing.json")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_summary(self):
        result = run_cmd(
            ["summary"],
            policy_file=self.policy_file,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "total_agents" in data
        assert "total_projects" in data


class TestShareUnknownCommand:
    """Test error handling."""

    def test_unknown_command(self):
        result = run_cmd(["nonexistent"])
        assert result.returncode != 0 or "Unknown" in (result.stdout + result.stderr)
