#!/usr/bin/env python3
"""Tests for sharing policy module."""

import json
import os
import tempfile
import shutil

import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sharing_policy import SharingPolicy, VALID_ROLES, ROLE_PERMISSIONS, ROLE_HIERARCHY


class TestSharingPolicyInit:
    """Test initialization and persistence."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmpdir, "sharing.json")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_default_empty(self):
        policy = SharingPolicy(config_path=self.config_path)
        agents = policy.list_agents()
        assert len(agents) == 0

    def test_persistence(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.register_agent("wren")
        policy.grant_access("wren", "easy-api", "writer")
        policy.save()

        policy2 = SharingPolicy(config_path=self.config_path)
        assert policy2.get_role("wren", "easy-api") == "writer"

    def test_nonexistent_config(self):
        policy = SharingPolicy(config_path="/nonexistent/config.json")
        assert len(policy.list_agents()) == 0


class TestRegisterAgent:
    """Test agent registration."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmpdir, "sharing.json")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_register_basic(self):
        policy = SharingPolicy(config_path=self.config_path)
        result = policy.register_agent("wren")
        assert "registered_at" in result
        assert result["display_name"] == "wren"

    def test_register_with_display_name(self):
        policy = SharingPolicy(config_path=self.config_path)
        result = policy.register_agent("wren", display_name="Wren Agent")
        assert result["display_name"] == "Wren Agent"

    def test_register_idempotent(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.register_agent("wren")
        policy.register_agent("wren")  # should not duplicate
        assert len(policy.list_agents()) == 1

    def test_register_multiple(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.register_agent("wren")
        policy.register_agent("zoe")
        assert len(policy.list_agents()) == 2


class TestGrantAccess:
    """Test access granting."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmpdir, "sharing.json")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_grant_reader(self):
        policy = SharingPolicy(config_path=self.config_path)
        assert policy.grant_access("wren", "easy-api", "reader") is True
        assert policy.get_role("wren", "easy-api") == "reader"

    def test_grant_writer(self):
        policy = SharingPolicy(config_path=self.config_path)
        assert policy.grant_access("wren", "easy-api", "writer") is True
        assert policy.get_role("wren", "easy-api") == "writer"

    def test_grant_curator(self):
        policy = SharingPolicy(config_path=self.config_path)
        assert policy.grant_access("wren", "easy-api", "curator") is True
        assert policy.get_role("wren", "easy-api") == "curator"

    def test_grant_invalid_role(self):
        policy = SharingPolicy(config_path=self.config_path)
        assert policy.grant_access("wren", "easy-api", "superadmin") is False

    def test_grant_auto_registers(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.grant_access("wren", "easy-api", "writer")
        agents = policy.list_agents()
        assert len(agents) == 1
        assert agents[0]["agent_id"] == "wren"

    def test_grant_multiple_projects(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.grant_access("wren", "easy-api", "writer")
        policy.grant_access("wren", "easy-dashboard", "reader")
        assert policy.get_role("wren", "easy-api") == "writer"
        assert policy.get_role("wren", "easy-dashboard") == "reader"

    def test_grant_overwrites_role(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.grant_access("wren", "easy-api", "reader")
        policy.grant_access("wren", "easy-api", "curator")
        assert policy.get_role("wren", "easy-api") == "curator"


class TestRevokeAccess:
    """Test access revocation."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmpdir, "sharing.json")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_revoke_existing(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.grant_access("wren", "easy-api", "writer")
        assert policy.revoke_access("wren", "easy-api") is True
        assert policy.get_role("wren", "easy-api") is None

    def test_revoke_nonexistent_agent(self):
        policy = SharingPolicy(config_path=self.config_path)
        assert policy.revoke_access("nobody", "easy-api") is False

    def test_revoke_nonexistent_project(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.register_agent("wren")
        assert policy.revoke_access("wren", "nonexistent") is False

    def test_revoke_preserves_other_projects(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.grant_access("wren", "easy-api", "writer")
        policy.grant_access("wren", "easy-dashboard", "reader")
        policy.revoke_access("wren", "easy-api")
        assert policy.get_role("wren", "easy-api") is None
        assert policy.get_role("wren", "easy-dashboard") == "reader"


class TestPermissions:
    """Test permission checks."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmpdir, "sharing.json")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_reader_can_read(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.grant_access("wren", "easy-api", "reader")
        assert policy.can_read("wren", "easy-api") is True

    def test_reader_cannot_promote(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.grant_access("wren", "easy-api", "reader")
        assert policy.can_promote("wren", "easy-api") is False

    def test_writer_can_promote(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.grant_access("wren", "easy-api", "writer")
        assert policy.can_promote("wren", "easy-api") is True

    def test_writer_cannot_edit(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.grant_access("wren", "easy-api", "writer")
        assert policy.can_edit("wren", "easy-api") is False

    def test_curator_full_access(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.grant_access("wren", "easy-api", "curator")
        assert policy.can_read("wren", "easy-api") is True
        assert policy.can_promote("wren", "easy-api") is True
        assert policy.can_edit("wren", "easy-api") is True
        assert policy.can_delete("wren", "easy-api") is True

    def test_no_access_returns_false(self):
        policy = SharingPolicy(config_path=self.config_path)
        assert policy.can_read("nobody", "easy-api") is False
        assert policy.can_promote("nobody", "easy-api") is False


class TestListOperations:
    """Test listing agents and projects."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmpdir, "sharing.json")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_list_agents(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.grant_access("wren", "easy-api", "writer")
        policy.grant_access("zoe", "easy-api", "reader")
        agents = policy.list_agents()
        assert len(agents) == 2
        ids = [a["agent_id"] for a in agents]
        assert "wren" in ids
        assert "zoe" in ids

    def test_list_agents_by_project(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.grant_access("wren", "easy-api", "writer")
        policy.grant_access("zoe", "easy-dashboard", "reader")
        agents = policy.list_agents(project="easy-api")
        assert len(agents) == 1
        assert agents[0]["agent_id"] == "wren"

    def test_list_projects(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.grant_access("wren", "easy-api", "writer")
        policy.grant_access("wren", "easy-dashboard", "reader")
        projects = policy.list_projects()
        assert len(projects) == 2

    def test_list_projects_by_agent(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.grant_access("wren", "easy-api", "writer")
        policy.grant_access("zoe", "easy-dashboard", "reader")
        projects = policy.list_projects(agent_id="wren")
        assert len(projects) == 1
        assert projects[0]["project"] == "easy-api"


class TestAuditLog:
    """Test audit logging."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmpdir, "sharing.json")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_register_creates_audit(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.register_agent("wren")
        summary = policy.policy_summary()
        assert summary["audit_log_entries"] >= 1

    def test_grant_creates_audit(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.grant_access("wren", "easy-api", "writer")
        summary = policy.policy_summary()
        assert summary["audit_log_entries"] >= 1

    def test_record_promotion(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.register_agent("wren")
        policy.record_promotion("wren", "easy-api", "fact_123")
        summary = policy.policy_summary()
        assert summary["audit_log_entries"] >= 2


class TestPolicySummary:
    """Test policy summary."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmpdir, "sharing.json")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_empty_summary(self):
        policy = SharingPolicy(config_path=self.config_path)
        summary = policy.policy_summary()
        assert summary["total_agents"] == 0
        assert summary["total_projects"] == 0

    def test_summary_with_data(self):
        policy = SharingPolicy(config_path=self.config_path)
        policy.grant_access("wren", "easy-api", "writer")
        policy.grant_access("zoe", "easy-dashboard", "reader")
        summary = policy.policy_summary()
        assert summary["total_agents"] == 2
        assert summary["total_projects"] == 2


class TestRoleDefinitions:
    """Test role and permission constants."""

    def test_valid_roles(self):
        assert "reader" in VALID_ROLES
        assert "writer" in VALID_ROLES
        assert "curator" in VALID_ROLES

    def test_role_hierarchy(self):
        assert ROLE_HIERARCHY["curator"] > ROLE_HIERARCHY["writer"]
        assert ROLE_HIERARCHY["writer"] > ROLE_HIERARCHY["reader"]

    def test_reader_permissions(self):
        assert "read" in ROLE_PERMISSIONS["reader"]
        assert "promote" not in ROLE_PERMISSIONS["reader"]

    def test_writer_permissions(self):
        assert "read" in ROLE_PERMISSIONS["writer"]
        assert "promote" in ROLE_PERMISSIONS["writer"]
        assert "edit" not in ROLE_PERMISSIONS["writer"]

    def test_curator_permissions(self):
        perms = ROLE_PERMISSIONS["curator"]
        assert "read" in perms
        assert "promote" in perms
        assert "edit" in perms
        assert "delete" in perms
        assert "manage" in perms
