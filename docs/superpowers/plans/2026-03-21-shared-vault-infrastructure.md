# Shared Vault Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared vault infrastructure layer (Phase 2 of the Shared Intelligence Graph spec). This enables multi-node operation by adding mode configuration, command blocking in connected mode, the `openclaw-lacp-connect` CLI, ob sync daemon management, curator HTTP surface, heartbeat monitoring, and invite token system.

**Architecture:** A mode module (`plugin/lib/mode.py`) serves as the central authority for operating mode. All mutation commands check mode before executing. Connected nodes delegate mutations to the curator and write only to inbox queues. The curator exposes 3 HTTP endpoints behind token auth. Heartbeat files in the shared vault provide distributed health monitoring. Invite tokens gate cluster membership.

**Tech Stack:** Python 3.9+, Bash 4.0+, `http.server` stdlib (curator HTTP), launchd (macOS) / systemd (Linux) for daemon management

---

## Task 1: Create mode configuration module

Create `plugin/lib/mode.py` -- the central authority for LACP operating mode. It reads/writes `LACP_MODE` from environment and config file, provides helper functions (`is_standalone()`, `is_connected()`, `is_curator()`), and checks whether mutations are allowed.

### Step 1.1: Write plugin/lib/mode.py

- [ ] Write `plugin/lib/mode.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/mode.py`

```python
#!/usr/bin/env python3
"""
Mode configuration for openclaw-lacp-fusion.

Three operating modes:
  - standalone: local vault, all commands active (default)
  - connected: synced vault, mutations blocked, inbox writes only
  - curator: canonical vault, runs consolidation, connectors, HTTP surface

Mode is determined by (in priority order):
  1. LACP_MODE environment variable
  2. ~/.openclaw/config/mode.json file
  3. Default: "standalone"
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

VALID_MODES = ("standalone", "connected", "curator")

# Commands that mutate the vault graph (blocked in connected mode)
MUTATION_COMMANDS = frozenset({
    "brain-expand",
    "brain-resolve",
    "obsidian-optimize",
})

# Commands that are redirected to inbox in connected mode (not blocked)
INBOX_REDIRECT_COMMANDS = frozenset({
    "brain-ingest",
})


@dataclass(frozen=True)
class ModeConfig:
    """Immutable snapshot of the current mode configuration."""
    mode: str
    curator_url: str
    curator_token: str
    mutations_enabled: bool
    vault_path: str
    agent_role: str

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "curator_url": self.curator_url,
            "curator_token": self.curator_token,
            "mutations_enabled": self.mutations_enabled,
            "vault_path": self.vault_path,
            "agent_role": self.agent_role,
        }


def _config_path() -> Path:
    """Return path to mode.json config file."""
    openclaw_home = os.environ.get("OPENCLAW_HOME", os.path.expanduser("~/.openclaw"))
    return Path(openclaw_home) / "config" / "mode.json"


def _read_config_file() -> dict:
    """Read mode.json, return empty dict if missing or malformed."""
    path = _config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_config_file(data: dict) -> Path:
    """Write mode.json, creating parent directories if needed."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def get_mode() -> str:
    """Return the current operating mode string."""
    env_mode = os.environ.get("LACP_MODE", "").strip().lower()
    if env_mode in VALID_MODES:
        return env_mode
    config = _read_config_file()
    file_mode = config.get("mode", "").strip().lower()
    if file_mode in VALID_MODES:
        return file_mode
    return "standalone"


def get_config() -> ModeConfig:
    """Return a full ModeConfig snapshot from env + config file."""
    config = _read_config_file()
    mode = get_mode()

    curator_url = os.environ.get(
        "LACP_CURATOR_URL",
        config.get("curator_url", ""),
    )
    curator_token = os.environ.get(
        "LACP_CURATOR_TOKEN",
        config.get("curator_token", ""),
    )
    mutations_enabled_env = os.environ.get("LACP_MUTATIONS_ENABLED", "").strip().lower()
    if mutations_enabled_env in ("true", "false"):
        mutations_enabled = mutations_enabled_env == "true"
    else:
        mutations_enabled = config.get("mutations_enabled", mode != "connected")

    vault_path = os.environ.get(
        "LACP_OBSIDIAN_VAULT",
        os.environ.get(
            "OPENCLAW_VAULT",
            config.get("vault_path", ""),
        ),
    )
    if not vault_path:
        openclaw_home = os.environ.get("OPENCLAW_HOME", os.path.expanduser("~/.openclaw"))
        vault_path = os.path.join(openclaw_home, "data", "knowledge")

    agent_role = os.environ.get(
        "LACP_AGENT_ROLE",
        config.get("agent_role", "developer"),
    )

    return ModeConfig(
        mode=mode,
        curator_url=curator_url,
        curator_token=curator_token,
        mutations_enabled=mutations_enabled,
        vault_path=vault_path,
        agent_role=agent_role,
    )


def set_mode(
    mode: str,
    *,
    curator_url: Optional[str] = None,
    curator_token: Optional[str] = None,
    vault_path: Optional[str] = None,
    agent_role: Optional[str] = None,
) -> Path:
    """Persist mode configuration to mode.json. Returns the config file path."""
    if mode not in VALID_MODES:
        raise ValueError(f"Invalid mode: {mode!r}. Must be one of {VALID_MODES}")

    config = _read_config_file()
    config["mode"] = mode
    config["mutations_enabled"] = mode != "connected"

    if curator_url is not None:
        config["curator_url"] = curator_url
    if curator_token is not None:
        config["curator_token"] = curator_token
    if vault_path is not None:
        config["vault_path"] = vault_path
    if agent_role is not None:
        config["agent_role"] = agent_role

    return _write_config_file(config)


def is_standalone() -> bool:
    """Return True if running in standalone mode."""
    return get_mode() == "standalone"


def is_connected() -> bool:
    """Return True if running in connected mode."""
    return get_mode() == "connected"


def is_curator() -> bool:
    """Return True if running in curator mode."""
    return get_mode() == "curator"


def check_mutation_allowed(command_name: str) -> tuple[bool, str]:
    """
    Check if a mutation command is allowed in the current mode.

    Returns (allowed, reason). If not allowed, reason explains why.
    """
    config = get_config()

    if config.mode == "standalone":
        return True, ""

    if config.mode == "curator":
        return True, ""

    # Connected mode
    if command_name in MUTATION_COMMANDS:
        return False, (
            f"{command_name} is blocked in connected mode. "
            f"Vault mutations are managed by the curator at {config.curator_url}."
        )

    if command_name in INBOX_REDIRECT_COMMANDS:
        return True, "redirected_to_inbox"

    return True, ""


def get_inbox_queue_path(agent_id: str = "") -> str:
    """
    Return the inbox queue path for the current agent in connected mode.
    Falls back to 'queue-agent' if no agent_id provided.
    """
    config = get_config()
    queue_name = f"queue-{agent_id}" if agent_id else "queue-agent"
    return os.path.join(config.vault_path, "05_Inbox", queue_name)
```

### Step 1.2: Write tests for mode module

- [ ] Write test file `plugin/lib/tests/test_mode.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/tests/test_mode.py`

```python
"""Tests for plugin.lib.mode -- operating mode configuration."""

import json
import os
from pathlib import Path
from unittest import mock

import pytest

# Ensure plugin/lib is importable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lib.mode import (
    VALID_MODES,
    MUTATION_COMMANDS,
    INBOX_REDIRECT_COMMANDS,
    ModeConfig,
    get_mode,
    get_config,
    set_mode,
    is_standalone,
    is_connected,
    is_curator,
    check_mutation_allowed,
    get_inbox_queue_path,
    _config_path,
)


class TestGetMode:
    def test_default_is_standalone(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        monkeypatch.delenv("LACP_MODE", raising=False)
        assert get_mode() == "standalone"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("LACP_MODE", "connected")
        assert get_mode() == "connected"

    def test_env_curator(self, monkeypatch):
        monkeypatch.setenv("LACP_MODE", "curator")
        assert get_mode() == "curator"

    def test_invalid_env_falls_through(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        monkeypatch.setenv("LACP_MODE", "bogus")
        assert get_mode() == "standalone"

    def test_config_file_mode(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        monkeypatch.delenv("LACP_MODE", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "mode.json").write_text('{"mode": "connected"}')
        assert get_mode() == "connected"

    def test_env_takes_priority_over_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        monkeypatch.setenv("LACP_MODE", "curator")
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "mode.json").write_text('{"mode": "connected"}')
        assert get_mode() == "curator"


class TestSetMode:
    def test_set_mode_writes_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        monkeypatch.delenv("LACP_MODE", raising=False)
        path = set_mode("connected", curator_url="http://localhost:9100")
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["mode"] == "connected"
        assert data["curator_url"] == "http://localhost:9100"
        assert data["mutations_enabled"] is False

    def test_set_mode_curator_enables_mutations(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        path = set_mode("curator")
        data = json.loads(path.read_text())
        assert data["mutations_enabled"] is True

    def test_set_mode_invalid_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        with pytest.raises(ValueError, match="Invalid mode"):
            set_mode("bogus")


class TestHelpers:
    def test_is_standalone(self, monkeypatch):
        monkeypatch.setenv("LACP_MODE", "standalone")
        assert is_standalone() is True
        assert is_connected() is False
        assert is_curator() is False

    def test_is_connected(self, monkeypatch):
        monkeypatch.setenv("LACP_MODE", "connected")
        assert is_connected() is True
        assert is_standalone() is False

    def test_is_curator(self, monkeypatch):
        monkeypatch.setenv("LACP_MODE", "curator")
        assert is_curator() is True


class TestCheckMutationAllowed:
    def test_standalone_allows_all(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LACP_MODE", "standalone")
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        for cmd in MUTATION_COMMANDS:
            allowed, reason = check_mutation_allowed(cmd)
            assert allowed is True

    def test_connected_blocks_mutations(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LACP_MODE", "connected")
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        for cmd in MUTATION_COMMANDS:
            allowed, reason = check_mutation_allowed(cmd)
            assert allowed is False
            assert "blocked" in reason

    def test_connected_redirects_ingest(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LACP_MODE", "connected")
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        allowed, reason = check_mutation_allowed("brain-ingest")
        assert allowed is True
        assert reason == "redirected_to_inbox"

    def test_curator_allows_all(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LACP_MODE", "curator")
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        for cmd in MUTATION_COMMANDS:
            allowed, reason = check_mutation_allowed(cmd)
            assert allowed is True


class TestGetConfig:
    def test_full_config_from_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        monkeypatch.delenv("LACP_MODE", raising=False)
        monkeypatch.delenv("LACP_CURATOR_URL", raising=False)
        monkeypatch.delenv("LACP_CURATOR_TOKEN", raising=False)
        monkeypatch.delenv("LACP_OBSIDIAN_VAULT", raising=False)
        monkeypatch.delenv("OPENCLAW_VAULT", raising=False)
        monkeypatch.delenv("LACP_MUTATIONS_ENABLED", raising=False)
        monkeypatch.delenv("LACP_AGENT_ROLE", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "mode.json").write_text(json.dumps({
            "mode": "connected",
            "curator_url": "http://curator:9100",
            "curator_token": "tok_abc",
            "vault_path": "/shared/vault",
            "agent_role": "pm",
        }))
        cfg = get_config()
        assert cfg.mode == "connected"
        assert cfg.curator_url == "http://curator:9100"
        assert cfg.curator_token == "tok_abc"
        assert cfg.mutations_enabled is False
        assert cfg.vault_path == "/shared/vault"
        assert cfg.agent_role == "pm"
```

### Step 1.3: Ensure __init__.py exists in lib/tests

- [ ] Create `plugin/lib/tests/__init__.py` if it does not exist

```bash
touch /Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/tests/__init__.py
```

### Step 1.4: Run tests and verify

- [ ] Run mode module tests

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/lib/tests/test_mode.py -v
```

**Expected output:** All 16 tests pass.

### Step 1.5: Commit

- [ ] Commit mode module

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo
git add plugin/lib/mode.py plugin/lib/tests/test_mode.py plugin/lib/tests/__init__.py
git commit -m "$(cat <<'EOF'
feat: add mode configuration module (standalone/connected/curator)

Central authority for LACP operating mode. Reads LACP_MODE from env or
~/.openclaw/config/mode.json. Provides is_standalone(), is_connected(),
is_curator() helpers and check_mutation_allowed() gate for command blocking.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add mode guards to mutation commands

Modify `brain-expand`, `brain-resolve`, `obsidian-optimize`, and `brain-ingest` to check mode before running. In connected mode: mutation commands exit with a clear error, ingest redirects writes to the inbox queue.

### Step 2.1: Create shared mode-check shell helper

- [ ] Write `plugin/bin/lib/mode-check.sh`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/lib/mode-check.sh`

```bash
#!/usr/bin/env bash
#
# mode-check.sh — Shared shell helper for mode-aware command blocking
#
# Source this from any bash script that needs mode guards:
#   source "$(dirname "$0")/lib/mode-check.sh"
#
# Then call:
#   mode_guard "brain-expand"
#
# Exit codes:
#   0 = allowed
#   10 = blocked (connected mode, mutation not allowed)

PLUGIN_LIB_DIR="${OPENCLAW_PLUGIN_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../lib" 2>/dev/null && pwd)}"

mode_guard() {
  local command_name="$1"
  local result
  result=$(python3 -c "
import sys, os
sys.path.insert(0, '${PLUGIN_LIB_DIR}')
from mode import check_mutation_allowed, get_mode
allowed, reason = check_mutation_allowed('${command_name}')
mode = get_mode()
if not allowed:
    print(f'BLOCKED|{reason}', end='')
    sys.exit(1)
elif reason == 'redirected_to_inbox':
    print(f'REDIRECT|{reason}', end='')
    sys.exit(0)
else:
    print(f'ALLOWED|{mode}', end='')
    sys.exit(0)
" 2>/dev/null)

  local exit_code=$?
  local status="${result%%|*}"
  local detail="${result#*|}"

  if [[ "$status" == "BLOCKED" ]]; then
    echo -e "\033[0;31m[BLOCKED]\033[0m $detail" >&2
    echo -e "\033[0;31m[BLOCKED]\033[0m Run 'openclaw-lacp-connect status' for connection info." >&2
    return 10
  fi

  # Export for callers that need to know
  export LACP_GUARD_STATUS="$status"
  export LACP_GUARD_DETAIL="$detail"
  return 0
}
```

### Step 2.2: Create shared mode-check Python helper

- [ ] Write `plugin/bin/lib/mode_check.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/lib/mode_check.py`

```python
#!/usr/bin/env python3
"""
Mode check helper for Python CLI scripts.

Usage:
    from lib.mode_check import guard_or_exit
    guard_or_exit("brain-resolve")
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Add plugin/lib to path
_lib_dir = str(Path(__file__).resolve().parent.parent.parent / "lib")
if _lib_dir not in sys.path:
    sys.path.insert(0, _lib_dir)

from mode import check_mutation_allowed, get_config


def guard_or_exit(command_name: str, *, json_output: bool = False) -> str:
    """
    Check if the command is allowed. Exit with code 10 if blocked.

    Returns:
        "allowed" — command can proceed normally
        "redirected_to_inbox" — command should write to inbox instead of graph
    """
    allowed, reason = check_mutation_allowed(command_name)

    if not allowed:
        config = get_config()
        if json_output:
            payload = {
                "ok": False,
                "kind": command_name.replace("-", "_"),
                "error": "mode_blocked",
                "mode": config.mode,
                "reason": reason,
            }
            print(json.dumps(payload, indent=2))
        else:
            print(f"\033[0;31m[BLOCKED]\033[0m {reason}", file=sys.stderr)
            print(
                f"\033[0;31m[BLOCKED]\033[0m Run 'openclaw-lacp-connect status' for connection info.",
                file=sys.stderr,
            )
        sys.exit(10)

    return reason if reason else "allowed"
```

### Step 2.3: Add mode guard to brain-expand (bash)

- [ ] Add mode guard to the top of `plugin/bin/openclaw-brain-expand`, after the `set -euo pipefail` line

Insert after line 7 (`set -euo pipefail`):

```bash
# --- Mode guard: block in connected mode ---
source "$(dirname "$0")/lib/mode-check.sh"
mode_guard "brain-expand" || exit $?
```

### Step 2.4: Add mode guard to brain-resolve (python)

- [ ] Add mode guard to `plugin/bin/openclaw-brain-resolve`, at the start of `main()`

Insert at the beginning of the `main()` function, before `args = build_parser().parse_args()`:

```python
    # Mode guard: block in connected mode
    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    from mode_check import guard_or_exit
    guard_or_exit("brain-resolve", json_output="--json" in sys.argv)
```

### Step 2.5: Add mode guard to obsidian-optimize (python)

- [ ] Add mode guard to `plugin/bin/openclaw-obsidian-optimize`, at the start of `main()`

Insert at the beginning of the `main()` function, before `args = build_parser().parse_args()`:

```python
    # Mode guard: block in connected mode
    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    from mode_check import guard_or_exit
    guard_or_exit("obsidian-optimize", json_output="--json" in sys.argv)
```

### Step 2.6: Add inbox redirect to brain-ingest (python)

- [ ] Add inbox redirect logic to `plugin/bin/openclaw-brain-ingest`

Insert after the imports at the top of the file (after `import hashlib`):

```python
from pathlib import Path as _Path
import sys as _sys
_sys.path.insert(0, str(_Path(__file__).resolve().parent / "lib"))
from mode_check import guard_or_exit

_INGEST_MODE_STATUS = guard_or_exit("brain-ingest", json_output="--json" in _sys.argv)
```

Then, in each `ingest_*` function, after the `inbox` path is computed, add a redirect check:

```python
    # In connected mode, force all writes to the agent inbox queue
    if _INGEST_MODE_STATUS == "redirected_to_inbox":
        from mode import get_inbox_queue_path
        inbox = Path(get_inbox_queue_path())
        inbox.mkdir(parents=True, exist_ok=True)
```

### Step 2.7: Write tests for mode guards

- [ ] Write test file `plugin/bin/tests/test_mode_guards.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/tests/test_mode_guards.py`

```python
"""Tests for mode guards on mutation commands."""

import json
import os
import subprocess
from pathlib import Path

import pytest

BIN_DIR = Path(__file__).resolve().parent.parent
BRAIN_RESOLVE = str(BIN_DIR / "openclaw-brain-resolve")
OBSIDIAN_OPTIMIZE = str(BIN_DIR / "openclaw-obsidian-optimize")


class TestBrainResolveBlocked:
    def test_connected_mode_blocks_resolve(self, tmp_path):
        env = os.environ.copy()
        env["LACP_MODE"] = "connected"
        env["OPENCLAW_HOME"] = str(tmp_path)
        result = subprocess.run(
            [
                "python3", BRAIN_RESOLVE,
                "--id", "test",
                "--resolution", "validated",
                "--reason", "test",
                "--vault", str(tmp_path),
                "--json",
            ],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 10
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"] == "mode_blocked"

    def test_standalone_allows_resolve(self, tmp_path):
        env = os.environ.copy()
        env["LACP_MODE"] = "standalone"
        env["OPENCLAW_HOME"] = str(tmp_path)
        # Will fail with vault_missing (exit 2) but NOT mode_blocked (exit 10)
        result = subprocess.run(
            [
                "python3", BRAIN_RESOLVE,
                "--id", "test",
                "--resolution", "validated",
                "--reason", "test",
                "--vault", "/tmp/nonexistent-guard-test",
                "--json",
            ],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 2  # vault_missing, not 10


class TestObsidianOptimizeBlocked:
    def test_connected_mode_blocks_optimize(self, tmp_path):
        env = os.environ.copy()
        env["LACP_MODE"] = "connected"
        env["OPENCLAW_HOME"] = str(tmp_path)
        result = subprocess.run(
            [
                "python3", OBSIDIAN_OPTIMIZE,
                "--vault", str(tmp_path),
                "--json",
            ],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 10
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"] == "mode_blocked"
```

### Step 2.8: Run tests and verify

- [ ] Run mode guard tests

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/bin/tests/test_mode_guards.py -v
```

**Expected output:** All 3 tests pass.

### Step 2.9: Commit

- [ ] Commit mode guards

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo
git add plugin/bin/lib/mode-check.sh plugin/bin/lib/mode_check.py plugin/bin/openclaw-brain-expand plugin/bin/openclaw-brain-resolve plugin/bin/openclaw-obsidian-optimize plugin/bin/openclaw-brain-ingest plugin/bin/tests/test_mode_guards.py
git commit -m "$(cat <<'EOF'
feat: add mode guards to mutation commands

brain-expand, brain-resolve, obsidian-optimize now check LACP_MODE before
running. In connected mode they exit with code 10 and a clear error message.
brain-ingest redirects writes to the agent inbox queue in connected mode.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Create invite token system

Build the invite token module that generates, validates, stores, and revokes invite tokens. Tokens are stored in `~/.openclaw/config/invites.json` on the curator. Each token encodes the target role, expiration, and a single-use flag.

### Step 3.1: Write plugin/lib/invites.py

- [ ] Write `plugin/lib/invites.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/invites.py`

```python
#!/usr/bin/env python3
"""
Invite token system for openclaw-lacp-fusion.

Tokens gate membership in a shared vault cluster. The curator generates tokens,
connected nodes redeem them during the join flow.

Token format: inv_<32 hex chars>
Storage: ~/.openclaw/config/invites.json
"""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, UTC, timedelta
from pathlib import Path
from typing import Optional


TOKEN_PREFIX = "inv_"
TOKEN_HEX_LENGTH = 32  # 16 bytes = 128 bits


@dataclass
class InviteToken:
    token: str
    email: str
    role: str  # developer, pm, executive, readonly
    created_at: str
    expires_at: str
    single_use: bool = True
    redeemed: bool = False
    redeemed_at: Optional[str] = None
    redeemed_by: Optional[str] = None
    revoked: bool = False


def _invites_path() -> Path:
    openclaw_home = os.environ.get("OPENCLAW_HOME", os.path.expanduser("~/.openclaw"))
    return Path(openclaw_home) / "config" / "invites.json"


def _load_invites() -> list[dict]:
    path = _invites_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("invites", [])
    except (json.JSONDecodeError, OSError):
        return []


def _save_invites(invites: list[dict]) -> Path:
    path = _invites_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"invites": invites}, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def generate_token(
    email: str,
    role: str = "developer",
    expires_hours: int = 72,
    single_use: bool = True,
) -> InviteToken:
    """Generate a new invite token and persist it."""
    valid_roles = ("developer", "pm", "executive", "readonly")
    if role not in valid_roles:
        raise ValueError(f"Invalid role: {role!r}. Must be one of {valid_roles}")

    now = datetime.now(UTC)
    token_str = TOKEN_PREFIX + secrets.token_hex(TOKEN_HEX_LENGTH // 2)

    invite = InviteToken(
        token=token_str,
        email=email,
        role=role,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(hours=expires_hours)).isoformat(),
        single_use=single_use,
    )

    invites = _load_invites()
    invites.append(asdict(invite))
    _save_invites(invites)

    return invite


def validate_token(token: str) -> tuple[bool, Optional[InviteToken], str]:
    """
    Validate an invite token.

    Returns (valid, invite_or_none, reason).
    """
    if not token.startswith(TOKEN_PREFIX):
        return False, None, "invalid_format"

    invites = _load_invites()
    for inv_dict in invites:
        if inv_dict["token"] != token:
            continue

        invite = InviteToken(**{k: v for k, v in inv_dict.items() if k in InviteToken.__dataclass_fields__})

        if invite.revoked:
            return False, invite, "revoked"

        if invite.single_use and invite.redeemed:
            return False, invite, "already_redeemed"

        now = datetime.now(UTC)
        expires = datetime.fromisoformat(invite.expires_at)
        if now > expires:
            return False, invite, "expired"

        return True, invite, "valid"

    return False, None, "not_found"


def redeem_token(token: str, redeemed_by: str = "") -> tuple[bool, str]:
    """
    Mark a token as redeemed.

    Returns (success, reason).
    """
    valid, invite, reason = validate_token(token)
    if not valid:
        return False, reason

    invites = _load_invites()
    now = datetime.now(UTC).isoformat()
    for inv_dict in invites:
        if inv_dict["token"] == token:
            inv_dict["redeemed"] = True
            inv_dict["redeemed_at"] = now
            inv_dict["redeemed_by"] = redeemed_by
            break

    _save_invites(invites)
    return True, "redeemed"


def revoke_token(token: str) -> tuple[bool, str]:
    """Revoke an invite token. Returns (success, reason)."""
    invites = _load_invites()
    for inv_dict in invites:
        if inv_dict["token"] == token:
            inv_dict["revoked"] = True
            _save_invites(invites)
            return True, "revoked"
    return False, "not_found"


def list_tokens(*, include_expired: bool = False) -> list[InviteToken]:
    """List all invite tokens, optionally including expired ones."""
    invites = _load_invites()
    now = datetime.now(UTC)
    result = []
    for inv_dict in invites:
        invite = InviteToken(**{k: v for k, v in inv_dict.items() if k in InviteToken.__dataclass_fields__})
        if not include_expired:
            expires = datetime.fromisoformat(invite.expires_at)
            if now > expires and not invite.redeemed:
                continue
        result.append(invite)
    return result
```

### Step 3.2: Write tests for invite module

- [ ] Write test file `plugin/lib/tests/test_invites.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/tests/test_invites.py`

```python
"""Tests for plugin.lib.invites -- invite token system."""

import json
import sys
from datetime import datetime, UTC, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lib.invites import (
    generate_token,
    validate_token,
    redeem_token,
    revoke_token,
    list_tokens,
    TOKEN_PREFIX,
)


class TestGenerateToken:
    def test_generates_valid_format(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        invite = generate_token("dev@example.com", role="developer")
        assert invite.token.startswith(TOKEN_PREFIX)
        assert len(invite.token) == len(TOKEN_PREFIX) + 32
        assert invite.email == "dev@example.com"
        assert invite.role == "developer"
        assert invite.redeemed is False

    def test_invalid_role_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        with pytest.raises(ValueError, match="Invalid role"):
            generate_token("x@x.com", role="admin")

    def test_persists_to_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        invite = generate_token("a@b.com")
        path = tmp_path / "config" / "invites.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert len(data["invites"]) == 1
        assert data["invites"][0]["token"] == invite.token


class TestValidateToken:
    def test_valid_token(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        invite = generate_token("a@b.com")
        valid, found, reason = validate_token(invite.token)
        assert valid is True
        assert reason == "valid"
        assert found.email == "a@b.com"

    def test_invalid_format(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        valid, _, reason = validate_token("not_a_token")
        assert valid is False
        assert reason == "invalid_format"

    def test_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        valid, _, reason = validate_token("inv_" + "a" * 32)
        assert valid is False
        assert reason == "not_found"

    def test_expired_token(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        invite = generate_token("a@b.com", expires_hours=0)
        # Token expires immediately (0 hours)
        valid, _, reason = validate_token(invite.token)
        # With 0 hours it should still be valid at the exact moment
        # Use -1 to force expiration by manipulating the file
        path = tmp_path / "config" / "invites.json"
        data = json.loads(path.read_text())
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        data["invites"][0]["expires_at"] = past
        path.write_text(json.dumps(data))
        valid, _, reason = validate_token(invite.token)
        assert valid is False
        assert reason == "expired"


class TestRedeemToken:
    def test_redeem_works(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        invite = generate_token("a@b.com")
        ok, reason = redeem_token(invite.token, redeemed_by="agent-001")
        assert ok is True
        assert reason == "redeemed"

    def test_double_redeem_single_use(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        invite = generate_token("a@b.com", single_use=True)
        redeem_token(invite.token)
        valid, _, reason = validate_token(invite.token)
        assert valid is False
        assert reason == "already_redeemed"


class TestRevokeToken:
    def test_revoke_works(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        invite = generate_token("a@b.com")
        ok, reason = revoke_token(invite.token)
        assert ok is True
        valid, _, reason = validate_token(invite.token)
        assert valid is False
        assert reason == "revoked"

    def test_revoke_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        ok, reason = revoke_token("inv_" + "b" * 32)
        assert ok is False
        assert reason == "not_found"


class TestListTokens:
    def test_list_active(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        generate_token("a@b.com")
        generate_token("c@d.com")
        tokens = list_tokens()
        assert len(tokens) == 2

    def test_list_excludes_expired_by_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
        invite = generate_token("a@b.com")
        # Manually expire it
        path = tmp_path / "config" / "invites.json"
        data = json.loads(path.read_text())
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        data["invites"][0]["expires_at"] = past
        path.write_text(json.dumps(data))
        assert len(list_tokens()) == 0
        assert len(list_tokens(include_expired=True)) == 1
```

### Step 3.3: Run tests and verify

- [ ] Run invite module tests

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/lib/tests/test_invites.py -v
```

**Expected output:** All 12 tests pass.

### Step 3.4: Commit

- [ ] Commit invite token system

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo
git add plugin/lib/invites.py plugin/lib/tests/test_invites.py
git commit -m "$(cat <<'EOF'
feat: add invite token system for shared vault membership

Generate, validate, redeem, and revoke invite tokens. Tokens are stored in
~/.openclaw/config/invites.json. Supports single-use, expiration, role
assignment (developer/pm/executive/readonly).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Create heartbeat system

Implement the heartbeat writer (curator side) and heartbeat monitor (connected node side). The curator writes `.curator-heartbeat.json` to the shared vault after every cycle. Connected nodes read it and alert on missed heartbeats.

### Step 4.1: Write plugin/lib/heartbeat.py

- [ ] Write `plugin/lib/heartbeat.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/heartbeat.py`

```python
#!/usr/bin/env python3
"""
Heartbeat system for openclaw-lacp-fusion.

Curator side: write_heartbeat() after each cycle.
Connected side: check_heartbeat() to detect outages.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, UTC, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

HEARTBEAT_FILENAME = ".curator-heartbeat.json"
# Default cycle interval in hours (used to compute missed heartbeats)
DEFAULT_CYCLE_HOURS = 4
# Number of missed heartbeats before alert
ALERT_THRESHOLD = 3


@dataclass
class OutageRecord:
    start: str
    end: Optional[str] = None
    files_queued_during_outage: int = 0
    reconciliation_status: str = "pending"  # pending | in_progress | completed


@dataclass
class HeartbeatData:
    last_seen: str
    status: str  # healthy | degraded | recovering
    cycle_duration_seconds: float = 0.0
    notes_processed: int = 0
    next_cycle: str = ""
    missed_heartbeats: int = 0
    outage_log: list[dict] = field(default_factory=list)


def _heartbeat_path(vault_path: str = "") -> Path:
    if not vault_path:
        vault_path = os.environ.get("LACP_OBSIDIAN_VAULT", "")
    if not vault_path:
        vault_path = os.environ.get("OPENCLAW_VAULT", "")
    if not vault_path:
        openclaw_home = os.environ.get("OPENCLAW_HOME", os.path.expanduser("~/.openclaw"))
        vault_path = os.path.join(openclaw_home, "data", "knowledge")
    return Path(vault_path) / HEARTBEAT_FILENAME


def write_heartbeat(
    vault_path: str = "",
    *,
    cycle_duration_seconds: float = 0.0,
    notes_processed: int = 0,
    cycle_interval_hours: float = DEFAULT_CYCLE_HOURS,
) -> Path:
    """Write heartbeat file to the shared vault (curator side)."""
    path = _heartbeat_path(vault_path)
    now = datetime.now(UTC)

    # Load existing data to preserve outage_log
    existing_outage_log: list[dict] = []
    existing_missed: int = 0
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            existing_outage_log = old.get("outage_log", [])
            existing_missed = old.get("missed_heartbeats", 0)
        except (json.JSONDecodeError, OSError):
            pass

    # If we had missed heartbeats, close the outage
    if existing_missed >= ALERT_THRESHOLD:
        outage_record = {
            "start": _estimate_outage_start(existing_missed, cycle_interval_hours),
            "end": now.isoformat(),
            "files_queued_during_outage": 0,  # Will be updated during reconciliation
            "reconciliation_status": "pending",
        }
        existing_outage_log.append(outage_record)

    heartbeat = HeartbeatData(
        last_seen=now.isoformat(),
        status="recovering" if existing_missed >= ALERT_THRESHOLD else "healthy",
        cycle_duration_seconds=cycle_duration_seconds,
        notes_processed=notes_processed,
        next_cycle=(now + timedelta(hours=cycle_interval_hours)).isoformat(),
        missed_heartbeats=0,
        outage_log=existing_outage_log,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(heartbeat), indent=2) + "\n", encoding="utf-8")
    return path


def _estimate_outage_start(missed: int, interval_hours: float) -> str:
    """Estimate when the outage started based on missed heartbeats."""
    now = datetime.now(UTC)
    start = now - timedelta(hours=missed * interval_hours)
    return start.isoformat()


def check_heartbeat(
    vault_path: str = "",
    *,
    cycle_interval_hours: float = DEFAULT_CYCLE_HOURS,
) -> dict:
    """
    Check curator heartbeat (connected node side).

    Returns a status dict:
      - status: "healthy" | "warning" | "outage" | "no_heartbeat"
      - last_seen: ISO timestamp or None
      - missed_heartbeats: int
      - message: human-readable status
    """
    path = _heartbeat_path(vault_path)

    if not path.exists():
        return {
            "status": "no_heartbeat",
            "last_seen": None,
            "missed_heartbeats": 0,
            "message": "No heartbeat file found. Curator may not be configured.",
        }

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return {
            "status": "no_heartbeat",
            "last_seen": None,
            "missed_heartbeats": 0,
            "message": f"Failed to read heartbeat: {e}",
        }

    last_seen_str = data.get("last_seen", "")
    if not last_seen_str:
        return {
            "status": "no_heartbeat",
            "last_seen": None,
            "missed_heartbeats": 0,
            "message": "Heartbeat file exists but has no last_seen timestamp.",
        }

    last_seen = datetime.fromisoformat(last_seen_str)
    now = datetime.now(UTC)
    elapsed = now - last_seen
    expected_interval = timedelta(hours=cycle_interval_hours)
    missed = max(0, int(elapsed / expected_interval) - 1)

    if missed == 0:
        status = "healthy"
        ago = _format_elapsed(elapsed)
        message = f"Curator healthy (last seen: {ago} ago)"
    elif missed < ALERT_THRESHOLD:
        status = "warning"
        ago = _format_elapsed(elapsed)
        message = f"Curator heartbeat delayed ({missed} missed, last seen: {ago} ago)"
    else:
        status = "outage"
        ago = _format_elapsed(elapsed)
        message = f"Curator heartbeat missed ({missed} missed, last seen: {ago} ago)"

    return {
        "status": status,
        "last_seen": last_seen_str,
        "missed_heartbeats": missed,
        "message": message,
        "outage_log": data.get("outage_log", []),
    }


def update_outage_reconciliation(
    vault_path: str = "",
    *,
    files_queued: int = 0,
    reconciliation_status: str = "completed",
) -> bool:
    """Update the most recent outage record after reconciliation."""
    path = _heartbeat_path(vault_path)
    if not path.exists():
        return False

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    outage_log = data.get("outage_log", [])
    if not outage_log:
        return False

    # Update the most recent outage
    outage_log[-1]["files_queued_during_outage"] = files_queued
    outage_log[-1]["reconciliation_status"] = reconciliation_status
    data["outage_log"] = outage_log

    if reconciliation_status == "completed":
        data["status"] = "healthy"

    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def _format_elapsed(td: timedelta) -> str:
    """Format a timedelta as human-readable string."""
    total_seconds = int(td.total_seconds())
    if total_seconds < 60:
        return f"{total_seconds}s"
    if total_seconds < 3600:
        return f"{total_seconds // 60}m"
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if minutes:
        return f"{hours}h {minutes}m"
    return f"{hours}h"
```

### Step 4.2: Write tests for heartbeat module

- [ ] Write test file `plugin/lib/tests/test_heartbeat.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/tests/test_heartbeat.py`

```python
"""Tests for plugin.lib.heartbeat -- heartbeat system."""

import json
import sys
from datetime import datetime, UTC, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lib.heartbeat import (
    write_heartbeat,
    check_heartbeat,
    update_outage_reconciliation,
    HEARTBEAT_FILENAME,
    ALERT_THRESHOLD,
)


class TestWriteHeartbeat:
    def test_creates_heartbeat_file(self, tmp_path):
        vault = str(tmp_path / "vault")
        Path(vault).mkdir()
        path = write_heartbeat(vault, cycle_duration_seconds=42, notes_processed=18)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["status"] == "healthy"
        assert data["cycle_duration_seconds"] == 42
        assert data["notes_processed"] == 18
        assert data["missed_heartbeats"] == 0

    def test_preserves_outage_log(self, tmp_path):
        vault = str(tmp_path / "vault")
        Path(vault).mkdir()
        # Write initial heartbeat
        write_heartbeat(vault)
        # Manually add outage_log entry
        hb_path = Path(vault) / HEARTBEAT_FILENAME
        data = json.loads(hb_path.read_text())
        data["outage_log"] = [{"start": "2026-01-01T00:00:00", "end": "2026-01-01T06:00:00", "files_queued_during_outage": 5, "reconciliation_status": "completed"}]
        hb_path.write_text(json.dumps(data))
        # Write another heartbeat
        write_heartbeat(vault)
        data2 = json.loads(hb_path.read_text())
        assert len(data2["outage_log"]) == 1


class TestCheckHeartbeat:
    def test_no_file_returns_no_heartbeat(self, tmp_path):
        result = check_heartbeat(str(tmp_path))
        assert result["status"] == "no_heartbeat"

    def test_recent_heartbeat_is_healthy(self, tmp_path):
        vault = str(tmp_path / "vault")
        Path(vault).mkdir()
        write_heartbeat(vault)
        result = check_heartbeat(vault)
        assert result["status"] == "healthy"
        assert result["missed_heartbeats"] == 0

    def test_old_heartbeat_triggers_warning(self, tmp_path):
        vault = str(tmp_path / "vault")
        Path(vault).mkdir()
        write_heartbeat(vault)
        # Backdate the heartbeat
        hb_path = Path(vault) / HEARTBEAT_FILENAME
        data = json.loads(hb_path.read_text())
        old_time = (datetime.now(UTC) - timedelta(hours=9)).isoformat()
        data["last_seen"] = old_time
        hb_path.write_text(json.dumps(data))
        result = check_heartbeat(vault, cycle_interval_hours=4)
        assert result["status"] == "warning"
        assert result["missed_heartbeats"] >= 1

    def test_very_old_heartbeat_triggers_outage(self, tmp_path):
        vault = str(tmp_path / "vault")
        Path(vault).mkdir()
        write_heartbeat(vault)
        hb_path = Path(vault) / HEARTBEAT_FILENAME
        data = json.loads(hb_path.read_text())
        old_time = (datetime.now(UTC) - timedelta(hours=20)).isoformat()
        data["last_seen"] = old_time
        hb_path.write_text(json.dumps(data))
        result = check_heartbeat(vault, cycle_interval_hours=4)
        assert result["status"] == "outage"
        assert result["missed_heartbeats"] >= ALERT_THRESHOLD


class TestOutageReconciliation:
    def test_update_reconciliation(self, tmp_path):
        vault = str(tmp_path / "vault")
        Path(vault).mkdir()
        write_heartbeat(vault)
        hb_path = Path(vault) / HEARTBEAT_FILENAME
        # Simulate outage recovery (heartbeat with missed >= ALERT_THRESHOLD)
        data = json.loads(hb_path.read_text())
        data["missed_heartbeats"] = ALERT_THRESHOLD
        hb_path.write_text(json.dumps(data))
        # Write recovery heartbeat (this should close the outage)
        write_heartbeat(vault)
        data2 = json.loads(hb_path.read_text())
        assert len(data2["outage_log"]) == 1
        assert data2["outage_log"][-1]["reconciliation_status"] == "pending"
        # Now reconcile
        update_outage_reconciliation(vault, files_queued=7, reconciliation_status="completed")
        data3 = json.loads(hb_path.read_text())
        assert data3["outage_log"][-1]["files_queued_during_outage"] == 7
        assert data3["outage_log"][-1]["reconciliation_status"] == "completed"
        assert data3["status"] == "healthy"
```

### Step 4.3: Run tests and verify

- [ ] Run heartbeat module tests

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/lib/tests/test_heartbeat.py -v
```

**Expected output:** All 7 tests pass.

### Step 4.4: Commit

- [ ] Commit heartbeat system

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo
git add plugin/lib/heartbeat.py plugin/lib/tests/test_heartbeat.py
git commit -m "$(cat <<'EOF'
feat: add heartbeat system for curator health monitoring

Curator writes .curator-heartbeat.json after each cycle. Connected nodes
check for missed heartbeats (3+ triggers outage alert). Supports outage
logging and reconciliation tracking after recovery.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Create ob sync daemon management

Build daemon management for `ob sync --continuous` as a background process. Uses launchd on macOS and systemd on Linux. Provides start/stop/status operations.

### Step 5.1: Write plugin/lib/sync_daemon.py

- [ ] Write `plugin/lib/sync_daemon.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/sync_daemon.py`

```python
#!/usr/bin/env python3
"""
ob sync daemon management for openclaw-lacp-fusion.

Manages `ob sync --continuous` as a background daemon:
  - macOS: launchd plist
  - Linux: systemd user unit

Provides start(), stop(), status() operations.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DAEMON_LABEL = "io.openclaw.ob-sync"
SYSTEMD_UNIT = "openclaw-ob-sync.service"


@dataclass
class DaemonStatus:
    running: bool
    pid: Optional[int]
    platform: str  # "macos" | "linux" | "unsupported"
    method: str  # "launchd" | "systemd" | "none"
    message: str

    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "pid": self.pid,
            "platform": self.platform,
            "method": self.method,
            "message": self.message,
        }


def _detect_platform() -> tuple[str, str]:
    """Detect OS and daemon method. Returns (platform, method)."""
    system = platform.system().lower()
    if system == "darwin":
        return "macos", "launchd"
    elif system == "linux":
        return "linux", "systemd"
    return "unsupported", "none"


def _ob_binary() -> str:
    """Find the ob binary path."""
    ob = shutil.which("ob")
    if ob:
        return ob
    # Common locations
    for candidate in [
        "/usr/local/bin/ob",
        os.path.expanduser("~/.npm-global/bin/ob"),
        os.path.expanduser("~/.local/bin/ob"),
    ]:
        if os.path.isfile(candidate):
            return candidate
    return "ob"  # Fall back, let PATH resolve


def _vault_path() -> str:
    """Resolve the vault path for the daemon."""
    from mode import get_config
    return get_config().vault_path


# ---------------------------------------------------------------------------
# macOS launchd
# ---------------------------------------------------------------------------

def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{DAEMON_LABEL}.plist"


def _generate_plist(vault_path: str) -> str:
    ob = _ob_binary()
    log_dir = Path.home() / ".openclaw" / "logs"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{DAEMON_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{ob}</string>
        <string>sync</string>
        <string>--continuous</string>
        <string>--vault</string>
        <string>{vault_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_dir}/ob-sync.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/ob-sync.stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:{Path.home()}/.npm-global/bin</string>
    </dict>
</dict>
</plist>
"""


def _launchd_start(vault_path: str) -> DaemonStatus:
    plist = _plist_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    log_dir = Path.home() / ".openclaw" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    plist.write_text(_generate_plist(vault_path), encoding="utf-8")

    result = subprocess.run(
        ["launchctl", "load", "-w", str(plist)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return DaemonStatus(
            running=False, pid=None, platform="macos", method="launchd",
            message=f"launchctl load failed: {result.stderr.strip()}",
        )

    return _launchd_status()


def _launchd_stop() -> DaemonStatus:
    plist = _plist_path()
    if not plist.exists():
        return DaemonStatus(
            running=False, pid=None, platform="macos", method="launchd",
            message="Daemon not installed (no plist found)",
        )

    subprocess.run(
        ["launchctl", "unload", "-w", str(plist)],
        capture_output=True, text=True,
    )
    plist.unlink(missing_ok=True)

    return DaemonStatus(
        running=False, pid=None, platform="macos", method="launchd",
        message="Daemon stopped and unloaded",
    )


def _launchd_status() -> DaemonStatus:
    result = subprocess.run(
        ["launchctl", "list", DAEMON_LABEL],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return DaemonStatus(
            running=False, pid=None, platform="macos", method="launchd",
            message="Daemon not running",
        )

    # Parse PID from launchctl list output
    pid = None
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 1:
            try:
                pid = int(parts[0])
            except (ValueError, IndexError):
                pass
    running = pid is not None and pid > 0

    return DaemonStatus(
        running=running, pid=pid if running else None,
        platform="macos", method="launchd",
        message=f"Daemon running (PID {pid})" if running else "Daemon loaded but not running",
    )


# ---------------------------------------------------------------------------
# Linux systemd
# ---------------------------------------------------------------------------

def _unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / SYSTEMD_UNIT


def _generate_unit(vault_path: str) -> str:
    ob = _ob_binary()
    return f"""[Unit]
Description=OpenClaw ob sync daemon
After=network.target

[Service]
Type=simple
ExecStart={ob} sync --continuous --vault {vault_path}
Restart=always
RestartSec=10
Environment=PATH=/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=default.target
"""


def _systemd_start(vault_path: str) -> DaemonStatus:
    unit = _unit_path()
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(_generate_unit(vault_path), encoding="utf-8")

    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    result = subprocess.run(
        ["systemctl", "--user", "enable", "--now", SYSTEMD_UNIT],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return DaemonStatus(
            running=False, pid=None, platform="linux", method="systemd",
            message=f"systemctl enable failed: {result.stderr.strip()}",
        )

    return _systemd_status()


def _systemd_stop() -> DaemonStatus:
    subprocess.run(
        ["systemctl", "--user", "disable", "--now", SYSTEMD_UNIT],
        capture_output=True, text=True,
    )
    unit = _unit_path()
    unit.unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)

    return DaemonStatus(
        running=False, pid=None, platform="linux", method="systemd",
        message="Daemon stopped and disabled",
    )


def _systemd_status() -> DaemonStatus:
    result = subprocess.run(
        ["systemctl", "--user", "is-active", SYSTEMD_UNIT],
        capture_output=True, text=True,
    )
    active = result.stdout.strip() == "active"

    pid = None
    if active:
        pid_result = subprocess.run(
            ["systemctl", "--user", "show", SYSTEMD_UNIT, "--property=MainPID", "--value"],
            capture_output=True, text=True,
        )
        try:
            pid = int(pid_result.stdout.strip())
            if pid == 0:
                pid = None
        except ValueError:
            pass

    return DaemonStatus(
        running=active, pid=pid,
        platform="linux", method="systemd",
        message=f"Daemon running (PID {pid})" if active else "Daemon not running",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start(vault_path: str = "") -> DaemonStatus:
    """Start the ob sync daemon."""
    if not vault_path:
        vault_path = _vault_path()

    plat, method = _detect_platform()
    if method == "launchd":
        return _launchd_start(vault_path)
    elif method == "systemd":
        return _systemd_start(vault_path)
    return DaemonStatus(
        running=False, pid=None, platform=plat, method=method,
        message=f"Unsupported platform: {plat}. Manually run: ob sync --continuous --vault {vault_path}",
    )


def stop() -> DaemonStatus:
    """Stop the ob sync daemon."""
    plat, method = _detect_platform()
    if method == "launchd":
        return _launchd_stop()
    elif method == "systemd":
        return _systemd_stop()
    return DaemonStatus(
        running=False, pid=None, platform=plat, method=method,
        message=f"Unsupported platform: {plat}",
    )


def status() -> DaemonStatus:
    """Check the ob sync daemon status."""
    plat, method = _detect_platform()
    if method == "launchd":
        return _launchd_status()
    elif method == "systemd":
        return _systemd_status()
    return DaemonStatus(
        running=False, pid=None, platform=plat, method=method,
        message=f"Unsupported platform: {plat}",
    )
```

### Step 5.2: Write tests for sync daemon module

- [ ] Write test file `plugin/lib/tests/test_sync_daemon.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/tests/test_sync_daemon.py`

```python
"""Tests for plugin.lib.sync_daemon -- ob sync daemon management.

Note: These tests verify the code paths and generated configs without
actually starting/stopping system daemons. Integration tests require
a real ob binary and are run separately.
"""

import platform
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lib.sync_daemon import (
    DAEMON_LABEL,
    SYSTEMD_UNIT,
    DaemonStatus,
    _detect_platform,
    _generate_plist,
    _generate_unit,
    _plist_path,
    _unit_path,
)


class TestDetectPlatform:
    def test_darwin(self, monkeypatch):
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        plat, method = _detect_platform()
        assert plat == "macos"
        assert method == "launchd"

    def test_linux(self, monkeypatch):
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        plat, method = _detect_platform()
        assert plat == "linux"
        assert method == "systemd"

    def test_unsupported(self, monkeypatch):
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        plat, method = _detect_platform()
        assert plat == "unsupported"
        assert method == "none"


class TestGeneratePlist:
    def test_plist_contains_label(self):
        plist = _generate_plist("/path/to/vault")
        assert DAEMON_LABEL in plist
        assert "/path/to/vault" in plist
        assert "sync" in plist
        assert "--continuous" in plist

    def test_plist_is_valid_xml(self):
        plist = _generate_plist("/vault")
        assert plist.startswith("<?xml")
        assert "</plist>" in plist


class TestGenerateUnit:
    def test_unit_contains_service(self):
        unit = _generate_unit("/path/to/vault")
        assert "[Service]" in unit
        assert "/path/to/vault" in unit
        assert "sync --continuous" in unit
        assert "Restart=always" in unit


class TestDaemonStatus:
    def test_status_to_dict(self):
        s = DaemonStatus(running=True, pid=1234, platform="macos", method="launchd", message="ok")
        d = s.to_dict()
        assert d["running"] is True
        assert d["pid"] == 1234
        assert d["platform"] == "macos"
```

### Step 5.3: Run tests and verify

- [ ] Run sync daemon tests

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/lib/tests/test_sync_daemon.py -v
```

**Expected output:** All 7 tests pass.

### Step 5.4: Commit

- [ ] Commit sync daemon management

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo
git add plugin/lib/sync_daemon.py plugin/lib/tests/test_sync_daemon.py
git commit -m "$(cat <<'EOF'
feat: add ob sync daemon management (launchd/systemd)

Start/stop/status for `ob sync --continuous` as a background daemon.
Generates launchd plist on macOS and systemd user unit on Linux.
Auto-restart on failure, log output to ~/.openclaw/logs/.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Create curator HTTP surface

Build a minimal Python HTTP server with 3 endpoints: POST /validate, POST /health, POST /notify. All endpoints require Bearer token authentication.

### Step 6.1: Write plugin/lib/curator_http.py

- [ ] Write `plugin/lib/curator_http.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/curator_http.py`

```python
#!/usr/bin/env python3
"""
Curator HTTP surface for openclaw-lacp-fusion.

Minimal HTTP server with 3 endpoints, all behind token authentication:
  POST /validate — Validate an invite token, return vault config
  POST /health   — Return curator status, last cycle time, graph stats
  POST /notify   — Fast-path notification for high-priority inbox items

Usage:
  python3 -m lib.curator_http --port 9100 --token <admin-token>

Or programmatically:
  from lib.curator_http import create_server, run_server
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, UTC
from functools import partial
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Optional

# Ensure lib is importable
_lib_dir = str(Path(__file__).resolve().parent)
if _lib_dir not in sys.path:
    sys.path.insert(0, _lib_dir)

from heartbeat import check_heartbeat, HEARTBEAT_FILENAME
from invites import validate_token, redeem_token

logger = logging.getLogger(__name__)

DEFAULT_PORT = 9100


class CuratorHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the curator surface."""

    # Set by the server factory
    admin_token: str = ""
    vault_path: str = ""
    vault_name: str = "Company Brain"
    on_notify: Optional[Any] = None  # callback(file, priority)

    def log_message(self, format: str, *args: Any) -> None:
        logger.info(format % args)

    def _send_json(self, status_code: int, data: dict) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self._send_json(401, {"error": "missing_auth", "message": "Authorization header required"})
            return False
        token = auth[len("Bearer "):]
        if token != self.admin_token:
            self._send_json(403, {"error": "invalid_token", "message": "Invalid authentication token"})
            return False
        return True

    def do_POST(self) -> None:
        if not self._check_auth():
            return

        if self.path == "/validate":
            self._handle_validate()
        elif self.path == "/health":
            self._handle_health()
        elif self.path == "/notify":
            self._handle_notify()
        else:
            self._send_json(404, {"error": "not_found", "message": f"Unknown endpoint: {self.path}"})

    def _handle_validate(self) -> None:
        body = self._read_body()
        invite_token = body.get("token", "")
        if not invite_token:
            self._send_json(400, {"error": "missing_token", "message": "token field required"})
            return

        valid, invite, reason = validate_token(invite_token)
        if not valid:
            self._send_json(200, {"valid": False, "reason": reason})
            return

        # Return vault config for the joining node
        self._send_json(200, {
            "valid": True,
            "vault_name": self.vault_name,
            "role": invite.role,
            "ob_sync_config": {
                "vault_name": self.vault_name,
                "vault_path": "~/.openclaw/vault",
            },
        })

    def _handle_health(self) -> None:
        hb = check_heartbeat(self.vault_path)
        vault = Path(self.vault_path) if self.vault_path else None

        note_count = 0
        inbox_pending = 0
        if vault and vault.exists():
            note_count = sum(1 for _ in vault.rglob("*.md") if "/.obsidian/" not in _.as_posix())
            inbox_dir = vault / "05_Inbox"
            if inbox_dir.exists():
                inbox_pending = sum(1 for _ in inbox_dir.rglob("*.md"))

        self._send_json(200, {
            "status": hb.get("status", "unknown"),
            "last_cycle": hb.get("last_seen"),
            "notes": note_count,
            "inbox_pending": inbox_pending,
            "message": hb.get("message", ""),
        })

    def _handle_notify(self) -> None:
        body = self._read_body()
        file_path = body.get("file", "")
        priority = body.get("priority", "normal")

        if not file_path:
            self._send_json(400, {"error": "missing_file", "message": "file field required"})
            return

        # Call the notify callback if registered
        if self.on_notify:
            try:
                self.on_notify(file_path, priority)
            except Exception as e:
                logger.error("Notify callback failed: %s", e)

        self._send_json(200, {
            "accepted": True,
            "file": file_path,
            "priority": priority,
        })


def create_server(
    port: int = DEFAULT_PORT,
    admin_token: str = "",
    vault_path: str = "",
    vault_name: str = "Company Brain",
    on_notify: Optional[Any] = None,
) -> HTTPServer:
    """Create and configure the curator HTTP server."""
    CuratorHandler.admin_token = admin_token
    CuratorHandler.vault_path = vault_path
    CuratorHandler.vault_name = vault_name
    CuratorHandler.on_notify = on_notify

    server = HTTPServer(("0.0.0.0", port), CuratorHandler)
    return server


def run_server(
    port: int = DEFAULT_PORT,
    admin_token: str = "",
    vault_path: str = "",
    vault_name: str = "Company Brain",
) -> None:
    """Run the curator HTTP server (blocking)."""
    if not admin_token:
        admin_token = os.environ.get("LACP_CURATOR_TOKEN", "")
    if not admin_token:
        print("ERROR: --token or LACP_CURATOR_TOKEN required", file=sys.stderr)
        sys.exit(1)

    server = create_server(
        port=port,
        admin_token=admin_token,
        vault_path=vault_path,
        vault_name=vault_name,
    )
    logger.info("Curator HTTP surface listening on port %d", port)
    print(f"Curator HTTP surface listening on port {port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        print("\nCurator HTTP surface stopped.", file=sys.stderr)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    p = argparse.ArgumentParser(description="Curator HTTP surface")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--token", default=os.environ.get("LACP_CURATOR_TOKEN", ""))
    p.add_argument("--vault", default=os.environ.get("LACP_OBSIDIAN_VAULT", ""))
    p.add_argument("--vault-name", default="Company Brain")
    args = p.parse_args()

    run_server(
        port=args.port,
        admin_token=args.token,
        vault_path=args.vault,
        vault_name=args.vault_name,
    )
```

### Step 6.2: Write tests for curator HTTP surface

- [ ] Write test file `plugin/lib/tests/test_curator_http.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/tests/test_curator_http.py`

```python
"""Tests for plugin.lib.curator_http -- curator HTTP surface."""

import json
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lib.curator_http import create_server, DEFAULT_PORT
from lib.invites import generate_token


TEST_TOKEN = "test_admin_token_abc123"


@pytest.fixture()
def curator_server(tmp_path, monkeypatch):
    """Start a test curator server on a random high port."""
    monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
    vault = tmp_path / "vault"
    vault.mkdir()
    # Create some notes
    (vault / "test.md").write_text("---\ntitle: test\n---\n# Test\n")
    inbox = vault / "05_Inbox" / "queue-agent"
    inbox.mkdir(parents=True)
    (inbox / "pending.md").write_text("# Pending\n")

    port = 19876  # High port unlikely to collide
    server = create_server(
        port=port,
        admin_token=TEST_TOKEN,
        vault_path=str(vault),
        vault_name="Test Brain",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://localhost:{port}", vault
    server.shutdown()


def _post(url: str, data: dict, token: str = TEST_TOKEN) -> tuple[int, dict]:
    """Helper to POST JSON."""
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class TestAuth:
    def test_missing_auth(self, curator_server):
        base_url, _ = curator_server
        body = json.dumps({}).encode()
        req = urllib.request.Request(
            f"{base_url}/health",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req)
            assert False, "Should have raised"
        except urllib.error.HTTPError as e:
            assert e.code == 401

    def test_invalid_token(self, curator_server):
        base_url, _ = curator_server
        status, data = _post(f"{base_url}/health", {}, token="wrong")
        assert status == 403


class TestHealthEndpoint:
    def test_health_returns_status(self, curator_server):
        base_url, _ = curator_server
        status, data = _post(f"{base_url}/health", {})
        assert status == 200
        assert "status" in data
        assert "notes" in data
        assert data["notes"] >= 1  # test.md + pending.md


class TestValidateEndpoint:
    def test_validate_missing_token(self, curator_server):
        base_url, _ = curator_server
        status, data = _post(f"{base_url}/validate", {})
        assert status == 400
        assert data["error"] == "missing_token"

    def test_validate_invalid_token(self, curator_server):
        base_url, _ = curator_server
        status, data = _post(f"{base_url}/validate", {"token": "inv_" + "x" * 32})
        assert status == 200
        assert data["valid"] is False

    def test_validate_valid_token(self, curator_server):
        base_url, _ = curator_server
        invite = generate_token("dev@test.com", role="developer")
        status, data = _post(f"{base_url}/validate", {"token": invite.token})
        assert status == 200
        assert data["valid"] is True
        assert data["role"] == "developer"
        assert data["vault_name"] == "Test Brain"


class TestNotifyEndpoint:
    def test_notify_missing_file(self, curator_server):
        base_url, _ = curator_server
        status, data = _post(f"{base_url}/notify", {})
        assert status == 400

    def test_notify_accepted(self, curator_server):
        base_url, _ = curator_server
        status, data = _post(f"{base_url}/notify", {"file": "05_Inbox/queue-agent/urgent.md", "priority": "high"})
        assert status == 200
        assert data["accepted"] is True
        assert data["priority"] == "high"


class TestNotFound:
    def test_unknown_endpoint(self, curator_server):
        base_url, _ = curator_server
        status, data = _post(f"{base_url}/unknown", {})
        assert status == 404
```

### Step 6.3: Run tests and verify

- [ ] Run curator HTTP tests

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/lib/tests/test_curator_http.py -v
```

**Expected output:** All 8 tests pass.

### Step 6.4: Commit

- [ ] Commit curator HTTP surface

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo
git add plugin/lib/curator_http.py plugin/lib/tests/test_curator_http.py
git commit -m "$(cat <<'EOF'
feat: add curator HTTP surface (validate, health, notify)

Minimal Python HTTP server with 3 endpoints behind Bearer token auth.
POST /validate: check invite tokens and return vault config.
POST /health: return curator status, note count, inbox size.
POST /notify: fast-path notification for high-priority inbox items.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Create openclaw-lacp-connect CLI

Build the full `openclaw-lacp-connect` CLI with subcommands: invite, join, status, disconnect, pause, resume, set-role, health, members.

### Step 7.1: Write plugin/bin/openclaw-lacp-connect

- [ ] Write `plugin/bin/openclaw-lacp-connect`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-lacp-connect`

```python
#!/usr/bin/env python3
"""
openclaw-lacp-connect — Manage connection between agent nodes and the curator.

Commands:
  invite    Generate an invite token (curator admin only)
  join      Connect to a shared vault using an invite token
  status    Show connection status, vault stats, sync daemon info
  disconnect  Disconnect from shared vault (keeps local copy)
  pause     Pause sync (keep local copy, stop daemon)
  resume    Resume sync (restart daemon)
  set-role  Change agent role
  health    Detailed health check
  members   List connected members (curator admin only)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

# Add plugin/lib to path
_lib_dir = str(Path(__file__).resolve().parent.parent / "lib")
if _lib_dir not in sys.path:
    sys.path.insert(0, _lib_dir)

from mode import get_config, get_mode, set_mode, VALID_MODES
from invites import generate_token, list_tokens, revoke_token
from heartbeat import check_heartbeat
from sync_daemon import start as daemon_start, stop as daemon_stop, status as daemon_status

GREEN = "\033[0;32m"
BLUE = "\033[0;34m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
NC = "\033[0m"


def _post_curator(url: str, endpoint: str, data: dict, token: str) -> tuple[int, dict]:
    """POST JSON to a curator endpoint."""
    full_url = url.rstrip("/") + endpoint
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        full_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"error": str(e)}
    except Exception as e:
        return 0, {"error": f"connection_failed: {e}"}


def cmd_invite(args: argparse.Namespace) -> int:
    """Generate an invite token (curator admin only)."""
    config = get_config()
    if config.mode != "curator":
        print(f"{RED}[ERROR]{NC} invite command is only available in curator mode.", file=sys.stderr)
        print(f"Current mode: {config.mode}", file=sys.stderr)
        return 1

    invite = generate_token(
        email=args.email,
        role=args.role,
        expires_hours=args.expires,
        single_use=not args.multi_use,
    )

    if args.json:
        print(json.dumps({
            "ok": True,
            "token": invite.token,
            "email": invite.email,
            "role": invite.role,
            "expires_at": invite.expires_at,
            "single_use": invite.single_use,
        }, indent=2))
    else:
        print(f"\n{GREEN}Invite token generated{NC}")
        print(f"  Token:   {invite.token}")
        print(f"  Email:   {invite.email}")
        print(f"  Role:    {invite.role}")
        print(f"  Expires: {invite.expires_at}")
        print(f"\nShare this command with the invitee:")
        print(f"  openclaw-lacp-connect join --token {invite.token}\n")
    return 0


def cmd_join(args: argparse.Namespace) -> int:
    """Connect to a shared vault using an invite token."""
    config = get_config()
    if config.mode == "connected":
        print(f"{YELLOW}[WARN]{NC} Already in connected mode.", file=sys.stderr)
        print(f"Run 'openclaw-lacp-connect disconnect' first to reconnect.", file=sys.stderr)
        return 1

    curator_url = args.curator_url or config.curator_url
    if not curator_url:
        print(f"{RED}[ERROR]{NC} --curator-url required (or set LACP_CURATOR_URL).", file=sys.stderr)
        return 1

    curator_token = args.curator_token or config.curator_token
    if not curator_token:
        print(f"{RED}[ERROR]{NC} --curator-token required (or set LACP_CURATOR_TOKEN).", file=sys.stderr)
        return 1

    # Step 1: Validate invite token with curator
    print(f"{BLUE}[1/5]{NC} Validating invite token...")
    status_code, resp = _post_curator(curator_url, "/validate", {"token": args.token}, curator_token)
    if status_code == 0:
        print(f"{RED}[ERROR]{NC} Could not reach curator at {curator_url}: {resp.get('error', '')}", file=sys.stderr)
        return 1
    if not resp.get("valid"):
        print(f"{RED}[ERROR]{NC} Invalid invite token: {resp.get('reason', 'unknown')}", file=sys.stderr)
        return 1

    vault_name = resp.get("vault_name", "Company Brain")
    role = resp.get("role", "developer")
    print(f"  Vault: {vault_name}, Role: {role}")

    # Step 2: Check ob is available
    print(f"{BLUE}[2/5]{NC} Checking ob (obsidian-headless)...")
    ob_check = subprocess.run(["ob", "--version"], capture_output=True, text=True)
    if ob_check.returncode != 0:
        print(f"{RED}[ERROR]{NC} 'ob' not found. Install: npm install -g obsidian-headless", file=sys.stderr)
        return 1
    print(f"  ob version: {ob_check.stdout.strip()}")

    # Step 3: Configure vault path
    vault_path = os.path.expanduser("~/.openclaw/vault")
    print(f"{BLUE}[3/5]{NC} Configuring shared vault at {vault_path}...")
    Path(vault_path).mkdir(parents=True, exist_ok=True)

    # Step 4: Start sync daemon
    print(f"{BLUE}[4/5]{NC} Starting ob sync daemon...")
    daemon_result = daemon_start(vault_path)
    if not daemon_result.running:
        print(f"{YELLOW}[WARN]{NC} Daemon start returned: {daemon_result.message}", file=sys.stderr)
        print(f"  You may need to run 'ob login' first, then 'openclaw-lacp-connect resume'.", file=sys.stderr)

    # Step 5: Persist mode config
    print(f"{BLUE}[5/5]{NC} Saving configuration...")
    set_mode(
        "connected",
        curator_url=curator_url,
        curator_token=curator_token,
        vault_path=vault_path,
        agent_role=role,
    )

    if args.json:
        print(json.dumps({
            "ok": True,
            "mode": "connected",
            "vault_name": vault_name,
            "vault_path": vault_path,
            "role": role,
            "daemon": daemon_result.to_dict(),
        }, indent=2))
    else:
        print(f"\n{GREEN}Connected to {vault_name}{NC}")
        print(f"  Mode:   connected")
        print(f"  Role:   {role}")
        print(f"  Vault:  {vault_path}")
        print(f"  Daemon: {daemon_result.message}\n")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show connection status."""
    config = get_config()
    daemon = daemon_status()
    hb = check_heartbeat(config.vault_path)

    vault = Path(config.vault_path)
    note_count = 0
    if vault.exists():
        note_count = sum(1 for _ in vault.rglob("*.md") if "/.obsidian/" not in _.as_posix())

    if args.json:
        print(json.dumps({
            "ok": True,
            "mode": config.mode,
            "vault_path": config.vault_path,
            "curator_url": config.curator_url,
            "agent_role": config.agent_role,
            "mutations_enabled": config.mutations_enabled,
            "daemon": daemon.to_dict(),
            "heartbeat": hb,
            "notes": note_count,
        }, indent=2))
    else:
        print(f"openclaw-lacp-connect status")
        print(f"  Mode:       {config.mode}")
        print(f"  Vault:      {config.vault_path}")
        print(f"  Notes:      {note_count}")
        print(f"  Role:       {config.agent_role}")
        print(f"  Mutations:  {'enabled' if config.mutations_enabled else 'disabled (curator-managed)'}")
        print(f"  Curator:    {config.curator_url or 'none'}")
        print(f"  Daemon:     {daemon.message}")
        print(f"  Heartbeat:  {hb.get('message', 'n/a')}")
    return 0


def cmd_disconnect(args: argparse.Namespace) -> int:
    """Disconnect from shared vault."""
    config = get_config()
    if config.mode != "connected":
        print(f"{YELLOW}[WARN]{NC} Not in connected mode (current: {config.mode}).", file=sys.stderr)
        return 1

    print(f"{BLUE}[1/2]{NC} Stopping sync daemon...")
    daemon_stop()

    print(f"{BLUE}[2/2]{NC} Reverting to standalone mode...")
    set_mode("standalone")

    if args.json:
        print(json.dumps({"ok": True, "mode": "standalone"}, indent=2))
    else:
        print(f"\n{GREEN}Disconnected.{NC} Mode reverted to standalone.")
        print(f"  Local vault copy preserved at: {config.vault_path}\n")
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    """Pause sync daemon."""
    result = daemon_stop()
    if args.json:
        print(json.dumps({"ok": True, "action": "pause", "daemon": result.to_dict()}, indent=2))
    else:
        print(f"{GREEN}Sync paused.{NC} {result.message}")
        print(f"  Local vault copy preserved. Run 'openclaw-lacp-connect resume' to restart.")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    """Resume sync daemon."""
    config = get_config()
    result = daemon_start(config.vault_path)
    if args.json:
        print(json.dumps({"ok": True, "action": "resume", "daemon": result.to_dict()}, indent=2))
    else:
        if result.running:
            print(f"{GREEN}Sync resumed.{NC} {result.message}")
        else:
            print(f"{YELLOW}[WARN]{NC} {result.message}")
    return 0


def cmd_set_role(args: argparse.Namespace) -> int:
    """Change agent role."""
    valid_roles = ("developer", "pm", "executive", "readonly")
    if args.role not in valid_roles:
        print(f"{RED}[ERROR]{NC} Invalid role: {args.role}. Must be one of: {', '.join(valid_roles)}", file=sys.stderr)
        return 1

    config = get_config()
    set_mode(config.mode, agent_role=args.role)

    if args.json:
        print(json.dumps({"ok": True, "role": args.role}, indent=2))
    else:
        print(f"{GREEN}Role updated to: {args.role}{NC}")
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    """Detailed health check."""
    config = get_config()
    daemon = daemon_status()
    hb = check_heartbeat(config.vault_path)

    vault = Path(config.vault_path)
    inbox_count = 0
    conflict_count = 0
    if vault.exists():
        inbox_dir = vault / "05_Inbox"
        if inbox_dir.exists():
            inbox_count = sum(1 for _ in inbox_dir.rglob("*.md"))
        conflict_count = sum(1 for _ in vault.rglob("* (conflict *).md"))

    # Try to reach curator health endpoint
    curator_health = {}
    if config.curator_url and config.curator_token:
        _, curator_health = _post_curator(config.curator_url, "/health", {}, config.curator_token)

    health = {
        "ok": True,
        "mode": config.mode,
        "daemon": daemon.to_dict(),
        "heartbeat": hb,
        "local": {
            "inbox_pending": inbox_count,
            "conflict_files": conflict_count,
        },
        "curator_remote": curator_health if curator_health else None,
    }

    if args.json:
        print(json.dumps(health, indent=2))
    else:
        print(f"openclaw-lacp-connect health")
        print(f"  Mode:            {config.mode}")
        print(f"  Daemon:          {daemon.message}")
        print(f"  Heartbeat:       {hb.get('message', 'n/a')}")
        print(f"  Inbox pending:   {inbox_count}")
        print(f"  Conflict files:  {conflict_count}")
        if curator_health:
            print(f"  Curator status:  {curator_health.get('status', 'unknown')}")
            print(f"  Curator notes:   {curator_health.get('notes', 'n/a')}")
    return 0


def cmd_members(args: argparse.Namespace) -> int:
    """List invite tokens / members (curator admin only)."""
    config = get_config()
    if config.mode != "curator":
        print(f"{RED}[ERROR]{NC} members command is only available in curator mode.", file=sys.stderr)
        return 1

    tokens = list_tokens(include_expired=args.all)
    if args.json:
        print(json.dumps({
            "ok": True,
            "members": [
                {
                    "email": t.email,
                    "role": t.role,
                    "redeemed": t.redeemed,
                    "redeemed_by": t.redeemed_by,
                    "revoked": t.revoked,
                    "expires_at": t.expires_at,
                }
                for t in tokens
            ],
        }, indent=2))
    else:
        if not tokens:
            print("No active invite tokens.")
            return 0
        print(f"{'Email':<30} {'Role':<12} {'Status':<15} {'Expires'}")
        print("-" * 80)
        for t in tokens:
            if t.revoked:
                status = "revoked"
            elif t.redeemed:
                status = f"joined ({t.redeemed_by or '?'})"
            else:
                status = "pending"
            print(f"{t.email:<30} {t.role:<12} {status:<15} {t.expires_at[:19]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="openclaw-lacp-connect",
        description="Manage connection between agent nodes and the curator",
    )
    p.add_argument("--json", action="store_true", help="Output as JSON")
    sub = p.add_subparsers(dest="command", required=True)

    # invite
    inv = sub.add_parser("invite", help="Generate an invite token (curator only)")
    inv.add_argument("--email", required=True, help="Invitee email")
    inv.add_argument("--role", default="developer", help="Role: developer, pm, executive, readonly")
    inv.add_argument("--expires", type=int, default=72, help="Expiration in hours (default: 72)")
    inv.add_argument("--multi-use", action="store_true", help="Allow multiple redemptions")

    # join
    j = sub.add_parser("join", help="Connect to a shared vault")
    j.add_argument("--token", required=True, help="Invite token")
    j.add_argument("--curator-url", default="", help="Curator URL (or LACP_CURATOR_URL)")
    j.add_argument("--curator-token", default="", help="Curator auth token (or LACP_CURATOR_TOKEN)")

    # status
    sub.add_parser("status", help="Show connection status")

    # disconnect
    sub.add_parser("disconnect", help="Disconnect from shared vault")

    # pause
    sub.add_parser("pause", help="Pause sync daemon")

    # resume
    sub.add_parser("resume", help="Resume sync daemon")

    # set-role
    sr = sub.add_parser("set-role", help="Change agent role")
    sr.add_argument("--role", required=True, help="New role")

    # health
    sub.add_parser("health", help="Detailed health check")

    # members
    m = sub.add_parser("members", help="List members (curator only)")
    m.add_argument("--all", action="store_true", help="Include expired tokens")

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Propagate --json to subcommands
    if not hasattr(args, "json") or args.json is None:
        args.json = False

    dispatch = {
        "invite": cmd_invite,
        "join": cmd_join,
        "status": cmd_status,
        "disconnect": cmd_disconnect,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "set-role": cmd_set_role,
        "health": cmd_health,
        "members": cmd_members,
    }

    handler = dispatch.get(args.command)
    if handler:
        return handler(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

### Step 7.2: Make executable

- [ ] Make the script executable

```bash
chmod +x /Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-lacp-connect
```

### Step 7.3: Write tests for openclaw-lacp-connect

- [ ] Write test file `plugin/bin/tests/test_lacp_connect.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/tests/test_lacp_connect.py`

```python
"""Tests for openclaw-lacp-connect CLI."""

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = str(Path(__file__).resolve().parent.parent / "openclaw-lacp-connect")


class TestConnectHelp:
    def test_help_exits_zero(self):
        result = subprocess.run(
            ["python3", SCRIPT, "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "openclaw-lacp-connect" in result.stdout
        assert "invite" in result.stdout
        assert "join" in result.stdout
        assert "status" in result.stdout


class TestConnectStatus:
    def test_status_standalone(self, tmp_path):
        env = os.environ.copy()
        env["LACP_MODE"] = "standalone"
        env["OPENCLAW_HOME"] = str(tmp_path)
        result = subprocess.run(
            ["python3", SCRIPT, "--json", "status"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["mode"] == "standalone"


class TestConnectInvite:
    def test_invite_requires_curator_mode(self, tmp_path):
        env = os.environ.copy()
        env["LACP_MODE"] = "standalone"
        env["OPENCLAW_HOME"] = str(tmp_path)
        result = subprocess.run(
            ["python3", SCRIPT, "--json", "invite", "--email", "dev@test.com"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 1

    def test_invite_in_curator_mode(self, tmp_path):
        env = os.environ.copy()
        env["LACP_MODE"] = "curator"
        env["OPENCLAW_HOME"] = str(tmp_path)
        result = subprocess.run(
            ["python3", SCRIPT, "--json", "invite", "--email", "dev@test.com", "--role", "developer"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["token"].startswith("inv_")
        assert payload["role"] == "developer"


class TestConnectSetRole:
    def test_set_role(self, tmp_path):
        env = os.environ.copy()
        env["OPENCLAW_HOME"] = str(tmp_path)
        env["LACP_MODE"] = "connected"
        result = subprocess.run(
            ["python3", SCRIPT, "--json", "set-role", "--role", "pm"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["role"] == "pm"

    def test_set_role_invalid(self, tmp_path):
        env = os.environ.copy()
        env["OPENCLAW_HOME"] = str(tmp_path)
        env["LACP_MODE"] = "connected"
        result = subprocess.run(
            ["python3", SCRIPT, "--json", "set-role", "--role", "admin"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 1


class TestConnectDisconnect:
    def test_disconnect_not_connected(self, tmp_path):
        env = os.environ.copy()
        env["LACP_MODE"] = "standalone"
        env["OPENCLAW_HOME"] = str(tmp_path)
        result = subprocess.run(
            ["python3", SCRIPT, "--json", "disconnect"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 1


class TestConnectMembers:
    def test_members_requires_curator(self, tmp_path):
        env = os.environ.copy()
        env["LACP_MODE"] = "standalone"
        env["OPENCLAW_HOME"] = str(tmp_path)
        result = subprocess.run(
            ["python3", SCRIPT, "--json", "members"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 1

    def test_members_in_curator_mode(self, tmp_path):
        env = os.environ.copy()
        env["LACP_MODE"] = "curator"
        env["OPENCLAW_HOME"] = str(tmp_path)
        result = subprocess.run(
            ["python3", SCRIPT, "--json", "members"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
```

### Step 7.4: Run tests and verify

- [ ] Run connect CLI tests

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/bin/tests/test_lacp_connect.py -v
```

**Expected output:** All 8 tests pass.

### Step 7.5: Commit

- [ ] Commit openclaw-lacp-connect CLI

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo
git add plugin/bin/openclaw-lacp-connect plugin/bin/tests/test_lacp_connect.py
git commit -m "$(cat <<'EOF'
feat: add openclaw-lacp-connect CLI for shared vault management

Full CLI with subcommands: invite, join, status, disconnect, pause, resume,
set-role, health, members. Handles invite token validation via curator HTTP
surface, ob sync daemon lifecycle, and mode configuration persistence.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Create lib directory for bin helpers

Ensure the `plugin/bin/lib/` directory exists with an `__init__.py` and that all helper modules are properly organized.

### Step 8.1: Create plugin/bin/lib/__init__.py

- [ ] Create `plugin/bin/lib/__init__.py`

```bash
mkdir -p /Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/lib
touch /Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/lib/__init__.py
```

### Step 8.2: Commit

- [ ] Commit bin lib directory

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo
git add plugin/bin/lib/__init__.py
git commit -m "$(cat <<'EOF'
chore: add plugin/bin/lib/ package for shared CLI helpers

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Integration test for full join flow

Write an integration test that validates the end-to-end join flow: curator generates invite, connected node validates it via HTTP, mode switches to connected, mutation commands are blocked.

### Step 9.1: Write integration test

- [ ] Write test file `plugin/bin/tests/test_integration_join_flow.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/tests/test_integration_join_flow.py`

```python
"""Integration test: full join flow from curator invite to connected mode blocking."""

import json
import os
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "lib"))

from curator_http import create_server
from invites import generate_token
from mode import set_mode, get_mode

BIN_DIR = Path(__file__).resolve().parent.parent
CONNECT_SCRIPT = str(BIN_DIR / "openclaw-lacp-connect")
BRAIN_RESOLVE = str(BIN_DIR / "openclaw-brain-resolve")

ADMIN_TOKEN = "integration_test_token_xyz"


@pytest.fixture()
def curator_env(tmp_path, monkeypatch):
    """Set up a curator environment with HTTP server."""
    monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
    monkeypatch.setenv("LACP_MODE", "curator")

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "test.md").write_text("---\ntitle: test\n---\n# Test\n")

    port = 19877
    server = create_server(
        port=port,
        admin_token=ADMIN_TOKEN,
        vault_path=str(vault),
        vault_name="Integration Test Brain",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield {
        "home": tmp_path,
        "vault": vault,
        "port": port,
        "url": f"http://localhost:{port}",
    }
    server.shutdown()


class TestFullJoinFlow:
    def test_invite_validate_block(self, curator_env):
        """Test: curator invites -> token validates -> connected mode blocks mutations."""
        home = curator_env["home"]
        env = os.environ.copy()
        env["OPENCLAW_HOME"] = str(home)
        env["LACP_MODE"] = "curator"

        # Step 1: Generate invite via CLI
        result = subprocess.run(
            [
                "python3", CONNECT_SCRIPT, "--json",
                "invite", "--email", "agent@test.com", "--role", "developer",
            ],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0, f"invite failed: {result.stderr}"
        invite_data = json.loads(result.stdout)
        token = invite_data["token"]
        assert token.startswith("inv_")

        # Step 2: Validate token via HTTP (simulating what join does)
        body = json.dumps({"token": token}).encode()
        req = urllib.request.Request(
            f"{curator_env['url']}/validate",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {ADMIN_TOKEN}",
            },
            method="POST",
        )
        resp = urllib.request.urlopen(req)
        validate_data = json.loads(resp.read())
        assert validate_data["valid"] is True
        assert validate_data["vault_name"] == "Integration Test Brain"
        assert validate_data["role"] == "developer"

        # Step 3: Switch to connected mode (simulating post-join state)
        env["LACP_MODE"] = "connected"
        set_mode(
            "connected",
            curator_url=curator_env["url"],
            curator_token=ADMIN_TOKEN,
        )

        # Step 4: Verify mutation commands are blocked
        result = subprocess.run(
            [
                "python3", BRAIN_RESOLVE,
                "--id", "test",
                "--resolution", "validated",
                "--reason", "test",
                "--vault", str(curator_env["vault"]),
                "--json",
            ],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 10, f"Expected exit 10, got {result.returncode}: {result.stdout} {result.stderr}"
        blocked_data = json.loads(result.stdout)
        assert blocked_data["ok"] is False
        assert blocked_data["error"] == "mode_blocked"

        # Step 5: Verify status shows connected
        result = subprocess.run(
            ["python3", CONNECT_SCRIPT, "--json", "status"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0
        status_data = json.loads(result.stdout)
        assert status_data["mode"] == "connected"
```

### Step 9.2: Run integration test

- [ ] Run integration test

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/bin/tests/test_integration_join_flow.py -v
```

**Expected output:** 1 test passes.

### Step 9.3: Commit

- [ ] Commit integration test

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo
git add plugin/bin/tests/test_integration_join_flow.py
git commit -m "$(cat <<'EOF'
test: add integration test for full join flow

End-to-end test: curator generates invite, token validates via HTTP,
mode switches to connected, mutation commands are blocked with exit 10.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Run full test suite and verify

Run all tests from this plan together to ensure nothing conflicts.

### Step 10.1: Run all tests

- [ ] Run the complete test suite for shared vault infrastructure

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest \
  plugin/lib/tests/test_mode.py \
  plugin/lib/tests/test_invites.py \
  plugin/lib/tests/test_heartbeat.py \
  plugin/lib/tests/test_sync_daemon.py \
  plugin/lib/tests/test_curator_http.py \
  plugin/bin/tests/test_mode_guards.py \
  plugin/bin/tests/test_lacp_connect.py \
  plugin/bin/tests/test_integration_join_flow.py \
  -v --tb=short
```

**Expected output:** All tests pass (approximately 62 tests across 8 test files).

### Step 10.2: Verify no regressions in existing tests

- [ ] Run the full existing test suite

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/ -v --tb=short 2>&1 | tail -30
```

**Expected output:** All existing tests continue to pass alongside the new tests.
