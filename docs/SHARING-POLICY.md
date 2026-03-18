# Sharing Policy — OpenClaw LACP v2.0.0

Multi-agent access control for shared LACP memory.

## Overview

When multiple agents operate on the same project or organization, they may need to share promoted facts. The sharing policy module controls who can access what, with role-based permissions and per-project policies.

## Roles

| Role | Read | Write | Curate |
|------|------|-------|--------|
| `reader` | Yes | No | No |
| `writer` | Yes | Yes | No |
| `curator` | Yes | Yes | Yes |

- **Read**: Query and inject shared facts into sessions
- **Write**: Promote new facts to shared memory
- **Curate**: Edit, delete, and manage existing shared facts

## Policy Structure

```json
{
  "version": "2.0.0",
  "sharing_enabled": false,
  "default_role": "reader",
  "agents": {
    "wren": {
      "role": "writer",
      "projects": ["easy-api", "easy-dashboard"],
      "registered_at": "2026-03-18T12:00:00+00:00"
    }
  },
  "projects": {
    "easy-api": {
      "max_facts": 100,
      "auto_promote": true
    }
  },
  "dedup_across_agents": true,
  "audit_sharing": true
}
```

## Python API

```python
from sharing_policy import SharingPolicy, ROLES

policy = SharingPolicy(config_path="/path/to/sharing.json")

# Enable sharing
policy.enable_sharing()

# Register agents
policy.register_agent("wren", role="writer", projects=["easy-api"])
policy.register_agent("zoe", role="reader")

# Check access
result = policy.check_access("wren", "easy-api", "write")
print(result["allowed"])  # True

# Grant/revoke
policy.grant_project_access("zoe", "easy-api")
policy.revoke_project_access("zoe", "easy-api")

# Update roles
policy.update_role("zoe", "curator")

# Per-project policies
policy.set_project_policy("easy-api", {"max_facts": 200, "auto_promote": True})

# List agents
for agent in policy.list_agents():
    print(f"{agent['agent_id']}: {agent['role']}")
```

## CLI Usage

```bash
# Register an agent
openclaw-lacp-share register --agent wren --role writer

# Enable sharing
openclaw-lacp-share enable

# Grant access
openclaw-lacp-share grant-access --agent wren --project easy-api --role writer

# Check permissions
openclaw-lacp-share check --agent wren --project easy-api --action write

# List available memory
openclaw-lacp-share list-available --from wren

# Query shared facts
openclaw-lacp-share query --from wren --topic "settlement"

# Revoke access
openclaw-lacp-share revoke-access --agent wren --project easy-api

# Use custom policy file
openclaw-lacp-share --policy-file /path/to/policy.json list-available --from wren
```

## Access Control Flow

1. **Is sharing enabled?** If not, deny all cross-agent access.
2. **Is agent registered?** If not, apply `default_role` (reader).
3. **Does agent have project access?** Check `projects` list. Empty list = all projects.
4. **Does role allow action?** Check role permissions map.

## Security Considerations

- Sharing is **disabled by default** — must be explicitly enabled
- Default role is `reader` — new/unknown agents can only read
- Per-project policies allow fine-grained control
- All access checks can be audited via the policy config
- Cross-agent dedup prevents duplicate facts across agents when `dedup_across_agents` is enabled
