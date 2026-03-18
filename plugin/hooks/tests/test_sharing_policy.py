"""Tests for sharing_policy.py — Multi-agent memory access control."""

import json
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
V2_LCM_DIR = REPO_ROOT / "plugin" / "v2-lcm"
sys.path.insert(0, str(V2_LCM_DIR))

from sharing_policy import SharingPolicy, VALID_ROLES, ROLE_PERMISSIONS


class TestSharingPolicyInit:
    """Test SharingPolicy initialization."""

    def test_init_creates_default_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            assert sp.list_agents() == []

    def test_save_and_reload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = str(Path(tmpdir) / "sharing.json")
            sp = SharingPolicy(config_path=config)
            sp.register_agent("agent-a", "Agent A")
            sp.save()

            sp2 = SharingPolicy(config_path=config)
            agents = sp2.list_agents()
            assert len(agents) == 1
            assert agents[0]["agent_id"] == "agent-a"


class TestAgentRegistration:
    """Test agent registration."""

    def test_register_agent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            result = sp.register_agent("wren", "Wren Agent")
            assert result["display_name"] == "Wren Agent"

    def test_register_duplicate_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            sp.register_agent("wren")
            sp.register_agent("wren")
            assert len(sp.list_agents()) == 1


class TestAccessGrant:
    """Test granting and revoking access."""

    def test_grant_reader(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            result = sp.grant_access("wren", "easy-api", "reader")
            assert result is True
            assert sp.get_role("wren", "easy-api") == "reader"

    def test_grant_writer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            sp.grant_access("wren", "easy-api", "writer")
            assert sp.get_role("wren", "easy-api") == "writer"

    def test_grant_curator(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            sp.grant_access("wren", "easy-api", "curator")
            assert sp.get_role("wren", "easy-api") == "curator"

    def test_grant_invalid_role(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            result = sp.grant_access("wren", "easy-api", "superadmin")
            assert result is False

    def test_revoke_access(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            sp.grant_access("wren", "easy-api", "reader")
            result = sp.revoke_access("wren", "easy-api")
            assert result is True
            assert sp.get_role("wren", "easy-api") is None

    def test_revoke_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            result = sp.revoke_access("ghost", "easy-api")
            assert result is False


class TestPermissionChecks:
    """Test permission check methods."""

    def test_reader_can_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            sp.grant_access("agent-a", "proj", "reader")
            assert sp.can_read("agent-a", "proj") is True

    def test_reader_cannot_promote(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            sp.grant_access("agent-a", "proj", "reader")
            assert sp.can_promote("agent-a", "proj") is False

    def test_writer_can_promote(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            sp.grant_access("agent-a", "proj", "writer")
            assert sp.can_promote("agent-a", "proj") is True

    def test_writer_cannot_delete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            sp.grant_access("agent-a", "proj", "writer")
            assert sp.can_delete("agent-a", "proj") is False

    def test_curator_can_delete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            sp.grant_access("agent-a", "proj", "curator")
            assert sp.can_delete("agent-a", "proj") is True

    def test_no_access_denies_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            assert sp.can_read("ghost", "proj") is False
            assert sp.can_promote("ghost", "proj") is False
            assert sp.can_edit("ghost", "proj") is False
            assert sp.can_delete("ghost", "proj") is False


class TestListOperations:
    """Test listing agents and projects."""

    def test_list_agents_by_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            sp.grant_access("wren", "easy-api", "writer")
            sp.grant_access("zoe", "easy-api", "reader")
            sp.grant_access("wren", "other-project", "curator")

            agents = sp.list_agents(project="easy-api")
            assert len(agents) == 2

    def test_list_projects_by_agent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            sp.grant_access("wren", "easy-api", "writer")
            sp.grant_access("wren", "easy-dashboard", "reader")

            projects = sp.list_projects(agent_id="wren")
            assert len(projects) == 2


class TestPolicySummary:
    """Test policy summary."""

    def test_summary_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            sp.grant_access("wren", "easy-api", "writer")
            summary = sp.policy_summary()
            assert "total_agents" in summary
            assert "total_projects" in summary
            assert summary["total_agents"] == 1

    def test_audit_log_records_actions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            sp.grant_access("wren", "easy-api", "writer")
            sp.revoke_access("wren", "easy-api")
            summary = sp.policy_summary()
            assert summary["audit_log_entries"] >= 2


class TestRoleConstants:
    """Test role constants and permissions."""

    def test_valid_roles(self):
        assert "reader" in VALID_ROLES
        assert "writer" in VALID_ROLES
        assert "curator" in VALID_ROLES

    def test_role_permissions_hierarchy(self):
        reader_perms = set(ROLE_PERMISSIONS["reader"])
        writer_perms = set(ROLE_PERMISSIONS["writer"])
        curator_perms = set(ROLE_PERMISSIONS["curator"])
        assert reader_perms.issubset(writer_perms)
        assert writer_perms.issubset(curator_perms)
