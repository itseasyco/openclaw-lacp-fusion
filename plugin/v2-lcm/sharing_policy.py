#!/usr/bin/env python3
"""
Sharing Policy — Multi-agent memory access control for LACP.

Manages per-project sharing configurations with role-based access:
  - reader: Can read LACP facts
  - writer: Can promote facts to LACP
  - curator: Can edit, delete, and manage facts

Policies stored in config/.openclaw-lacp-sharing.json.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DEFAULT_SHARING_CONFIG = "~/.openclaw/config/.openclaw-lacp-sharing.json"

VALID_ROLES = ["reader", "writer", "curator"]
ROLE_HIERARCHY = {"curator": 3, "writer": 2, "reader": 1}

# Permission matrix: what each role can do
ROLE_PERMISSIONS = {
    "reader": ["read"],
    "writer": ["read", "promote"],
    "curator": ["read", "promote", "edit", "delete", "manage"],
}


class SharingPolicy:
    """Multi-agent memory sharing policy manager."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(
            config_path or os.path.expanduser(DEFAULT_SHARING_CONFIG)
        )
        self._data = self._load()

    def _load(self) -> dict:
        """Load sharing policies from disk."""
        try:
            if self.config_path.exists():
                return json.loads(self.config_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
        return {
            "version": "2.0.0",
            "agents": {},
            "projects": {},
            "audit_log": [],
        }

    def save(self) -> None:
        """Persist sharing policies to disk."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(json.dumps(self._data, indent=2, default=str))
        except OSError:
            pass

    def register_agent(self, agent_id: str, display_name: str = "") -> dict:
        """Register a new agent in the sharing system."""
        if agent_id not in self._data["agents"]:
            self._data["agents"][agent_id] = {
                "display_name": display_name or agent_id,
                "registered_at": datetime.now(timezone.utc).isoformat(),
                "projects": {},
            }
            self._audit("register_agent", agent_id=agent_id)
        return self._data["agents"][agent_id]

    def grant_access(self, agent_id: str, project: str, role: str) -> bool:
        """Grant an agent a role on a project."""
        if role not in VALID_ROLES:
            return False

        # Auto-register agent if needed
        if agent_id not in self._data["agents"]:
            self.register_agent(agent_id)

        # Set role
        self._data["agents"][agent_id]["projects"][project] = {
            "role": role,
            "granted_at": datetime.now(timezone.utc).isoformat(),
        }

        # Also track in project-centric view
        if project not in self._data["projects"]:
            self._data["projects"][project] = {"agents": {}}
        self._data["projects"][project]["agents"][agent_id] = role

        self._audit("grant_access", agent_id=agent_id, project=project, role=role)
        return True

    def revoke_access(self, agent_id: str, project: str) -> bool:
        """Revoke an agent's access to a project."""
        if agent_id not in self._data["agents"]:
            return False

        agent = self._data["agents"][agent_id]
        if project not in agent.get("projects", {}):
            return False

        del agent["projects"][project]

        # Clean up project-centric view
        if project in self._data["projects"]:
            self._data["projects"][project]["agents"].pop(agent_id, None)

        self._audit("revoke_access", agent_id=agent_id, project=project)
        return True

    def get_role(self, agent_id: str, project: str) -> Optional[str]:
        """Get an agent's role for a project."""
        agent = self._data["agents"].get(agent_id, {})
        project_data = agent.get("projects", {}).get(project, {})
        return project_data.get("role")

    def can_read(self, agent_id: str, project: str, fact_id: str = "") -> bool:
        """Check if agent can read facts from a project."""
        role = self.get_role(agent_id, project)
        if role is None:
            return False
        return "read" in ROLE_PERMISSIONS.get(role, [])

    def can_promote(self, agent_id: str, project: str) -> bool:
        """Check if agent can promote facts to a project."""
        role = self.get_role(agent_id, project)
        if role is None:
            return False
        return "promote" in ROLE_PERMISSIONS.get(role, [])

    def can_edit(self, agent_id: str, project: str) -> bool:
        """Check if agent can edit facts in a project."""
        role = self.get_role(agent_id, project)
        if role is None:
            return False
        return "edit" in ROLE_PERMISSIONS.get(role, [])

    def can_delete(self, agent_id: str, project: str) -> bool:
        """Check if agent can delete facts from a project."""
        role = self.get_role(agent_id, project)
        if role is None:
            return False
        return "delete" in ROLE_PERMISSIONS.get(role, [])

    def list_agents(self, project: Optional[str] = None) -> list[dict]:
        """List all agents, optionally filtered by project."""
        agents = []
        for agent_id, agent_data in self._data["agents"].items():
            if project:
                project_info = agent_data.get("projects", {}).get(project)
                if project_info:
                    agents.append({
                        "agent_id": agent_id,
                        "display_name": agent_data.get("display_name", agent_id),
                        "project": project,
                        "role": project_info.get("role", "none"),
                    })
            else:
                agents.append({
                    "agent_id": agent_id,
                    "display_name": agent_data.get("display_name", agent_id),
                    "projects": list(agent_data.get("projects", {}).keys()),
                })
        return agents

    def list_projects(self, agent_id: Optional[str] = None) -> list[dict]:
        """List all projects, optionally filtered by agent."""
        projects = []
        for project_name, project_data in self._data["projects"].items():
            if agent_id:
                if agent_id in project_data.get("agents", {}):
                    projects.append({
                        "project": project_name,
                        "role": project_data["agents"][agent_id],
                    })
            else:
                projects.append({
                    "project": project_name,
                    "agents": project_data.get("agents", {}),
                })
        return projects

    def record_promotion(self, agent_id: str, project: str, fact_id: str) -> None:
        """Record that an agent promoted a fact (for dedup tracking)."""
        self._audit("promote", agent_id=agent_id, project=project, fact_id=fact_id)

    def _audit(self, action: str, **kwargs) -> None:
        """Append to audit log."""
        entry = {
            "action": action,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **kwargs,
        }
        self._data["audit_log"].append(entry)
        # Cap audit log at 1000 entries
        if len(self._data["audit_log"]) > 1000:
            self._data["audit_log"] = self._data["audit_log"][-1000:]

    def policy_summary(self) -> dict:
        """Get a summary of the sharing policy state."""
        return {
            "total_agents": len(self._data["agents"]),
            "total_projects": len(self._data["projects"]),
            "audit_log_entries": len(self._data.get("audit_log", [])),
            "agents": [
                {
                    "id": aid,
                    "projects": len(adata.get("projects", {})),
                }
                for aid, adata in self._data["agents"].items()
            ],
        }
