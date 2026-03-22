# Connector Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the connector framework (Phase 4 of the Shared Intelligence Graph spec) that ingests knowledge from external sources into the vault. Connectors run exclusively on the curator server. Each connector transforms external data into VaultNote objects that land in `05_Inbox/queue-*/` folders.

**Architecture:** A base Connector class defines the interface. A registry loads connectors from `config/connectors.json`, manages lifecycle, and discovers community connectors. Trust verification operates at two layers (connector trust level + sender allowlist). Three native connectors (filesystem, webhook, cron-fetch), three first-party connectors (GitHub, Slack, email), a CLI tool, and community packaging round out the framework.

**Tech Stack:** Python 3.9+, asyncio (for webhook server), watchdog (filesystem events), hmac/hashlib (HMAC verification), imaplib (email), json, argparse

**Spec reference:** `docs/superpowers/specs/2026-03-21-shared-intelligence-graph-design.md` sections 2.3, 2.4

---

## Task 1: Connector base class and VaultNote dataclass

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/base.py`

**What:** Define the abstract Connector base class and VaultNote dataclass. Every connector inherits from this. VaultNote is the universal output format -- a structured note with frontmatter that lands in an inbox queue folder.

### Step 1.1: Create the connectors package

- [ ] Create `plugin/lib/connectors/__init__.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/__init__.py`

```python
"""Connector framework for ingesting external knowledge into the vault."""

from .base import Connector, VaultNote, ConnectorStatus

__all__ = ["Connector", "VaultNote", "ConnectorStatus"]
```

### Step 1.2: Write the base module

- [ ] Write `plugin/lib/connectors/base.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/base.py`

```python
"""Base connector class and VaultNote dataclass."""

from __future__ import annotations

import hashlib
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class TrustLevel(str, Enum):
    VERIFIED = "verified"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ConnectorMode(str, Enum):
    PULL = "pull"
    PUSH = "push"
    BOTH = "both"


@dataclass
class ConnectorStatus:
    """Health status returned by health_check()."""

    healthy: bool
    connector_id: str
    connector_type: str
    last_pull_time: Optional[str] = None
    last_error: Optional[str] = None
    error_count: int = 0
    notes_ingested: int = 0
    uptime_seconds: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "healthy": self.healthy,
            "connector_id": self.connector_id,
            "connector_type": self.connector_type,
            "last_pull_time": self.last_pull_time,
            "last_error": self.last_error,
            "error_count": self.error_count,
            "notes_ingested": self.notes_ingested,
            "uptime_seconds": self.uptime_seconds,
        }
        d.update(self.extra)
        return d


@dataclass
class VaultNote:
    """
    Universal output format for connectors.

    Every connector transforms external data into one or more VaultNote
    objects. The registry writes these to the appropriate inbox queue folder
    as Markdown files with YAML frontmatter.
    """

    title: str
    body: str
    source_connector: str       # connector id that produced this note
    source_type: str            # connector type (github, slack, etc.)
    source_id: str              # unique id from the source (PR number, message ts, etc.)
    trust_level: str = "medium"
    landing_zone: str = "queue-human"  # subfolder under 05_Inbox/

    # Frontmatter fields
    category: str = ""
    tags: list[str] = field(default_factory=list)
    author: str = ""
    source_url: str = ""
    created: str = ""
    status: str = "active"
    extra_frontmatter: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.created:
            self.created = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Low trust always gets unverified status
        if self.trust_level == TrustLevel.LOW.value:
            self.status = "unverified"

    @property
    def slug(self) -> str:
        """Generate a filesystem-safe slug for the note filename."""
        raw = f"{self.source_connector}_{self.source_id}"
        h = hashlib.md5(raw.encode()).hexdigest()[:8]
        safe_title = "".join(
            c if c.isalnum() or c in "-_ " else "" for c in self.title
        )[:60].strip().replace(" ", "-").lower()
        return f"{safe_title}-{h}" if safe_title else h

    def to_markdown(self) -> str:
        """Render the note as Markdown with YAML frontmatter."""
        fm: dict[str, Any] = {
            "title": self.title,
            "created": self.created,
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "author": self.author or self.source_connector,
            "source": self.source_type,
            "source_connector": self.source_connector,
            "source_id": self.source_id,
            "trust_level": self.trust_level,
            "status": self.status,
        }
        if self.category:
            fm["category"] = self.category
        if self.tags:
            fm["tags"] = self.tags
        if self.source_url:
            fm["source_url"] = self.source_url
        fm.update(self.extra_frontmatter)

        # Render YAML frontmatter manually (avoid PyYAML dependency)
        lines = ["---"]
        for k, v in fm.items():
            if isinstance(v, list):
                lines.append(f"{k}:")
                for item in v:
                    lines.append(f"  - {item}")
            elif isinstance(v, bool):
                lines.append(f"{k}: {'true' if v else 'false'}")
            elif isinstance(v, (int, float)):
                lines.append(f"{k}: {v}")
            else:
                lines.append(f"{k}: {v}")
        lines.append("---")
        lines.append("")
        lines.append(f"# {self.title}")
        lines.append("")
        lines.append(self.body)
        lines.append("")
        lines.append("---")
        lines.append(f"Ingested by connector: {self.source_connector}")
        lines.append("")
        return "\n".join(lines)

    def write_to_vault(self, vault_path: str | Path) -> Path:
        """Write this note to the appropriate inbox queue folder."""
        vault = Path(vault_path)
        queue_dir = vault / "05_Inbox" / self.landing_zone
        queue_dir.mkdir(parents=True, exist_ok=True)
        out = queue_dir / f"{self.slug}.md"
        # Handle collision
        if out.exists():
            ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            out = queue_dir / f"{self.slug}-{ts}.md"
        out.write_text(self.to_markdown(), encoding="utf-8")
        return out


@dataclass
class RawData:
    """
    Raw data from an external source, before transformation.

    Connectors produce RawData from pull() or receive(), then
    transform() converts it to a VaultNote.
    """

    source_id: str
    payload: dict[str, Any]
    timestamp: str = ""
    sender: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class Connector(ABC):
    """
    Abstract base class for all connectors.

    Subclasses must implement authenticate(), transform(), and health_check().
    Pull-mode connectors must implement pull().
    Push-mode connectors must implement receive().
    Both-mode connectors must implement both.
    """

    id: str = ""
    type: str = ""
    trust_level: str = TrustLevel.MEDIUM.value
    mode: str = ConnectorMode.PULL.value
    landing_zone: str = "queue-human"

    def __init__(self, config: dict[str, Any]):
        """
        Initialize from a connector config entry (from connectors.json).

        Args:
            config: The full connector config dict including id, type,
                    trust_level, mode, landing_zone, and connector-specific
                    config under the "config" key.
        """
        self.id = config.get("id", self.id)
        self.type = config.get("type", self.type)
        self.trust_level = config.get("trust_level", self.trust_level)
        self.mode = config.get("mode", self.mode)
        self.landing_zone = config.get("landing_zone", self.landing_zone)
        self.connector_config = config.get("config", {})

        # Runtime state
        self._started_at: Optional[str] = None
        self._error_count: int = 0
        self._last_error: Optional[str] = None
        self._last_pull_time: Optional[str] = None
        self._notes_ingested: int = 0

        # Resolve env var references in config values
        self.connector_config = self._resolve_env_vars(self.connector_config)

    @staticmethod
    def _resolve_env_vars(config: dict[str, Any]) -> dict[str, Any]:
        """Replace ${ENV_VAR} references with actual environment values."""
        resolved = {}
        for k, v in config.items():
            if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                env_key = v[2:-1]
                resolved[k] = os.environ.get(env_key, "")
            elif isinstance(v, dict):
                resolved[k] = Connector._resolve_env_vars(v)
            elif isinstance(v, list):
                resolved[k] = [
                    os.environ.get(item[2:-1], "")
                    if isinstance(item, str) and item.startswith("${") and item.endswith("}")
                    else item
                    for item in v
                ]
            else:
                resolved[k] = v
        return resolved

    @abstractmethod
    def authenticate(self) -> bool:
        """
        Establish connection to the external source.

        Returns True if authentication succeeds, False otherwise.
        Called once during connector startup.
        """
        ...

    def pull(self) -> list[RawData]:
        """
        Fetch new data from source (for pull/both mode connectors).

        Returns a list of RawData objects representing new items since
        the last pull. Override in pull-mode connectors.
        """
        raise NotImplementedError(
            f"Connector {self.id} is mode={self.mode} but pull() not implemented"
        )

    def receive(self, payload: dict[str, Any]) -> RawData:
        """
        Handle incoming webhook/push payload (for push/both mode connectors).

        Returns a single RawData object. Override in push-mode connectors.
        """
        raise NotImplementedError(
            f"Connector {self.id} is mode={self.mode} but receive() not implemented"
        )

    @abstractmethod
    def transform(self, raw_data: RawData) -> VaultNote:
        """
        Convert raw external data into a VaultNote.

        This is where connector-specific formatting happens. Every
        connector must implement this.
        """
        ...

    @abstractmethod
    def health_check(self) -> ConnectorStatus:
        """
        Return connector status including health, last pull time, error count.

        Every connector must implement this.
        """
        ...

    def record_pull(self):
        """Record a successful pull timestamp."""
        self._last_pull_time = datetime.now(timezone.utc).isoformat()

    def record_error(self, error: str):
        """Record an error."""
        self._error_count += 1
        self._last_error = error

    def record_ingestion(self, count: int = 1):
        """Record notes ingested."""
        self._notes_ingested += count

    def base_status(self, healthy: bool) -> ConnectorStatus:
        """Build a ConnectorStatus with common fields pre-filled."""
        uptime = 0.0
        if self._started_at:
            started = datetime.fromisoformat(self._started_at)
            uptime = (datetime.now(timezone.utc) - started).total_seconds()
        return ConnectorStatus(
            healthy=healthy,
            connector_id=self.id,
            connector_type=self.type,
            last_pull_time=self._last_pull_time,
            last_error=self._last_error,
            error_count=self._error_count,
            notes_ingested=self._notes_ingested,
            uptime_seconds=uptime,
        )

    def start(self):
        """Mark connector as started."""
        self._started_at = datetime.now(timezone.utc).isoformat()
```

### Step 1.3: Write tests for base module

- [ ] Write `plugin/lib/connectors/tests/test_base.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/tests/test_base.py`

```python
"""Tests for connector base class and VaultNote."""

import os
import json
import tempfile
from pathlib import Path

import pytest

# Allow import from parent
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from lib.connectors.base import (
    Connector,
    ConnectorStatus,
    RawData,
    VaultNote,
    TrustLevel,
    ConnectorMode,
)


class StubConnector(Connector):
    """Minimal concrete connector for testing."""

    type = "stub"

    def authenticate(self) -> bool:
        return True

    def transform(self, raw_data: RawData) -> VaultNote:
        return VaultNote(
            title=raw_data.payload.get("title", "Stub"),
            body=raw_data.payload.get("body", ""),
            source_connector=self.id,
            source_type=self.type,
            source_id=raw_data.source_id,
            trust_level=self.trust_level,
            landing_zone=self.landing_zone,
        )

    def health_check(self) -> ConnectorStatus:
        return self.base_status(healthy=True)


class TestVaultNote:
    def test_slug_generation(self):
        note = VaultNote(
            title="My Test Note",
            body="content",
            source_connector="test-conn",
            source_type="stub",
            source_id="abc-123",
        )
        assert "my-test-note" in note.slug
        assert len(note.slug) > 10

    def test_slug_uniqueness(self):
        note_a = VaultNote(
            title="Same Title", body="", source_connector="conn-a",
            source_type="stub", source_id="id-1",
        )
        note_b = VaultNote(
            title="Same Title", body="", source_connector="conn-b",
            source_type="stub", source_id="id-2",
        )
        assert note_a.slug != note_b.slug

    def test_to_markdown_has_frontmatter(self):
        note = VaultNote(
            title="PR Merged",
            body="Pull request #42 was merged.",
            source_connector="github-test",
            source_type="github",
            source_id="pr-42",
            tags=["cicd", "github"],
            trust_level="verified",
        )
        md = note.to_markdown()
        assert md.startswith("---\n")
        assert "title: PR Merged" in md
        assert "trust_level: verified" in md
        assert "tags:" in md
        assert "  - cicd" in md
        assert "# PR Merged" in md
        assert "Pull request #42 was merged." in md

    def test_low_trust_sets_unverified(self):
        note = VaultNote(
            title="Unknown", body="", source_connector="x",
            source_type="webhook", source_id="1",
            trust_level="low",
        )
        assert note.status == "unverified"

    def test_write_to_vault(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            note = VaultNote(
                title="Test Write",
                body="body content",
                source_connector="test",
                source_type="stub",
                source_id="w-1",
                landing_zone="queue-cicd",
            )
            path = note.write_to_vault(tmpdir)
            assert path.exists()
            assert "05_Inbox/queue-cicd" in str(path)
            content = path.read_text()
            assert "Test Write" in content

    def test_write_handles_collision(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            note = VaultNote(
                title="Collision", body="v1", source_connector="c",
                source_type="stub", source_id="same-id",
            )
            path1 = note.write_to_vault(tmpdir)
            # Write again -- should not overwrite
            note2 = VaultNote(
                title="Collision", body="v2", source_connector="c",
                source_type="stub", source_id="same-id",
            )
            path2 = note2.write_to_vault(tmpdir)
            assert path1 != path2
            assert path1.exists()
            assert path2.exists()


class TestConnectorBase:
    def test_init_from_config(self):
        cfg = {
            "id": "test-stub",
            "type": "stub",
            "trust_level": "high",
            "mode": "pull",
            "landing_zone": "queue-agent",
            "config": {"key": "value"},
        }
        conn = StubConnector(cfg)
        assert conn.id == "test-stub"
        assert conn.trust_level == "high"
        assert conn.mode == "pull"
        assert conn.connector_config["key"] == "value"

    def test_env_var_resolution(self, monkeypatch):
        monkeypatch.setenv("MY_SECRET", "s3cret")
        cfg = {
            "id": "env-test",
            "type": "stub",
            "config": {"token": "${MY_SECRET}", "plain": "hello"},
        }
        conn = StubConnector(cfg)
        assert conn.connector_config["token"] == "s3cret"
        assert conn.connector_config["plain"] == "hello"

    def test_env_var_missing_resolves_empty(self, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        cfg = {
            "id": "env-miss",
            "type": "stub",
            "config": {"token": "${NONEXISTENT_VAR}"},
        }
        conn = StubConnector(cfg)
        assert conn.connector_config["token"] == ""

    def test_authenticate(self):
        conn = StubConnector({"id": "auth-test", "type": "stub", "config": {}})
        assert conn.authenticate() is True

    def test_transform(self):
        conn = StubConnector({"id": "tx-test", "type": "stub", "config": {}})
        raw = RawData(source_id="r1", payload={"title": "Hello", "body": "World"})
        note = conn.transform(raw)
        assert note.title == "Hello"
        assert note.source_connector == "tx-test"

    def test_health_check(self):
        conn = StubConnector({"id": "hc-test", "type": "stub", "config": {}})
        conn.start()
        status = conn.health_check()
        assert status.healthy is True
        assert status.connector_id == "hc-test"

    def test_pull_not_implemented_on_push(self):
        conn = StubConnector({"id": "push-test", "type": "stub", "mode": "push", "config": {}})
        with pytest.raises(NotImplementedError):
            conn.pull()

    def test_error_tracking(self):
        conn = StubConnector({"id": "err-test", "type": "stub", "config": {}})
        conn.record_error("timeout")
        conn.record_error("refused")
        status = conn.health_check()
        assert status.error_count == 2
        assert status.last_error == "refused"


class TestRawData:
    def test_auto_timestamp(self):
        raw = RawData(source_id="x", payload={})
        assert raw.timestamp  # should be auto-filled
        assert "T" in raw.timestamp  # ISO format
```

- [ ] Create `plugin/lib/connectors/tests/__init__.py` (empty)

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/tests/__init__.py`

```python
```

**Test:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/lib/connectors/tests/test_base.py -v
```

**Commit:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && git add plugin/lib/connectors/ && git commit -m "$(cat <<'EOF'
feat: add connector base class, VaultNote dataclass, and RawData

Defines the abstract Connector interface (authenticate, pull, receive,
transform, health_check), VaultNote output format with frontmatter and
write_to_vault, RawData intermediate, trust levels, and env var resolution.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Trust and sender verification

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/trust.py`

**What:** Implement the two-layer trust model from spec section 2.4. Layer 1: connector-level trust determines how notes are handled by the curator. Layer 2: per-connector sender policies (allowlist, domain, open) gate whether incoming data is accepted at all.

### Step 2.1: Write the trust module

- [ ] Write `plugin/lib/connectors/trust.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/trust.py`

```python
"""
Two-layer trust and sender verification for connectors.

Layer 1: Connector trust level (verified, high, medium, low)
         Determines how the curator handles ingested notes.

Layer 2: Sender allowlist per connector
         Determines whether incoming data is accepted at all.

Policies:
  - allowlist: Only messages from listed senders accepted. Others dropped.
  - domain:    Accept from any sender matching the domain (e.g. @easylabs.io).
  - open:      Accept from anyone. Lowest trust, always tagged unverified.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class SenderPolicy(str, Enum):
    ALLOWLIST = "allowlist"
    DOMAIN = "domain"
    OPEN = "open"


class TrustDecision(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"


@dataclass
class SenderVerdict:
    """Result of sender verification."""

    decision: TrustDecision
    sender: str
    policy: str
    trust_override: Optional[str] = None
    landing_zone_override: Optional[str] = None
    reason: str = ""


@dataclass
class SenderEntry:
    """
    A single entry in a sender allowlist.

    Supports exact match, wildcard prefix (*@domain.com), and optional
    trust/landing_zone overrides per sender.
    """

    address: str
    trust_override: Optional[str] = None
    landing_zone_override: Optional[str] = None

    @classmethod
    def from_config(cls, entry: str | dict[str, Any]) -> "SenderEntry":
        """Parse from config -- supports both string and dict formats."""
        if isinstance(entry, str):
            return cls(address=entry)
        return cls(
            address=entry.get("address", ""),
            trust_override=entry.get("trust_override"),
            landing_zone_override=entry.get("landing_zone_override"),
        )

    def matches(self, sender: str) -> bool:
        """Check if sender matches this entry. Supports * wildcard."""
        sender_lower = sender.lower().strip()
        pattern_lower = self.address.lower().strip()

        if pattern_lower == sender_lower:
            return True

        # Wildcard: *@domain.com matches any user at that domain
        if pattern_lower.startswith("*@"):
            domain = pattern_lower[1:]  # "@domain.com"
            return sender_lower.endswith(domain)

        return False


class TrustVerifier:
    """
    Verifies senders against connector-specific policies.

    Usage:
        verifier = TrustVerifier.from_connector_config(connector_config)
        verdict = verifier.check_sender("user@example.com")
        if verdict.decision == TrustDecision.REJECT:
            # drop the message
    """

    def __init__(
        self,
        policy: SenderPolicy,
        entries: list[SenderEntry],
        domains: list[str] | None = None,
        ip_allowlist: list[str] | None = None,
    ):
        self.policy = policy
        self.entries = entries
        self.domains = [d.lower().strip() for d in (domains or [])]
        self.ip_allowlist = ip_allowlist or []

    @classmethod
    def from_connector_config(cls, config: dict[str, Any]) -> "TrustVerifier":
        """
        Build a TrustVerifier from a connector's config dict.

        Expects optional keys:
          - sender_policy: "allowlist" | "domain" | "open"
          - sender_allowlist: list of strings or dicts
          - sender_domains: list of domain strings
          - ip_allowlist: list of IP/CIDR strings
        """
        policy_str = config.get("sender_policy", "open")
        try:
            policy = SenderPolicy(policy_str)
        except ValueError:
            policy = SenderPolicy.OPEN

        raw_entries = config.get("sender_allowlist", [])
        entries = [SenderEntry.from_config(e) for e in raw_entries]

        domains = config.get("sender_domains", [])
        ip_allowlist = config.get("ip_allowlist", [])

        return cls(
            policy=policy,
            entries=entries,
            domains=domains,
            ip_allowlist=ip_allowlist,
        )

    def check_sender(self, sender: str) -> SenderVerdict:
        """
        Verify a sender against the configured policy.

        Returns a SenderVerdict with accept/reject decision and any overrides.
        """
        if not sender:
            if self.policy == SenderPolicy.OPEN:
                return SenderVerdict(
                    decision=TrustDecision.ACCEPT,
                    sender="",
                    policy=self.policy.value,
                    reason="open policy accepts all",
                )
            return SenderVerdict(
                decision=TrustDecision.REJECT,
                sender="",
                policy=self.policy.value,
                reason="empty sender rejected by non-open policy",
            )

        if self.policy == SenderPolicy.ALLOWLIST:
            return self._check_allowlist(sender)
        elif self.policy == SenderPolicy.DOMAIN:
            return self._check_domain(sender)
        else:  # OPEN
            return SenderVerdict(
                decision=TrustDecision.ACCEPT,
                sender=sender,
                policy=self.policy.value,
                reason="open policy accepts all",
            )

    def _check_allowlist(self, sender: str) -> SenderVerdict:
        """Check sender against explicit allowlist."""
        for entry in self.entries:
            if entry.matches(sender):
                return SenderVerdict(
                    decision=TrustDecision.ACCEPT,
                    sender=sender,
                    policy=self.policy.value,
                    trust_override=entry.trust_override,
                    landing_zone_override=entry.landing_zone_override,
                    reason=f"matched allowlist entry: {entry.address}",
                )
        return SenderVerdict(
            decision=TrustDecision.REJECT,
            sender=sender,
            policy=self.policy.value,
            reason="sender not in allowlist",
        )

    def _check_domain(self, sender: str) -> SenderVerdict:
        """Check sender against allowed domains."""
        sender_lower = sender.lower().strip()
        for domain in self.domains:
            normalized = domain if domain.startswith("@") else f"@{domain}"
            if sender_lower.endswith(normalized):
                return SenderVerdict(
                    decision=TrustDecision.ACCEPT,
                    sender=sender,
                    policy=self.policy.value,
                    reason=f"matched domain: {domain}",
                )
        # Also check entries (allowlist entries work as fallback in domain mode)
        for entry in self.entries:
            if entry.matches(sender):
                return SenderVerdict(
                    decision=TrustDecision.ACCEPT,
                    sender=sender,
                    policy=self.policy.value,
                    trust_override=entry.trust_override,
                    landing_zone_override=entry.landing_zone_override,
                    reason=f"matched allowlist entry: {entry.address}",
                )
        return SenderVerdict(
            decision=TrustDecision.REJECT,
            sender=sender,
            policy=self.policy.value,
            reason=f"sender domain not in allowed list: {self.domains}",
        )

    def check_ip(self, ip_str: str) -> bool:
        """
        Verify an IP address against the IP allowlist.

        Returns True if allowed (or if no IP allowlist is configured).
        Supports individual IPs and CIDR ranges.
        """
        if not self.ip_allowlist:
            return True  # no restriction
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        for entry in self.ip_allowlist:
            try:
                if "/" in entry:
                    network = ipaddress.ip_network(entry, strict=False)
                    if addr in network:
                        return True
                else:
                    if addr == ipaddress.ip_address(entry):
                        return True
            except ValueError:
                continue
        return False


def verify_hmac_signature(
    payload_body: bytes,
    signature_header: str,
    secret: str,
    algorithm: str = "sha256",
    prefix: str = "",
) -> bool:
    """
    Verify an HMAC signature from a webhook payload.

    Args:
        payload_body: Raw request body bytes.
        signature_header: Value of the signature header from the request.
        secret: The shared HMAC secret.
        algorithm: Hash algorithm (sha256, sha1).
        prefix: Optional prefix to strip from signature (e.g. "sha256=").

    Returns:
        True if signature is valid.
    """
    if not signature_header or not secret:
        return False

    sig = signature_header
    if prefix and sig.startswith(prefix):
        sig = sig[len(prefix):]

    hash_func = getattr(hashlib, algorithm, None)
    if hash_func is None:
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        payload_body,
        hash_func,
    ).hexdigest()

    return hmac.compare_digest(sig.lower(), expected.lower())
```

### Step 2.2: Write tests for trust module

- [ ] Write `plugin/lib/connectors/tests/test_trust.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/tests/test_trust.py`

```python
"""Tests for trust and sender verification."""

import hashlib
import hmac as hmac_mod

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from lib.connectors.trust import (
    SenderEntry,
    SenderPolicy,
    SenderVerdict,
    TrustDecision,
    TrustVerifier,
    verify_hmac_signature,
)


class TestSenderEntry:
    def test_exact_match(self):
        e = SenderEntry(address="andrew@easylabs.io")
        assert e.matches("andrew@easylabs.io") is True
        assert e.matches("niko@easylabs.io") is False

    def test_case_insensitive(self):
        e = SenderEntry(address="Andrew@EasyLabs.io")
        assert e.matches("andrew@easylabs.io") is True

    def test_wildcard_domain(self):
        e = SenderEntry(address="*@easylabs.io")
        assert e.matches("andrew@easylabs.io") is True
        assert e.matches("niko@easylabs.io") is True
        assert e.matches("hacker@evil.com") is False

    def test_from_config_string(self):
        e = SenderEntry.from_config("test@example.com")
        assert e.address == "test@example.com"
        assert e.trust_override is None

    def test_from_config_dict(self):
        e = SenderEntry.from_config({
            "address": "boss@co.com",
            "trust_override": "high",
            "landing_zone_override": "queue-agent",
        })
        assert e.address == "boss@co.com"
        assert e.trust_override == "high"
        assert e.landing_zone_override == "queue-agent"


class TestTrustVerifierAllowlist:
    def test_accept_listed_sender(self):
        v = TrustVerifier.from_connector_config({
            "sender_policy": "allowlist",
            "sender_allowlist": ["andrew@easylabs.io", "niko@easylabs.io"],
        })
        verdict = v.check_sender("andrew@easylabs.io")
        assert verdict.decision == TrustDecision.ACCEPT

    def test_reject_unlisted_sender(self):
        v = TrustVerifier.from_connector_config({
            "sender_policy": "allowlist",
            "sender_allowlist": ["andrew@easylabs.io"],
        })
        verdict = v.check_sender("hacker@evil.com")
        assert verdict.decision == TrustDecision.REJECT

    def test_trust_override_propagated(self):
        v = TrustVerifier.from_connector_config({
            "sender_policy": "allowlist",
            "sender_allowlist": [
                {"address": "andrew@easylabs.io", "trust_override": "high"},
            ],
        })
        verdict = v.check_sender("andrew@easylabs.io")
        assert verdict.trust_override == "high"

    def test_empty_sender_rejected(self):
        v = TrustVerifier.from_connector_config({
            "sender_policy": "allowlist",
            "sender_allowlist": ["andrew@easylabs.io"],
        })
        verdict = v.check_sender("")
        assert verdict.decision == TrustDecision.REJECT


class TestTrustVerifierDomain:
    def test_accept_matching_domain(self):
        v = TrustVerifier.from_connector_config({
            "sender_policy": "domain",
            "sender_domains": ["easylabs.io"],
        })
        verdict = v.check_sender("anyone@easylabs.io")
        assert verdict.decision == TrustDecision.ACCEPT

    def test_reject_non_matching_domain(self):
        v = TrustVerifier.from_connector_config({
            "sender_policy": "domain",
            "sender_domains": ["easylabs.io"],
        })
        verdict = v.check_sender("someone@other.com")
        assert verdict.decision == TrustDecision.REJECT


class TestTrustVerifierOpen:
    def test_accept_anyone(self):
        v = TrustVerifier.from_connector_config({
            "sender_policy": "open",
        })
        verdict = v.check_sender("random@anywhere.net")
        assert verdict.decision == TrustDecision.ACCEPT

    def test_accept_empty_sender(self):
        v = TrustVerifier.from_connector_config({
            "sender_policy": "open",
        })
        verdict = v.check_sender("")
        assert verdict.decision == TrustDecision.ACCEPT

    def test_default_is_open(self):
        v = TrustVerifier.from_connector_config({})
        verdict = v.check_sender("anyone@anywhere.com")
        assert verdict.decision == TrustDecision.ACCEPT


class TestIPAllowlist:
    def test_no_restriction_allows_all(self):
        v = TrustVerifier(
            policy=SenderPolicy.OPEN,
            entries=[],
            ip_allowlist=[],
        )
        assert v.check_ip("1.2.3.4") is True

    def test_exact_ip_match(self):
        v = TrustVerifier(
            policy=SenderPolicy.OPEN,
            entries=[],
            ip_allowlist=["10.0.0.1", "10.0.0.2"],
        )
        assert v.check_ip("10.0.0.1") is True
        assert v.check_ip("10.0.0.3") is False

    def test_cidr_match(self):
        v = TrustVerifier(
            policy=SenderPolicy.OPEN,
            entries=[],
            ip_allowlist=["192.168.1.0/24"],
        )
        assert v.check_ip("192.168.1.100") is True
        assert v.check_ip("192.168.2.1") is False

    def test_invalid_ip_rejected(self):
        v = TrustVerifier(
            policy=SenderPolicy.OPEN,
            entries=[],
            ip_allowlist=["10.0.0.0/8"],
        )
        assert v.check_ip("not-an-ip") is False


class TestHMACVerification:
    def test_valid_sha256(self):
        secret = "webhook-secret-123"
        body = b'{"event": "push"}'
        sig = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert verify_hmac_signature(body, sig, secret, algorithm="sha256") is True

    def test_invalid_signature(self):
        assert verify_hmac_signature(b"body", "badsig", "secret") is False

    def test_prefix_stripping(self):
        secret = "s3cret"
        body = b"data"
        sig = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()
        header = f"sha256={sig}"
        assert verify_hmac_signature(body, header, secret, prefix="sha256=") is True

    def test_empty_signature_rejected(self):
        assert verify_hmac_signature(b"x", "", "secret") is False

    def test_empty_secret_rejected(self):
        assert verify_hmac_signature(b"x", "sig", "") is False
```

**Test:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/lib/connectors/tests/test_trust.py -v
```

**Commit:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && git add plugin/lib/connectors/trust.py plugin/lib/connectors/tests/test_trust.py && git commit -m "$(cat <<'EOF'
feat: add trust and sender verification module

Two-layer trust: connector trust level (verified/high/medium/low) and
sender policies (allowlist/domain/open). Includes HMAC signature
verification, IP allowlist with CIDR support, and per-sender trust
overrides.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Connector registry

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/registry.py`

**What:** The registry loads connector configurations from `config/connectors.json`, instantiates the appropriate connector class for each entry, manages connector lifecycle (start/stop/restart), and discovers community connectors installed via npm.

### Step 3.1: Write the registry module

- [ ] Write `plugin/lib/connectors/registry.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/registry.py`

```python
"""
Connector registry: loads, manages lifecycle, and discovers connectors.

Loads connector configs from config/connectors.json, instantiates the
correct connector class per type, and provides start/stop/status/pull
operations across all active connectors.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from .base import Connector, ConnectorStatus, RawData, VaultNote


# Built-in connector type -> module mapping
BUILTIN_CONNECTORS: dict[str, str] = {
    "filesystem": "plugin.lib.connectors.filesystem",
    "webhook": "plugin.lib.connectors.webhook",
    "cron_fetch": "plugin.lib.connectors.cron_fetch",
    "cron-fetch": "plugin.lib.connectors.cron_fetch",
    "github": "plugin.lib.connectors.github",
    "slack": "plugin.lib.connectors.slack",
    "email": "plugin.lib.connectors.email",
}

# Connector class name convention: <Type>Connector (e.g. FilesystemConnector)
# Each module must expose a class matching this pattern.

PLUGIN_DIR = Path(
    os.environ.get(
        "OPENCLAW_PLUGIN_DIR",
        Path.home() / ".openclaw" / "extensions" / "openclaw-lacp-fusion",
    )
)
CONFIG_DIR = PLUGIN_DIR / "config"
CONNECTORS_CONFIG = CONFIG_DIR / "connectors.json"

# Community connectors live under the openclaw extensions directory
EXTENSIONS_DIR = Path(
    os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw")
) / "extensions"


class ConnectorLoadError(Exception):
    """Raised when a connector cannot be loaded."""
    pass


class ConnectorRegistry:
    """
    Manages all connector instances.

    Loads from config/connectors.json, discovers community connectors,
    and provides lifecycle operations.
    """

    def __init__(self, config_path: Optional[str | Path] = None):
        self.config_path = Path(config_path) if config_path else CONNECTORS_CONFIG
        self.connectors: dict[str, Connector] = {}
        self._config: dict[str, Any] = {}

    def load_config(self) -> dict[str, Any]:
        """Load connectors.json and return the parsed config."""
        if not self.config_path.exists():
            self._config = {"connectors": []}
            return self._config
        try:
            self._config = json.loads(self.config_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            raise ConnectorLoadError(f"Failed to read {self.config_path}: {exc}")
        return self._config

    def save_config(self):
        """Write current config back to disk."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(self._config, indent=2) + "\n"
        )

    def _resolve_connector_class(self, connector_type: str) -> type:
        """
        Find the Connector subclass for the given type.

        Checks built-in connectors first, then community connectors
        installed under extensions/.
        """
        # Built-in
        module_path = BUILTIN_CONNECTORS.get(connector_type)
        if module_path:
            try:
                mod = importlib.import_module(module_path)
            except ImportError as exc:
                raise ConnectorLoadError(
                    f"Failed to import built-in connector module {module_path}: {exc}"
                )
            class_name = (
                connector_type.replace("-", "_").replace("_", " ").title().replace(" ", "")
                + "Connector"
            )
            cls = getattr(mod, class_name, None)
            if cls is None:
                raise ConnectorLoadError(
                    f"Module {module_path} does not export class {class_name}"
                )
            return cls

        # Community: look for openclaw-lacp-connector-<type>
        community_dir = EXTENSIONS_DIR / f"openclaw-lacp-connector-{connector_type}"
        if community_dir.is_dir():
            return self._load_community_connector(community_dir, connector_type)

        raise ConnectorLoadError(
            f"Unknown connector type: {connector_type}. "
            f"Install with: openclaw plugins install openclaw-lacp-connector-{connector_type}"
        )

    def _load_community_connector(
        self, connector_dir: Path, connector_type: str
    ) -> type:
        """Load a community connector from its directory."""
        # Check for connector.json manifest
        manifest_path = connector_dir / "connector.json"
        if not manifest_path.exists():
            raise ConnectorLoadError(
                f"Community connector at {connector_dir} missing connector.json manifest"
            )

        try:
            manifest = json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            raise ConnectorLoadError(f"Bad connector.json at {manifest_path}: {exc}")

        # Load the Python module
        index_py = connector_dir / "index.py"
        if not index_py.exists():
            raise ConnectorLoadError(
                f"Community connector at {connector_dir} missing index.py"
            )

        # Add to sys.path temporarily and import
        if str(connector_dir) not in sys.path:
            sys.path.insert(0, str(connector_dir))

        try:
            spec = importlib.util.spec_from_file_location(
                f"connector_{connector_type}", str(index_py)
            )
            if spec is None or spec.loader is None:
                raise ConnectorLoadError(f"Cannot create module spec from {index_py}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as exc:
            raise ConnectorLoadError(f"Failed to load {index_py}: {exc}")

        # Find the Connector subclass
        class_name = (
            connector_type.replace("-", "_").replace("_", " ").title().replace(" ", "")
            + "Connector"
        )
        cls = getattr(mod, class_name, None)
        if cls is None:
            # Fallback: find any Connector subclass
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, Connector)
                    and attr is not Connector
                ):
                    cls = attr
                    break
        if cls is None:
            raise ConnectorLoadError(
                f"No Connector subclass found in {index_py}"
            )
        return cls

    def load_all(self) -> list[str]:
        """
        Load config and instantiate all connectors.

        Returns list of successfully loaded connector IDs.
        """
        self.load_config()
        loaded: list[str] = []
        errors: list[str] = []

        for entry in self._config.get("connectors", []):
            conn_id = entry.get("id", "unknown")
            conn_type = entry.get("type", "unknown")
            enabled = entry.get("enabled", True)

            if not enabled:
                continue

            try:
                cls = self._resolve_connector_class(conn_type)
                instance = cls(entry)
                self.connectors[conn_id] = instance
                loaded.append(conn_id)
            except ConnectorLoadError as exc:
                errors.append(f"{conn_id}: {exc}")
            except Exception as exc:
                errors.append(f"{conn_id}: unexpected error: {exc}")

        if errors:
            for err in errors:
                print(f"[connector-registry] WARN: {err}", file=sys.stderr)

        return loaded

    def start_all(self) -> dict[str, bool]:
        """Authenticate and start all loaded connectors. Returns {id: success}."""
        results: dict[str, bool] = {}
        for conn_id, conn in self.connectors.items():
            try:
                ok = conn.authenticate()
                if ok:
                    conn.start()
                results[conn_id] = ok
            except Exception as exc:
                conn.record_error(str(exc))
                results[conn_id] = False
        return results

    def stop_all(self):
        """Stop all connectors (clear registry)."""
        self.connectors.clear()

    def get(self, connector_id: str) -> Optional[Connector]:
        """Get a connector by ID."""
        return self.connectors.get(connector_id)

    def pull_all(self, vault_path: str | Path) -> list[Path]:
        """
        Run pull() on all pull/both-mode connectors, transform results,
        and write to vault.

        Returns list of written note paths.
        """
        written: list[Path] = []
        for conn_id, conn in self.connectors.items():
            if conn.mode not in ("pull", "both"):
                continue
            try:
                raw_items = conn.pull()
                conn.record_pull()
                for raw in raw_items:
                    note = conn.transform(raw)
                    path = note.write_to_vault(vault_path)
                    written.append(path)
                    conn.record_ingestion()
            except Exception as exc:
                conn.record_error(str(exc))
        return written

    def receive(
        self, connector_id: str, payload: dict[str, Any], vault_path: str | Path
    ) -> Optional[Path]:
        """
        Route an incoming webhook payload to the specified connector.

        Returns the written note path, or None if the connector is not found.
        """
        conn = self.connectors.get(connector_id)
        if conn is None:
            return None
        if conn.mode not in ("push", "both"):
            return None
        try:
            raw = conn.receive(payload)
            note = conn.transform(raw)
            path = note.write_to_vault(vault_path)
            conn.record_ingestion()
            return path
        except Exception as exc:
            conn.record_error(str(exc))
            return None

    def status_all(self) -> list[dict[str, Any]]:
        """Get health status for all connectors."""
        statuses: list[dict[str, Any]] = []
        for conn_id, conn in self.connectors.items():
            try:
                s = conn.health_check()
                statuses.append(s.to_dict())
            except Exception as exc:
                statuses.append({
                    "healthy": False,
                    "connector_id": conn_id,
                    "error": str(exc),
                })
        return statuses

    def add_connector(self, entry: dict[str, Any]) -> str:
        """Add a connector entry to the config (does not start it)."""
        conn_id = entry.get("id")
        if not conn_id:
            raise ValueError("Connector entry must have an 'id' field")
        # Check for duplicate
        for existing in self._config.get("connectors", []):
            if existing.get("id") == conn_id:
                raise ValueError(f"Connector with id '{conn_id}' already exists")
        self._config.setdefault("connectors", []).append(entry)
        self.save_config()
        return conn_id

    def remove_connector(self, connector_id: str) -> bool:
        """Remove a connector from config and stop it."""
        before = len(self._config.get("connectors", []))
        self._config["connectors"] = [
            c for c in self._config.get("connectors", [])
            if c.get("id") != connector_id
        ]
        removed = len(self._config.get("connectors", [])) < before
        if removed:
            self.save_config()
            self.connectors.pop(connector_id, None)
        return removed

    def list_available_types(self) -> list[dict[str, str]]:
        """List all available connector types (built-in + discovered community)."""
        types: list[dict[str, str]] = []

        # Built-in
        seen = set()
        for type_name in BUILTIN_CONNECTORS:
            canonical = type_name.replace("-", "_")
            if canonical not in seen:
                seen.add(canonical)
                tier = "native" if canonical in ("filesystem", "webhook", "cron_fetch") else "first-party"
                types.append({"type": type_name, "tier": tier})

        # Community
        if EXTENSIONS_DIR.is_dir():
            for d in EXTENSIONS_DIR.iterdir():
                if d.is_dir() and d.name.startswith("openclaw-lacp-connector-"):
                    ctype = d.name.replace("openclaw-lacp-connector-", "")
                    manifest = d / "connector.json"
                    if manifest.exists():
                        types.append({"type": ctype, "tier": "community"})

        return types
```

### Step 3.2: Write tests for registry

- [ ] Write `plugin/lib/connectors/tests/test_registry.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/tests/test_registry.py`

```python
"""Tests for connector registry."""

import json
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from lib.connectors.registry import ConnectorRegistry, ConnectorLoadError
from lib.connectors.base import Connector, ConnectorStatus, RawData, VaultNote


class TestRegistryLoadConfig:
    def test_load_empty_config(self, tmp_path):
        cfg_file = tmp_path / "connectors.json"
        cfg_file.write_text('{"connectors": []}')
        reg = ConnectorRegistry(config_path=cfg_file)
        config = reg.load_config()
        assert config["connectors"] == []

    def test_load_missing_config(self, tmp_path):
        reg = ConnectorRegistry(config_path=tmp_path / "nonexistent.json")
        config = reg.load_config()
        assert config["connectors"] == []

    def test_load_bad_json_raises(self, tmp_path):
        cfg_file = tmp_path / "connectors.json"
        cfg_file.write_text("not json{{{")
        reg = ConnectorRegistry(config_path=cfg_file)
        with pytest.raises(ConnectorLoadError):
            reg.load_config()


class TestRegistryAddRemove:
    def test_add_connector_entry(self, tmp_path):
        cfg_file = tmp_path / "connectors.json"
        cfg_file.write_text('{"connectors": []}')
        reg = ConnectorRegistry(config_path=cfg_file)
        reg.load_config()
        reg.add_connector({
            "id": "test-webhook",
            "type": "webhook",
            "config": {},
        })
        # Re-read from disk
        saved = json.loads(cfg_file.read_text())
        assert len(saved["connectors"]) == 1
        assert saved["connectors"][0]["id"] == "test-webhook"

    def test_add_duplicate_raises(self, tmp_path):
        cfg_file = tmp_path / "connectors.json"
        cfg_file.write_text('{"connectors": [{"id": "dupe", "type": "webhook"}]}')
        reg = ConnectorRegistry(config_path=cfg_file)
        reg.load_config()
        with pytest.raises(ValueError, match="already exists"):
            reg.add_connector({"id": "dupe", "type": "webhook"})

    def test_remove_connector(self, tmp_path):
        cfg_file = tmp_path / "connectors.json"
        cfg_file.write_text(json.dumps({
            "connectors": [
                {"id": "keep", "type": "webhook"},
                {"id": "remove-me", "type": "filesystem"},
            ]
        }))
        reg = ConnectorRegistry(config_path=cfg_file)
        reg.load_config()
        assert reg.remove_connector("remove-me") is True
        saved = json.loads(cfg_file.read_text())
        assert len(saved["connectors"]) == 1
        assert saved["connectors"][0]["id"] == "keep"

    def test_remove_nonexistent_returns_false(self, tmp_path):
        cfg_file = tmp_path / "connectors.json"
        cfg_file.write_text('{"connectors": []}')
        reg = ConnectorRegistry(config_path=cfg_file)
        reg.load_config()
        assert reg.remove_connector("ghost") is False


class TestRegistryStatusAll:
    def test_status_empty_registry(self, tmp_path):
        cfg_file = tmp_path / "connectors.json"
        cfg_file.write_text('{"connectors": []}')
        reg = ConnectorRegistry(config_path=cfg_file)
        reg.load_config()
        assert reg.status_all() == []
```

**Test:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/lib/connectors/tests/test_registry.py -v
```

**Commit:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && git add plugin/lib/connectors/registry.py plugin/lib/connectors/tests/test_registry.py && git commit -m "$(cat <<'EOF'
feat: add connector registry with config loading and lifecycle management

Loads connectors from config/connectors.json, resolves built-in and
community connector types, manages start/stop/pull/receive lifecycle,
and provides add/remove/status operations.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Filesystem connector (native)

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/filesystem.py`

**What:** Adapt the existing `openclaw-ingest-watch` pattern into a proper Connector subclass. Watches configured directories for new/changed files, classifies them (transcript, pdf, url, file), and transforms into VaultNote objects. Uses polling (not inotify) for cross-platform compatibility.

### Step 4.1: Write the filesystem connector

- [ ] Write `plugin/lib/connectors/filesystem.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/filesystem.py`

```python
"""
Filesystem connector (Tier 1 -- Native).

Watches configured directories for new or changed files and transforms
them into VaultNote objects. Adapted from openclaw-ingest-watch.

Config keys:
  - watch_paths: list of directory paths to watch
  - extensions: list of file extensions to accept (e.g. [".md", ".txt", ".pdf"])
  - ignore_patterns: list of glob patterns to ignore (e.g. ["*.tmp", ".DS_Store"])
  - poll_interval_seconds: how often to scan (default: 60)
"""

from __future__ import annotations

import fnmatch
import os
import plistlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .base import Connector, ConnectorStatus, RawData, VaultNote, TrustLevel


# Transcript detection patterns (from openclaw-ingest-watch)
TRANSCRIPT_PATTERNS = [
    re.compile(r"^Speaker\s*:", re.MULTILINE),
    re.compile(r"^\[?\d{1,2}:\d{2}", re.MULTILINE),
    re.compile(r"^Q\s*:", re.MULTILINE),
    re.compile(r"^A\s*:", re.MULTILINE),
    re.compile(r"\[\d{2}:\d{2}:\d{2}\]", re.MULTILINE),
]


def _is_transcript(file_path: Path) -> bool:
    """Heuristic: does the file look like a transcript?"""
    try:
        text = file_path.read_text(errors="ignore")[:4096]
    except OSError:
        return False
    hits = sum(1 for pat in TRANSCRIPT_PATTERNS if pat.search(text))
    return hits >= 2


def _classify_file(file_path: Path) -> str:
    """Return the file type: transcript, pdf, url, or file."""
    suffix = file_path.suffix.lower()
    if suffix in (".url", ".webloc"):
        return "url"
    if suffix == ".pdf":
        return "pdf"
    if suffix in (".md", ".txt"):
        if _is_transcript(file_path):
            return "transcript"
        return "file"
    return "file"


def _extract_url(file_path: Path) -> str:
    """Extract a URL from a .url or .webloc file."""
    suffix = file_path.suffix.lower()
    if suffix == ".webloc":
        try:
            with open(file_path, "rb") as f:
                plist = plistlib.load(f)
            return plist.get("URL", "")
        except Exception:
            pass
    if suffix == ".url":
        try:
            text = file_path.read_text(errors="ignore")
            for line in text.splitlines():
                if line.strip().upper().startswith("URL="):
                    return line.split("=", 1)[1].strip()
        except OSError:
            pass
    # Fallback: find any URL in the file
    try:
        text = file_path.read_text(errors="ignore")[:2048]
        m = re.search(r"https?://[^\s<>\"]+", text)
        if m:
            return m.group(0)
    except OSError:
        pass
    return ""


class FilesystemConnector(Connector):
    """
    Watch local directories for new files and ingest them as vault notes.

    Maintains a set of already-seen file paths (by mtime + size hash)
    to avoid re-ingesting unchanged files.
    """

    type = "filesystem"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._watch_paths: list[str] = self.connector_config.get("watch_paths", [])
        self._extensions: list[str] = self.connector_config.get(
            "extensions", [".md", ".txt", ".pdf", ".url", ".webloc"]
        )
        self._ignore_patterns: list[str] = self.connector_config.get(
            "ignore_patterns", ["*.tmp", ".DS_Store", "*.swp", "*~"]
        )
        self._seen: dict[str, float] = {}  # path -> mtime

    def authenticate(self) -> bool:
        """Verify that at least one watch path exists."""
        valid = 0
        for wp in self._watch_paths:
            p = Path(os.path.expanduser(wp)).resolve()
            if p.is_dir():
                valid += 1
        return valid > 0

    def pull(self) -> list[RawData]:
        """Scan watch paths for new or changed files."""
        results: list[RawData] = []

        for wp in self._watch_paths:
            dir_path = Path(os.path.expanduser(wp)).resolve()
            if not dir_path.is_dir():
                continue

            for entry in dir_path.iterdir():
                if not entry.is_file():
                    continue
                if entry.parent.name == "processed":
                    continue
                if not self._extension_match(entry):
                    continue
                if self._is_ignored(entry):
                    continue

                abs_str = str(entry.resolve())
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue

                # Skip if we've already seen this file at this mtime
                if abs_str in self._seen and self._seen[abs_str] >= mtime:
                    continue

                self._seen[abs_str] = mtime
                file_type = _classify_file(entry)

                payload: dict[str, Any] = {
                    "file_path": abs_str,
                    "file_name": entry.name,
                    "file_type": file_type,
                    "file_size": entry.stat().st_size,
                }

                if file_type == "url":
                    url = _extract_url(entry)
                    if url:
                        payload["url"] = url

                results.append(RawData(
                    source_id=abs_str,
                    payload=payload,
                    sender=f"filesystem:{wp}",
                ))

        return results

    def transform(self, raw_data: RawData) -> VaultNote:
        """Convert a file discovery into a VaultNote."""
        p = raw_data.payload
        file_path = Path(p["file_path"])
        file_type = p.get("file_type", "file")
        file_name = p.get("file_name", file_path.name)

        if file_type == "url":
            url = p.get("url", "")
            title = f"Link: {file_path.stem}"
            body = f"Source URL: [{url}]({url})\n\nImported from: `{file_name}`"
            tags = ["link", "imported"]
        elif file_type == "transcript":
            title = f"Transcript: {file_path.stem}"
            try:
                content = file_path.read_text(errors="ignore")
            except OSError:
                content = "(could not read file)"
            body = content
            tags = ["transcript", "imported"]
        elif file_type == "pdf":
            title = f"PDF: {file_path.stem}"
            body = f"PDF imported from: `{file_name}`\n\n(PDF text extraction pending)"
            tags = ["pdf", "imported"]
        else:
            title = file_path.stem
            try:
                content = file_path.read_text(errors="ignore")[:4000]
            except OSError:
                content = "(could not read file)"
            body = content
            tags = ["imported"]

        return VaultNote(
            title=title,
            body=body,
            source_connector=self.id,
            source_type=self.type,
            source_id=raw_data.source_id,
            trust_level=self.trust_level,
            landing_zone=self.landing_zone,
            tags=tags,
            category=file_type,
            source_url=p.get("url", ""),
        )

    def health_check(self) -> ConnectorStatus:
        status = self.base_status(healthy=True)
        valid_paths = []
        for wp in self._watch_paths:
            p = Path(os.path.expanduser(wp)).resolve()
            if p.is_dir():
                valid_paths.append(str(p))
            else:
                status.healthy = False
        status.extra["watch_paths"] = valid_paths
        status.extra["seen_files"] = len(self._seen)
        return status

    def _extension_match(self, entry: Path) -> bool:
        if not self._extensions:
            return True
        return entry.suffix.lower() in self._extensions

    def _is_ignored(self, entry: Path) -> bool:
        for pattern in self._ignore_patterns:
            if fnmatch.fnmatch(entry.name, pattern):
                return True
        return False
```

### Step 4.2: Write tests for filesystem connector

- [ ] Write `plugin/lib/connectors/tests/test_filesystem.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/tests/test_filesystem.py`

```python
"""Tests for filesystem connector."""

import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from lib.connectors.filesystem import FilesystemConnector, _classify_file, _is_transcript


class TestFileClassification:
    def test_pdf(self, tmp_path):
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 dummy")
        assert _classify_file(f) == "pdf"

    def test_url_file(self, tmp_path):
        f = tmp_path / "link.url"
        f.write_text("[InternetShortcut]\nURL=https://example.com\n")
        assert _classify_file(f) == "url"

    def test_markdown(self, tmp_path):
        f = tmp_path / "note.md"
        f.write_text("# Hello\n\nSome notes.")
        assert _classify_file(f) == "file"

    def test_transcript_detection(self, tmp_path):
        f = tmp_path / "meeting.md"
        f.write_text(
            "Speaker: Alice\n[00:01] Hello\nSpeaker: Bob\n[00:02] Hi there\nQ: How?\nA: Like this."
        )
        assert _classify_file(f) == "transcript"


class TestFilesystemConnector:
    def _make_connector(self, watch_paths):
        return FilesystemConnector({
            "id": "test-fs",
            "type": "filesystem",
            "trust_level": "high",
            "mode": "pull",
            "landing_zone": "queue-agent",
            "config": {
                "watch_paths": watch_paths,
                "extensions": [".md", ".txt"],
                "ignore_patterns": ["*.tmp", ".DS_Store"],
            },
        })

    def test_authenticate_with_valid_path(self, tmp_path):
        conn = self._make_connector([str(tmp_path)])
        assert conn.authenticate() is True

    def test_authenticate_with_no_valid_paths(self):
        conn = self._make_connector(["/nonexistent/path/abc123"])
        assert conn.authenticate() is False

    def test_pull_discovers_new_file(self, tmp_path):
        (tmp_path / "note.md").write_text("# Hello")
        conn = self._make_connector([str(tmp_path)])
        results = conn.pull()
        assert len(results) == 1
        assert results[0].payload["file_name"] == "note.md"

    def test_pull_skips_seen_file(self, tmp_path):
        (tmp_path / "note.md").write_text("# Hello")
        conn = self._make_connector([str(tmp_path)])
        first = conn.pull()
        assert len(first) == 1
        second = conn.pull()
        assert len(second) == 0

    def test_pull_skips_ignored_patterns(self, tmp_path):
        (tmp_path / "good.md").write_text("ok")
        (tmp_path / "bad.tmp").write_text("skip")
        (tmp_path / ".DS_Store").write_text("skip")
        conn = self._make_connector([str(tmp_path)])
        results = conn.pull()
        assert len(results) == 1
        assert results[0].payload["file_name"] == "good.md"

    def test_pull_skips_wrong_extension(self, tmp_path):
        (tmp_path / "image.png").write_bytes(b"PNG")
        conn = self._make_connector([str(tmp_path)])
        results = conn.pull()
        assert len(results) == 0

    def test_transform_file(self, tmp_path):
        f = tmp_path / "note.md"
        f.write_text("# My Note\n\nContent here.")
        conn = self._make_connector([str(tmp_path)])
        results = conn.pull()
        note = conn.transform(results[0])
        assert note.title == "note"
        assert note.source_connector == "test-fs"
        assert note.trust_level == "high"

    def test_health_check(self, tmp_path):
        conn = self._make_connector([str(tmp_path)])
        conn.start()
        status = conn.health_check()
        assert status.healthy is True
        assert str(tmp_path) in status.extra["watch_paths"]
```

**Test:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/lib/connectors/tests/test_filesystem.py -v
```

**Commit:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && git add plugin/lib/connectors/filesystem.py plugin/lib/connectors/tests/test_filesystem.py && git commit -m "$(cat <<'EOF'
feat: add filesystem connector adapted from openclaw-ingest-watch

Watches configured directories for new/changed files. Classifies as
transcript, pdf, url, or file. Supports extension filtering and ignore
patterns. Tracks seen files by mtime to avoid re-ingestion.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Webhook connector (native)

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/webhook.py`

**What:** Generic webhook connector that receives HTTP POST payloads, verifies HMAC signatures, checks IP allowlist, and runs optional custom transform scripts. This is the escape hatch for any service that supports webhooks.

### Step 5.1: Write the webhook connector

- [ ] Write `plugin/lib/connectors/webhook.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/webhook.py`

```python
"""
Webhook connector (Tier 1 -- Native).

Generic HTTP webhook receiver with HMAC signature verification,
IP allowlist, and custom transform scripts.

Config keys:
  - path: URL path this connector handles (e.g. "/hooks/sentry")
  - hmac_secret: shared secret for HMAC verification
  - hmac_header: HTTP header name containing the signature
  - hmac_algorithm: hash algorithm (default: sha256)
  - hmac_prefix: prefix to strip from signature (e.g. "sha256=")
  - ip_allowlist: list of allowed IP addresses/CIDRs
  - transform: path to a custom Python transform script (optional)
  - title_template: Python format string for note title (e.g. "{event}: {summary}")
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from .base import Connector, ConnectorStatus, RawData, VaultNote
from .trust import TrustVerifier, verify_hmac_signature


class WebhookConnector(Connector):
    """
    Receive webhook payloads via HTTP POST and transform into vault notes.

    The curator's HTTP surface routes incoming webhooks to this connector
    based on the configured path.
    """

    type = "webhook"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._path: str = self.connector_config.get("path", f"/hooks/{self.id}")
        self._hmac_secret: str = self.connector_config.get("hmac_secret", "")
        self._hmac_header: str = self.connector_config.get("hmac_header", "X-Hub-Signature-256")
        self._hmac_algorithm: str = self.connector_config.get("hmac_algorithm", "sha256")
        self._hmac_prefix: str = self.connector_config.get("hmac_prefix", "")
        self._transform_path: str = self.connector_config.get("transform", "")
        self._title_template: str = self.connector_config.get("title_template", "Webhook: {id}")
        self._custom_transform: Optional[Callable] = None
        self._trust_verifier = TrustVerifier.from_connector_config(self.connector_config)

    @property
    def path(self) -> str:
        return self._path

    def authenticate(self) -> bool:
        """Webhook connectors are always ready. Auth is per-request via HMAC."""
        # Load custom transform if configured
        if self._transform_path:
            self._custom_transform = self._load_transform_script(self._transform_path)
        return True

    def _load_transform_script(self, script_path: str) -> Optional[Callable]:
        """
        Load a custom transform function from a Python script.

        The script must define a function: transform(payload: dict) -> dict
        that returns a dict with keys: title, body, tags (optional), category (optional).
        """
        # Resolve relative to plugin config dir
        p = Path(script_path)
        if not p.is_absolute():
            plugin_dir = Path(
                os.environ.get(
                    "OPENCLAW_PLUGIN_DIR",
                    Path.home() / ".openclaw" / "extensions" / "openclaw-lacp-fusion",
                )
            )
            p = plugin_dir / script_path

        if not p.exists():
            return None

        try:
            spec = importlib.util.spec_from_file_location("custom_transform", str(p))
            if spec is None or spec.loader is None:
                return None
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            fn = getattr(mod, "transform", None)
            if callable(fn):
                return fn
        except Exception:
            pass
        return None

    def verify_request(
        self,
        body: bytes,
        headers: dict[str, str],
        source_ip: str = "",
    ) -> bool:
        """
        Verify an incoming webhook request.

        Checks HMAC signature (if configured) and IP allowlist.
        """
        # IP check
        if source_ip and not self._trust_verifier.check_ip(source_ip):
            self.record_error(f"IP rejected: {source_ip}")
            return False

        # HMAC check
        if self._hmac_secret:
            sig = headers.get(self._hmac_header, "")
            if not verify_hmac_signature(
                body,
                sig,
                self._hmac_secret,
                algorithm=self._hmac_algorithm,
                prefix=self._hmac_prefix,
            ):
                self.record_error("HMAC verification failed")
                return False

        return True

    def receive(self, payload: dict[str, Any]) -> RawData:
        """Accept an incoming webhook payload as RawData."""
        # Generate a source_id from the payload
        source_id = payload.get("id") or payload.get(
            "event_id"
        ) or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")

        return RawData(
            source_id=str(source_id),
            payload=payload,
            sender=payload.get("sender", payload.get("source", "")),
        )

    def transform(self, raw_data: RawData) -> VaultNote:
        """Transform webhook payload into a VaultNote."""
        payload = raw_data.payload

        # Use custom transform if available
        if self._custom_transform is not None:
            try:
                result = self._custom_transform(payload)
                return VaultNote(
                    title=result.get("title", f"Webhook: {raw_data.source_id}"),
                    body=result.get("body", json.dumps(payload, indent=2)),
                    source_connector=self.id,
                    source_type=self.type,
                    source_id=raw_data.source_id,
                    trust_level=self.trust_level,
                    landing_zone=self.landing_zone,
                    tags=result.get("tags", ["webhook"]),
                    category=result.get("category", "webhook"),
                    source_url=result.get("source_url", ""),
                )
            except Exception as exc:
                self.record_error(f"Custom transform failed: {exc}")
                # Fall through to default transform

        # Default transform: dump payload as formatted JSON
        try:
            title = self._title_template.format(**payload, id=raw_data.source_id)
        except (KeyError, IndexError):
            title = f"Webhook: {raw_data.source_id}"

        body = f"## Payload\n\n```json\n{json.dumps(payload, indent=2)}\n```"

        return VaultNote(
            title=title,
            body=body,
            source_connector=self.id,
            source_type=self.type,
            source_id=raw_data.source_id,
            trust_level=self.trust_level,
            landing_zone=self.landing_zone,
            tags=["webhook"],
            category="webhook",
        )

    def health_check(self) -> ConnectorStatus:
        status = self.base_status(healthy=True)
        status.extra["path"] = self._path
        status.extra["hmac_configured"] = bool(self._hmac_secret)
        status.extra["custom_transform"] = self._transform_path or None
        return status
```

### Step 5.2: Write tests for webhook connector

- [ ] Write `plugin/lib/connectors/tests/test_webhook.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/tests/test_webhook.py`

```python
"""Tests for webhook connector."""

import hashlib
import hmac as hmac_mod
import json
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from lib.connectors.webhook import WebhookConnector
from lib.connectors.base import RawData


def _make_connector(**overrides):
    cfg = {
        "id": "test-webhook",
        "type": "webhook",
        "trust_level": "medium",
        "mode": "push",
        "landing_zone": "queue-cicd",
        "config": {
            "path": "/hooks/test",
            "hmac_secret": "test-secret",
            "hmac_header": "X-Signature",
            "hmac_algorithm": "sha256",
            **overrides,
        },
    }
    return WebhookConnector(cfg)


class TestWebhookAuth:
    def test_authenticate_always_true(self):
        conn = _make_connector()
        assert conn.authenticate() is True

    def test_path_from_config(self):
        conn = _make_connector()
        assert conn.path == "/hooks/test"


class TestWebhookVerification:
    def test_valid_hmac(self):
        conn = _make_connector()
        body = b'{"event": "test"}'
        sig = hmac_mod.new(b"test-secret", body, hashlib.sha256).hexdigest()
        assert conn.verify_request(body, {"X-Signature": sig}) is True

    def test_invalid_hmac(self):
        conn = _make_connector()
        assert conn.verify_request(b"body", {"X-Signature": "bad"}) is False

    def test_missing_hmac_header(self):
        conn = _make_connector()
        assert conn.verify_request(b"body", {}) is False

    def test_ip_allowlist_accepts(self):
        conn = _make_connector(ip_allowlist=["10.0.0.0/8"])
        body = b'{"event": "test"}'
        sig = hmac_mod.new(b"test-secret", body, hashlib.sha256).hexdigest()
        assert conn.verify_request(body, {"X-Signature": sig}, source_ip="10.1.2.3") is True

    def test_ip_allowlist_rejects(self):
        conn = _make_connector(ip_allowlist=["10.0.0.0/8"])
        assert conn.verify_request(b"body", {}, source_ip="192.168.1.1") is False

    def test_no_hmac_secret_skips_verification(self):
        conn = _make_connector(hmac_secret="")
        assert conn.verify_request(b"body", {}) is True


class TestWebhookTransform:
    def test_default_transform(self):
        conn = _make_connector()
        conn.authenticate()
        raw = RawData(
            source_id="evt-1",
            payload={"event": "deploy", "status": "success"},
        )
        note = conn.transform(raw)
        assert "evt-1" in note.title
        assert "deploy" in note.body
        assert note.source_connector == "test-webhook"

    def test_title_template(self):
        conn = _make_connector(title_template="{event}: {status}")
        conn.authenticate()
        raw = RawData(
            source_id="evt-2",
            payload={"event": "build", "status": "failed"},
        )
        note = conn.transform(raw)
        assert note.title == "build: failed"

    def test_receive_extracts_source_id(self):
        conn = _make_connector()
        raw = conn.receive({"id": "hook-42", "data": "value"})
        assert raw.source_id == "hook-42"

    def test_receive_generates_id_if_missing(self):
        conn = _make_connector()
        raw = conn.receive({"data": "value"})
        assert len(raw.source_id) > 0
```

**Test:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/lib/connectors/tests/test_webhook.py -v
```

**Commit:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && git add plugin/lib/connectors/webhook.py plugin/lib/connectors/tests/test_webhook.py && git commit -m "$(cat <<'EOF'
feat: add generic webhook connector with HMAC and IP verification

Receives HTTP POST payloads, verifies HMAC signatures, checks IP
allowlist, supports custom Python transform scripts and title templates.
Default transform renders payload as formatted JSON.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Cron-fetch connector (native)

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/cron_fetch.py`

**What:** Poll URLs on a schedule, transform responses into vault notes. Useful for RSS feeds, status pages, API endpoints.

### Step 6.1: Write the cron-fetch connector

- [ ] Write `plugin/lib/connectors/cron_fetch.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/cron_fetch.py`

```python
"""
Cron-fetch connector (Tier 1 -- Native).

Polls configured URLs on a schedule and transforms responses into vault
notes. Useful for RSS feeds, status pages, API endpoints.

Config keys:
  - urls: list of URL configs, each with:
      - url: the URL to fetch
      - headers: optional dict of HTTP headers
      - method: GET (default) or POST
      - body: optional request body (for POST)
      - label: human-readable name for this source
  - poll_interval_minutes: how often to poll (default: 30)
  - transform: optional path to custom transform script
  - response_format: "json" | "text" | "auto" (default: auto)
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from .base import Connector, ConnectorStatus, RawData, VaultNote


class CronFetchConnector(Connector):
    """Poll URLs on a schedule and transform responses into vault notes."""

    type = "cron_fetch"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._url_configs: list[dict[str, Any]] = self.connector_config.get("urls", [])
        self._poll_interval: int = self.connector_config.get("poll_interval_minutes", 30)
        self._response_format: str = self.connector_config.get("response_format", "auto")
        self._transform_path: str = self.connector_config.get("transform", "")
        self._custom_transform: Optional[Callable] = None
        self._last_hashes: dict[str, str] = {}  # url -> content hash

    def authenticate(self) -> bool:
        """Verify at least one URL is configured."""
        if self._transform_path:
            self._custom_transform = self._load_transform(self._transform_path)
        return len(self._url_configs) > 0

    def _load_transform(self, script_path: str) -> Optional[Callable]:
        """Load a custom transform function from a Python script."""
        p = Path(script_path)
        if not p.is_absolute():
            plugin_dir = Path(
                os.environ.get(
                    "OPENCLAW_PLUGIN_DIR",
                    Path.home() / ".openclaw" / "extensions" / "openclaw-lacp-fusion",
                )
            )
            p = plugin_dir / script_path
        if not p.exists():
            return None
        try:
            spec = importlib.util.spec_from_file_location("cron_transform", str(p))
            if spec is None or spec.loader is None:
                return None
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            fn = getattr(mod, "transform", None)
            return fn if callable(fn) else None
        except Exception:
            return None

    def pull(self) -> list[RawData]:
        """Fetch all configured URLs and return new/changed responses."""
        results: list[RawData] = []

        for url_cfg in self._url_configs:
            if isinstance(url_cfg, str):
                url_cfg = {"url": url_cfg}

            url = url_cfg.get("url", "")
            if not url:
                continue

            label = url_cfg.get("label", url)
            headers = url_cfg.get("headers", {})
            method = url_cfg.get("method", "GET").upper()
            body = url_cfg.get("body")

            try:
                content = self._fetch(url, headers, method, body)
            except Exception as exc:
                self.record_error(f"Fetch failed for {url}: {exc}")
                continue

            # Check if content changed since last fetch
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            if url in self._last_hashes and self._last_hashes[url] == content_hash:
                continue  # unchanged
            self._last_hashes[url] = content_hash

            # Parse response
            payload: dict[str, Any] = {
                "url": url,
                "label": label,
                "content_type": self._response_format,
            }

            if self._response_format == "json" or (
                self._response_format == "auto" and self._looks_like_json(content)
            ):
                try:
                    payload["data"] = json.loads(content)
                    payload["content_type"] = "json"
                except json.JSONDecodeError:
                    payload["data"] = content
                    payload["content_type"] = "text"
            else:
                payload["data"] = content
                payload["content_type"] = "text"

            source_id = hashlib.md5(f"{url}:{content_hash[:16]}".encode()).hexdigest()[:12]

            results.append(RawData(
                source_id=source_id,
                payload=payload,
                sender=f"cron-fetch:{url}",
            ))

        return results

    def _fetch(
        self, url: str, headers: dict[str, str], method: str, body: Optional[str]
    ) -> str:
        """Fetch a URL using urllib (no external dependencies)."""
        req = urllib.request.Request(url, method=method)
        for k, v in headers.items():
            req.add_header(k, v)
        req.add_header("User-Agent", "openclaw-lacp-connector/1.0")

        data = body.encode() if body else None
        with urllib.request.urlopen(req, data=data, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")

    @staticmethod
    def _looks_like_json(content: str) -> bool:
        stripped = content.strip()
        return (stripped.startswith("{") and stripped.endswith("}")) or (
            stripped.startswith("[") and stripped.endswith("]")
        )

    def transform(self, raw_data: RawData) -> VaultNote:
        """Transform fetched content into a VaultNote."""
        payload = raw_data.payload

        if self._custom_transform is not None:
            try:
                result = self._custom_transform(payload)
                return VaultNote(
                    title=result.get("title", payload.get("label", "Fetched")),
                    body=result.get("body", str(payload.get("data", ""))),
                    source_connector=self.id,
                    source_type=self.type,
                    source_id=raw_data.source_id,
                    trust_level=self.trust_level,
                    landing_zone=self.landing_zone,
                    tags=result.get("tags", ["cron-fetch"]),
                    category=result.get("category", "fetch"),
                    source_url=payload.get("url", ""),
                )
            except Exception as exc:
                self.record_error(f"Custom transform failed: {exc}")

        # Default transform
        label = payload.get("label", payload.get("url", "Unknown"))
        data = payload.get("data", "")
        content_type = payload.get("content_type", "text")

        if content_type == "json":
            body = f"## Source\n\n[{label}]({payload.get('url', '')})\n\n## Data\n\n```json\n{json.dumps(data, indent=2)}\n```"
        else:
            body = f"## Source\n\n[{label}]({payload.get('url', '')})\n\n## Content\n\n{data}"

        return VaultNote(
            title=f"Fetch: {label}",
            body=body,
            source_connector=self.id,
            source_type=self.type,
            source_id=raw_data.source_id,
            trust_level=self.trust_level,
            landing_zone=self.landing_zone,
            tags=["cron-fetch"],
            category="fetch",
            source_url=payload.get("url", ""),
        )

    def health_check(self) -> ConnectorStatus:
        status = self.base_status(healthy=True)
        status.extra["url_count"] = len(self._url_configs)
        status.extra["poll_interval_minutes"] = self._poll_interval
        status.extra["tracked_urls"] = len(self._last_hashes)
        return status
```

### Step 6.2: Write tests for cron-fetch connector

- [ ] Write `plugin/lib/connectors/tests/test_cron_fetch.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/tests/test_cron_fetch.py`

```python
"""Tests for cron-fetch connector."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from lib.connectors.cron_fetch import CronFetchConnector
from lib.connectors.base import RawData


def _make_connector(**config_overrides):
    cfg = {
        "id": "test-fetch",
        "type": "cron_fetch",
        "trust_level": "medium",
        "mode": "pull",
        "landing_zone": "queue-human",
        "config": {
            "urls": [{"url": "https://example.com/api/data", "label": "Test API"}],
            "poll_interval_minutes": 15,
            **config_overrides,
        },
    }
    return CronFetchConnector(cfg)


class TestCronFetchAuth:
    def test_authenticate_with_urls(self):
        conn = _make_connector()
        assert conn.authenticate() is True

    def test_authenticate_no_urls(self):
        conn = _make_connector(urls=[])
        assert conn.authenticate() is False


class TestCronFetchPull:
    @patch.object(CronFetchConnector, "_fetch")
    def test_pull_returns_new_data(self, mock_fetch):
        mock_fetch.return_value = '{"status": "ok"}'
        conn = _make_connector()
        results = conn.pull()
        assert len(results) == 1
        assert results[0].payload["content_type"] == "json"
        assert results[0].payload["data"]["status"] == "ok"

    @patch.object(CronFetchConnector, "_fetch")
    def test_pull_skips_unchanged(self, mock_fetch):
        mock_fetch.return_value = '{"status": "ok"}'
        conn = _make_connector()
        first = conn.pull()
        assert len(first) == 1
        second = conn.pull()
        assert len(second) == 0

    @patch.object(CronFetchConnector, "_fetch")
    def test_pull_detects_change(self, mock_fetch):
        conn = _make_connector()
        mock_fetch.return_value = '{"v": 1}'
        conn.pull()
        mock_fetch.return_value = '{"v": 2}'
        results = conn.pull()
        assert len(results) == 1

    @patch.object(CronFetchConnector, "_fetch")
    def test_pull_handles_text_response(self, mock_fetch):
        mock_fetch.return_value = "plain text content"
        conn = _make_connector(response_format="text")
        results = conn.pull()
        assert len(results) == 1
        assert results[0].payload["content_type"] == "text"

    @patch.object(CronFetchConnector, "_fetch")
    def test_pull_handles_fetch_error(self, mock_fetch):
        mock_fetch.side_effect = Exception("timeout")
        conn = _make_connector()
        results = conn.pull()
        assert len(results) == 0


class TestCronFetchTransform:
    def test_transform_json(self):
        conn = _make_connector()
        raw = RawData(
            source_id="f1",
            payload={
                "url": "https://example.com/api",
                "label": "Test API",
                "content_type": "json",
                "data": {"status": "healthy"},
            },
        )
        note = conn.transform(raw)
        assert "Fetch: Test API" in note.title
        assert "healthy" in note.body
        assert note.source_url == "https://example.com/api"

    def test_transform_text(self):
        conn = _make_connector()
        raw = RawData(
            source_id="f2",
            payload={
                "url": "https://example.com/page",
                "label": "Page",
                "content_type": "text",
                "data": "Hello world",
            },
        )
        note = conn.transform(raw)
        assert "Hello world" in note.body


class TestCronFetchHealth:
    def test_health_check(self):
        conn = _make_connector()
        conn.start()
        status = conn.health_check()
        assert status.healthy is True
        assert status.extra["url_count"] == 1
```

**Test:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/lib/connectors/tests/test_cron_fetch.py -v
```

**Commit:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && git add plugin/lib/connectors/cron_fetch.py plugin/lib/connectors/tests/test_cron_fetch.py && git commit -m "$(cat <<'EOF'
feat: add cron-fetch connector for polling URLs on schedule

Fetches configured URLs, detects changed content via SHA256 hash,
supports JSON and text response formats, custom transform scripts.
Uses stdlib urllib only (no external HTTP dependencies).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: GitHub connector (first-party)

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/github.py`

**What:** Handle GitHub webhook events (pull_request, push, deployment, release). Verify webhook secret. Transform PR events into structured vault notes with status, author, diff summary. Support repo allowlist filtering.

### Step 7.1: Write the GitHub connector

- [ ] Write `plugin/lib/connectors/github.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/github.py`

```python
"""
GitHub connector (Tier 2 -- First-party).

Handles GitHub webhook events: pull_request, push, deployment, release.
Verifies webhook secret, filters by repo allowlist, and transforms
events into structured vault notes.

Config keys:
  - webhook_secret: GitHub webhook secret for HMAC-SHA256 verification
  - repos: list of "owner/repo" strings to accept (empty = accept all)
  - events: list of event types to process (default: all supported)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from .base import Connector, ConnectorStatus, RawData, VaultNote
from .trust import verify_hmac_signature


SUPPORTED_EVENTS = {"pull_request", "push", "deployment", "release", "issues"}


class GithubConnector(Connector):
    """Receive and process GitHub webhook events."""

    type = "github"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._webhook_secret: str = self.connector_config.get("webhook_secret", "")
        self._repos: list[str] = self.connector_config.get("repos", [])
        self._events: set[str] = set(
            self.connector_config.get("events", list(SUPPORTED_EVENTS))
        )
        self._processed_deliveries: set[str] = set()

    def authenticate(self) -> bool:
        """GitHub connector requires a webhook secret."""
        return bool(self._webhook_secret)

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        """Verify GitHub webhook HMAC-SHA256 signature."""
        return verify_hmac_signature(
            payload_body=body,
            signature_header=signature,
            secret=self._webhook_secret,
            algorithm="sha256",
            prefix="sha256=",
        )

    def receive(self, payload: dict[str, Any]) -> RawData:
        """Accept a GitHub webhook payload."""
        event_type = payload.get("_event_type", "unknown")
        delivery_id = payload.get("_delivery_id", "")

        # Extract repo info
        repo = payload.get("repository", {})
        repo_full_name = repo.get("full_name", "unknown/unknown")

        # Filter by repo allowlist
        if self._repos and repo_full_name not in self._repos:
            raise ValueError(f"Repo {repo_full_name} not in allowlist")

        # Filter by event type
        if event_type not in self._events:
            raise ValueError(f"Event type {event_type} not in accepted events")

        # Deduplicate by delivery ID
        if delivery_id and delivery_id in self._processed_deliveries:
            raise ValueError(f"Duplicate delivery: {delivery_id}")
        if delivery_id:
            self._processed_deliveries.add(delivery_id)
            # Keep set bounded
            if len(self._processed_deliveries) > 10000:
                self._processed_deliveries = set(
                    list(self._processed_deliveries)[-5000:]
                )

        sender = payload.get("sender", {}).get("login", "unknown")

        return RawData(
            source_id=f"{event_type}-{delivery_id or repo_full_name}",
            payload=payload,
            sender=sender,
            metadata={"event_type": event_type, "repo": repo_full_name},
        )

    def transform(self, raw_data: RawData) -> VaultNote:
        """Transform a GitHub event into a VaultNote."""
        event_type = raw_data.metadata.get("event_type", "unknown")
        repo = raw_data.metadata.get("repo", "")
        payload = raw_data.payload

        if event_type == "pull_request":
            return self._transform_pr(raw_data, payload, repo)
        elif event_type == "push":
            return self._transform_push(raw_data, payload, repo)
        elif event_type == "deployment":
            return self._transform_deployment(raw_data, payload, repo)
        elif event_type == "release":
            return self._transform_release(raw_data, payload, repo)
        elif event_type == "issues":
            return self._transform_issue(raw_data, payload, repo)
        else:
            return self._transform_generic(raw_data, payload, repo, event_type)

    def _transform_pr(
        self, raw: RawData, payload: dict, repo: str
    ) -> VaultNote:
        pr = payload.get("pull_request", {})
        action = payload.get("action", "unknown")
        number = pr.get("number", "?")
        title = pr.get("title", "Untitled PR")
        author = pr.get("user", {}).get("login", "unknown")
        body_text = pr.get("body", "") or ""
        state = pr.get("state", "unknown")
        merged = pr.get("merged", False)
        base = pr.get("base", {}).get("ref", "?")
        head = pr.get("head", {}).get("ref", "?")
        url = pr.get("html_url", "")
        additions = pr.get("additions", 0)
        deletions = pr.get("deletions", 0)
        changed_files = pr.get("changed_files", 0)

        status_label = "merged" if merged else state

        note_body = f"""## PR #{number}: {title}

**Repository:** {repo}
**Author:** @{author}
**Action:** {action}
**Status:** {status_label}
**Branch:** `{head}` -> `{base}`
**Changes:** +{additions} -{deletions} across {changed_files} files

{f"**URL:** [{url}]({url})" if url else ""}

### Description

{body_text[:2000] if body_text else "(no description)"}
"""

        tags = ["github", "pull-request", action]
        if merged:
            tags.append("merged")

        return VaultNote(
            title=f"PR #{number}: {title} ({repo})",
            body=note_body,
            source_connector=self.id,
            source_type=self.type,
            source_id=f"pr-{repo}-{number}-{action}",
            trust_level=self.trust_level,
            landing_zone=self.landing_zone,
            tags=tags,
            category="pull-request",
            author=author,
            source_url=url,
        )

    def _transform_push(
        self, raw: RawData, payload: dict, repo: str
    ) -> VaultNote:
        ref = payload.get("ref", "unknown")
        branch = ref.replace("refs/heads/", "")
        commits = payload.get("commits", [])
        pusher = payload.get("pusher", {}).get("name", "unknown")
        compare = payload.get("compare", "")

        commit_lines = []
        for c in commits[:20]:
            sha = c.get("id", "")[:7]
            msg = c.get("message", "").split("\n")[0][:80]
            commit_lines.append(f"- `{sha}` {msg}")

        note_body = f"""## Push to {repo}

**Branch:** `{branch}`
**Pusher:** @{pusher}
**Commits:** {len(commits)}
{f"**Compare:** [{compare}]({compare})" if compare else ""}

### Commits

{chr(10).join(commit_lines) if commit_lines else "(no commits)"}
"""

        return VaultNote(
            title=f"Push: {branch} ({repo}) - {len(commits)} commits",
            body=note_body,
            source_connector=self.id,
            source_type=self.type,
            source_id=f"push-{repo}-{branch}-{len(commits)}",
            trust_level=self.trust_level,
            landing_zone=self.landing_zone,
            tags=["github", "push", branch],
            category="push",
            author=pusher,
            source_url=compare,
        )

    def _transform_deployment(
        self, raw: RawData, payload: dict, repo: str
    ) -> VaultNote:
        deployment = payload.get("deployment", {})
        env = deployment.get("environment", "unknown")
        ref = deployment.get("ref", "unknown")
        creator = deployment.get("creator", {}).get("login", "unknown")
        desc = deployment.get("description", "") or ""

        note_body = f"""## Deployment: {repo}

**Environment:** {env}
**Ref:** `{ref}`
**Creator:** @{creator}
**Description:** {desc or "(none)"}
"""

        return VaultNote(
            title=f"Deploy: {repo} -> {env}",
            body=note_body,
            source_connector=self.id,
            source_type=self.type,
            source_id=f"deploy-{repo}-{env}-{ref}",
            trust_level=self.trust_level,
            landing_zone=self.landing_zone,
            tags=["github", "deployment", env],
            category="deployment",
            author=creator,
        )

    def _transform_release(
        self, raw: RawData, payload: dict, repo: str
    ) -> VaultNote:
        release = payload.get("release", {})
        tag = release.get("tag_name", "unknown")
        name = release.get("name", tag)
        author = release.get("author", {}).get("login", "unknown")
        body_text = release.get("body", "") or ""
        url = release.get("html_url", "")
        prerelease = release.get("prerelease", False)

        note_body = f"""## Release: {name}

**Repository:** {repo}
**Tag:** `{tag}`
**Author:** @{author}
**Pre-release:** {"yes" if prerelease else "no"}
{f"**URL:** [{url}]({url})" if url else ""}

### Release Notes

{body_text[:3000] if body_text else "(no release notes)"}
"""

        return VaultNote(
            title=f"Release: {name} ({repo})",
            body=note_body,
            source_connector=self.id,
            source_type=self.type,
            source_id=f"release-{repo}-{tag}",
            trust_level=self.trust_level,
            landing_zone=self.landing_zone,
            tags=["github", "release", tag],
            category="release",
            author=author,
            source_url=url,
        )

    def _transform_issue(
        self, raw: RawData, payload: dict, repo: str
    ) -> VaultNote:
        issue = payload.get("issue", {})
        action = payload.get("action", "unknown")
        number = issue.get("number", "?")
        title = issue.get("title", "Untitled")
        author = issue.get("user", {}).get("login", "unknown")
        body_text = issue.get("body", "") or ""
        labels = [lb.get("name", "") for lb in issue.get("labels", [])]
        url = issue.get("html_url", "")

        note_body = f"""## Issue #{number}: {title}

**Repository:** {repo}
**Author:** @{author}
**Action:** {action}
**Labels:** {", ".join(labels) if labels else "(none)"}
{f"**URL:** [{url}]({url})" if url else ""}

### Description

{body_text[:2000] if body_text else "(no description)"}
"""

        return VaultNote(
            title=f"Issue #{number}: {title} ({repo})",
            body=note_body,
            source_connector=self.id,
            source_type=self.type,
            source_id=f"issue-{repo}-{number}-{action}",
            trust_level=self.trust_level,
            landing_zone=self.landing_zone,
            tags=["github", "issue", action] + labels,
            category="issue",
            author=author,
            source_url=url,
        )

    def _transform_generic(
        self, raw: RawData, payload: dict, repo: str, event_type: str
    ) -> VaultNote:
        return VaultNote(
            title=f"GitHub: {event_type} ({repo})",
            body=f"## {event_type}\n\n```json\n{json.dumps(payload, indent=2, default=str)[:3000]}\n```",
            source_connector=self.id,
            source_type=self.type,
            source_id=raw.source_id,
            trust_level=self.trust_level,
            landing_zone=self.landing_zone,
            tags=["github", event_type],
            category=event_type,
        )

    def health_check(self) -> ConnectorStatus:
        status = self.base_status(healthy=bool(self._webhook_secret))
        status.extra["repos"] = self._repos
        status.extra["events"] = list(self._events)
        status.extra["processed_deliveries"] = len(self._processed_deliveries)
        return status
```

### Step 7.2: Write tests for GitHub connector

- [ ] Write `plugin/lib/connectors/tests/test_github.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/tests/test_github.py`

```python
"""Tests for GitHub connector."""

import hashlib
import hmac as hmac_mod
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from lib.connectors.github import GithubConnector


def _make_connector(**overrides):
    cfg = {
        "id": "github-test",
        "type": "github",
        "trust_level": "verified",
        "mode": "push",
        "landing_zone": "queue-cicd",
        "config": {
            "webhook_secret": "gh-secret-123",
            "repos": ["easy-labs/easy-api"],
            "events": ["pull_request", "push", "deployment", "release"],
            **overrides,
        },
    }
    return GithubConnector(cfg)


class TestGitHubAuth:
    def test_authenticate_with_secret(self):
        conn = _make_connector()
        assert conn.authenticate() is True

    def test_authenticate_without_secret(self):
        conn = _make_connector(webhook_secret="")
        assert conn.authenticate() is False


class TestGitHubWebhookVerification:
    def test_valid_signature(self):
        conn = _make_connector()
        body = b'{"action": "opened"}'
        sig = "sha256=" + hmac_mod.new(b"gh-secret-123", body, hashlib.sha256).hexdigest()
        assert conn.verify_webhook(body, sig) is True

    def test_invalid_signature(self):
        conn = _make_connector()
        assert conn.verify_webhook(b"body", "sha256=invalid") is False


class TestGitHubReceive:
    def test_accept_allowed_repo(self):
        conn = _make_connector()
        raw = conn.receive({
            "_event_type": "pull_request",
            "_delivery_id": "d1",
            "repository": {"full_name": "easy-labs/easy-api"},
            "sender": {"login": "andrew"},
        })
        assert raw.source_id.startswith("pull_request")

    def test_reject_disallowed_repo(self):
        conn = _make_connector()
        with pytest.raises(ValueError, match="not in allowlist"):
            conn.receive({
                "_event_type": "pull_request",
                "_delivery_id": "d2",
                "repository": {"full_name": "hacker/evil-repo"},
                "sender": {"login": "hacker"},
            })

    def test_reject_disallowed_event(self):
        conn = _make_connector(events=["push"])
        with pytest.raises(ValueError, match="not in accepted events"):
            conn.receive({
                "_event_type": "issues",
                "_delivery_id": "d3",
                "repository": {"full_name": "easy-labs/easy-api"},
                "sender": {"login": "andrew"},
            })

    def test_deduplicate_delivery(self):
        conn = _make_connector()
        payload = {
            "_event_type": "push",
            "_delivery_id": "dup-1",
            "repository": {"full_name": "easy-labs/easy-api"},
            "sender": {"login": "andrew"},
        }
        conn.receive(payload)
        with pytest.raises(ValueError, match="Duplicate"):
            conn.receive(payload)


class TestGitHubTransformPR:
    def test_pr_opened(self):
        conn = _make_connector()
        raw = conn.receive({
            "_event_type": "pull_request",
            "_delivery_id": "pr-1",
            "action": "opened",
            "repository": {"full_name": "easy-labs/easy-api"},
            "sender": {"login": "andrew"},
            "pull_request": {
                "number": 42,
                "title": "feat: add treasury send",
                "user": {"login": "andrew"},
                "body": "Implements the treasury send flow.",
                "state": "open",
                "merged": False,
                "base": {"ref": "main"},
                "head": {"ref": "feat/treasury-send"},
                "html_url": "https://github.com/easy-labs/easy-api/pull/42",
                "additions": 150,
                "deletions": 20,
                "changed_files": 5,
            },
        })
        note = conn.transform(raw)
        assert "PR #42" in note.title
        assert "treasury send" in note.title
        assert note.author == "andrew"
        assert "pull-request" in note.tags
        assert note.source_url == "https://github.com/easy-labs/easy-api/pull/42"

    def test_pr_merged(self):
        conn = _make_connector()
        raw = conn.receive({
            "_event_type": "pull_request",
            "_delivery_id": "pr-2",
            "action": "closed",
            "repository": {"full_name": "easy-labs/easy-api"},
            "sender": {"login": "andrew"},
            "pull_request": {
                "number": 42,
                "title": "feat: merged",
                "user": {"login": "andrew"},
                "state": "closed",
                "merged": True,
                "base": {"ref": "main"},
                "head": {"ref": "feat/x"},
                "html_url": "",
            },
        })
        note = conn.transform(raw)
        assert "merged" in note.tags


class TestGitHubTransformPush:
    def test_push_event(self):
        conn = _make_connector()
        raw = conn.receive({
            "_event_type": "push",
            "_delivery_id": "push-1",
            "ref": "refs/heads/main",
            "repository": {"full_name": "easy-labs/easy-api"},
            "sender": {"login": "andrew"},
            "pusher": {"name": "andrew"},
            "commits": [
                {"id": "abc1234567890", "message": "fix: handle timeout"},
                {"id": "def1234567890", "message": "test: add timeout tests"},
            ],
            "compare": "https://github.com/easy-labs/easy-api/compare/abc...def",
        })
        note = conn.transform(raw)
        assert "Push" in note.title
        assert "2 commits" in note.title
        assert "abc1234" in note.body
        assert "timeout" in note.body


class TestGitHubHealth:
    def test_health_with_secret(self):
        conn = _make_connector()
        conn.start()
        status = conn.health_check()
        assert status.healthy is True
        assert "easy-labs/easy-api" in status.extra["repos"]
```

**Test:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/lib/connectors/tests/test_github.py -v
```

**Commit:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && git add plugin/lib/connectors/github.py plugin/lib/connectors/tests/test_github.py && git commit -m "$(cat <<'EOF'
feat: add GitHub connector with webhook verification and PR/push/deploy transforms

Handles pull_request, push, deployment, release, and issues events.
Verifies HMAC-SHA256 webhook signatures. Filters by repo and event
allowlists. Deduplicates by delivery ID. Structured note output with
PR metadata, commit lists, and deployment details.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Slack connector (first-party)

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/slack.py`

**What:** Handle Slack events (messages, reactions). Filter by channel and user allowlists. Support reaction-based bookmarking (e.g., a message with 2+ reactions gets ingested). Parse threads into single notes.

### Step 8.1: Write the Slack connector

- [ ] Write `plugin/lib/connectors/slack.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/slack.py`

```python
"""
Slack connector (Tier 2 -- First-party).

Handles Slack events: messages, reaction_added. Filters by channel and
user allowlists. Supports reaction-based bookmarking (min_reactions
threshold) and thread extraction.

Config keys:
  - bot_token: Slack bot OAuth token
  - channels: list of channel names or IDs to monitor
  - user_allowlist: list of Slack user IDs to accept (empty = accept all users)
  - events: list of event types (default: ["message", "reaction_added"])
  - min_reactions: minimum reactions on a message to auto-ingest (default: 2)
  - bookmark_reactions: list of reaction names that trigger ingestion (e.g. ["brain", "bookmark"])
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any, Optional

from .base import Connector, ConnectorStatus, RawData, VaultNote
from .trust import TrustVerifier, TrustDecision


class SlackConnector(Connector):
    """Receive and process Slack events."""

    type = "slack"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._bot_token: str = self.connector_config.get("bot_token", "")
        self._channels: list[str] = self.connector_config.get("channels", [])
        self._user_allowlist: list[str] = self.connector_config.get("user_allowlist", [])
        self._events: set[str] = set(
            self.connector_config.get("events", ["message", "reaction_added"])
        )
        self._min_reactions: int = self.connector_config.get("min_reactions", 2)
        self._bookmark_reactions: list[str] = self.connector_config.get(
            "bookmark_reactions", ["brain", "bookmark", "star"]
        )
        self._channel_name_cache: dict[str, str] = {}  # id -> name
        self._user_name_cache: dict[str, str] = {}  # id -> display_name
        self._trust_verifier = TrustVerifier.from_connector_config(self.connector_config)

    def authenticate(self) -> bool:
        """Verify bot token by calling auth.test."""
        if not self._bot_token:
            return False
        try:
            result = self._slack_api("auth.test")
            return result.get("ok", False)
        except Exception:
            return False

    def _slack_api(self, method: str, data: Optional[dict] = None) -> dict:
        """Call a Slack API method."""
        url = f"https://slack.com/api/{method}"
        headers = {
            "Authorization": f"Bearer {self._bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    def _resolve_channel_name(self, channel_id: str) -> str:
        """Get channel name from ID, with caching."""
        if channel_id in self._channel_name_cache:
            return self._channel_name_cache[channel_id]
        try:
            result = self._slack_api("conversations.info", {"channel": channel_id})
            name = result.get("channel", {}).get("name", channel_id)
            self._channel_name_cache[channel_id] = name
            return name
        except Exception:
            return channel_id

    def _resolve_user_name(self, user_id: str) -> str:
        """Get user display name from ID, with caching."""
        if user_id in self._user_name_cache:
            return self._user_name_cache[user_id]
        try:
            result = self._slack_api("users.info", {"user": user_id})
            profile = result.get("user", {}).get("profile", {})
            name = profile.get("display_name") or profile.get("real_name") or user_id
            self._user_name_cache[user_id] = name
            return name
        except Exception:
            return user_id

    def receive(self, payload: dict[str, Any]) -> RawData:
        """Accept a Slack event payload."""
        event = payload.get("event", payload)
        event_type = event.get("type", "unknown")

        if event_type not in self._events:
            raise ValueError(f"Event type {event_type} not accepted")

        # Channel filter
        channel = event.get("channel", "")
        if self._channels:
            channel_name = self._resolve_channel_name(channel) if channel else ""
            if channel not in self._channels and channel_name not in self._channels:
                raise ValueError(f"Channel {channel} ({channel_name}) not in allowlist")

        # User filter
        user = event.get("user", "")
        if self._user_allowlist and user not in self._user_allowlist:
            raise ValueError(f"User {user} not in allowlist")

        # For reaction events, check the reaction name and count
        if event_type == "reaction_added":
            reaction = event.get("reaction", "")
            if reaction not in self._bookmark_reactions:
                raise ValueError(f"Reaction {reaction} not a bookmark reaction")

        ts = event.get("ts", event.get("event_ts", ""))
        source_id = f"slack-{channel}-{ts}"

        return RawData(
            source_id=source_id,
            payload=event,
            sender=user,
            metadata={
                "event_type": event_type,
                "channel": channel,
                "ts": ts,
            },
        )

    def pull(self) -> list[RawData]:
        """
        Pull recent messages from configured channels.

        Fetches messages with >= min_reactions and messages with bookmark reactions.
        """
        results: list[RawData] = []

        for channel in self._channels:
            try:
                resp = self._slack_api("conversations.history", {
                    "channel": channel,
                    "limit": 50,
                })
                if not resp.get("ok"):
                    continue

                for msg in resp.get("messages", []):
                    # Check reaction threshold
                    reactions = msg.get("reactions", [])
                    total_reactions = sum(r.get("count", 0) for r in reactions)
                    has_bookmark = any(
                        r.get("name", "") in self._bookmark_reactions
                        for r in reactions
                    )

                    if total_reactions >= self._min_reactions or has_bookmark:
                        user = msg.get("user", "")
                        if self._user_allowlist and user not in self._user_allowlist:
                            continue

                        ts = msg.get("ts", "")
                        results.append(RawData(
                            source_id=f"slack-{channel}-{ts}",
                            payload=msg,
                            sender=user,
                            metadata={
                                "event_type": "message",
                                "channel": channel,
                                "ts": ts,
                            },
                        ))
            except Exception as exc:
                self.record_error(f"Pull failed for channel {channel}: {exc}")

        return results

    def transform(self, raw_data: RawData) -> VaultNote:
        """Transform a Slack event into a VaultNote."""
        event = raw_data.payload
        event_type = raw_data.metadata.get("event_type", "message")
        channel = raw_data.metadata.get("channel", "")
        channel_name = self._resolve_channel_name(channel) if channel else "unknown"
        user = raw_data.sender
        user_name = self._resolve_user_name(user) if user else "unknown"

        if event_type == "reaction_added":
            return self._transform_reaction(raw_data, event, channel_name, user_name)
        else:
            return self._transform_message(raw_data, event, channel_name, user_name)

    def _transform_message(
        self, raw: RawData, event: dict, channel_name: str, user_name: str
    ) -> VaultNote:
        text = event.get("text", "")
        ts = event.get("ts", "")
        thread_ts = event.get("thread_ts", "")

        # Build title from first line of message
        first_line = text.split("\n")[0][:60] if text else "(empty message)"

        note_body = f"""## Slack Message

**Channel:** #{channel_name}
**Author:** {user_name}
**Timestamp:** {ts}
{f"**Thread:** {thread_ts}" if thread_ts else ""}

### Content

{text}
"""

        reactions = event.get("reactions", [])
        if reactions:
            reaction_lines = [
                f"- :{r.get('name', '?')}: x{r.get('count', 0)}"
                for r in reactions
            ]
            note_body += f"\n### Reactions\n\n" + "\n".join(reaction_lines)

        tags = ["slack", f"channel-{channel_name}"]

        return VaultNote(
            title=f"Slack: {first_line} (#{channel_name})",
            body=note_body,
            source_connector=self.id,
            source_type=self.type,
            source_id=raw.source_id,
            trust_level=self.trust_level,
            landing_zone=self.landing_zone,
            tags=tags,
            category="slack-message",
            author=user_name,
        )

    def _transform_reaction(
        self, raw: RawData, event: dict, channel_name: str, user_name: str
    ) -> VaultNote:
        reaction = event.get("reaction", "?")
        item = event.get("item", {})
        item_ts = item.get("ts", "")
        item_channel = item.get("channel", "")

        note_body = f"""## Slack Bookmark

**Reaction:** :{reaction}:
**By:** {user_name}
**Channel:** #{channel_name}
**Message timestamp:** {item_ts}

(Original message content would be fetched via conversations.history)
"""

        return VaultNote(
            title=f"Slack Bookmark: :{reaction}: in #{channel_name}",
            body=note_body,
            source_connector=self.id,
            source_type=self.type,
            source_id=raw.source_id,
            trust_level=self.trust_level,
            landing_zone=self.landing_zone,
            tags=["slack", "bookmark", reaction],
            category="slack-bookmark",
            author=user_name,
        )

    def health_check(self) -> ConnectorStatus:
        healthy = bool(self._bot_token)
        status = self.base_status(healthy=healthy)
        status.extra["channels"] = self._channels
        status.extra["user_allowlist_count"] = len(self._user_allowlist)
        status.extra["events"] = list(self._events)
        return status
```

### Step 8.2: Write tests for Slack connector

- [ ] Write `plugin/lib/connectors/tests/test_slack.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/tests/test_slack.py`

```python
"""Tests for Slack connector."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from lib.connectors.slack import SlackConnector
from lib.connectors.base import RawData


def _make_connector(**overrides):
    cfg = {
        "id": "slack-test",
        "type": "slack",
        "trust_level": "medium",
        "mode": "both",
        "landing_zone": "queue-human",
        "config": {
            "bot_token": "xoxb-test-token",
            "channels": ["C123ENGINEERING", "engineering"],
            "user_allowlist": ["U01ABC123"],
            "events": ["message", "reaction_added"],
            "min_reactions": 2,
            "bookmark_reactions": ["brain", "bookmark"],
            **overrides,
        },
    }
    return SlackConnector(cfg)


class TestSlackAuth:
    @patch.object(SlackConnector, "_slack_api")
    def test_authenticate_success(self, mock_api):
        mock_api.return_value = {"ok": True, "user_id": "U01"}
        conn = _make_connector()
        assert conn.authenticate() is True

    @patch.object(SlackConnector, "_slack_api")
    def test_authenticate_failure(self, mock_api):
        mock_api.return_value = {"ok": False, "error": "invalid_auth"}
        conn = _make_connector()
        assert conn.authenticate() is False

    def test_authenticate_no_token(self):
        conn = _make_connector(bot_token="")
        assert conn.authenticate() is False


class TestSlackReceive:
    def test_accept_message_from_allowed_user(self):
        conn = _make_connector()
        raw = conn.receive({
            "event": {
                "type": "message",
                "channel": "C123ENGINEERING",
                "user": "U01ABC123",
                "text": "Important architecture note",
                "ts": "1234567890.123456",
            }
        })
        assert raw.sender == "U01ABC123"

    def test_reject_message_from_disallowed_user(self):
        conn = _make_connector()
        with pytest.raises(ValueError, match="not in allowlist"):
            conn.receive({
                "event": {
                    "type": "message",
                    "channel": "C123ENGINEERING",
                    "user": "U99HACKER",
                    "text": "spam",
                    "ts": "1234567890.999",
                }
            })

    def test_reject_disallowed_channel(self):
        conn = _make_connector()
        with pytest.raises(ValueError, match="not in allowlist"):
            conn.receive({
                "event": {
                    "type": "message",
                    "channel": "C999RANDOM",
                    "user": "U01ABC123",
                    "text": "test",
                    "ts": "1234567890.111",
                }
            })

    def test_reject_non_bookmark_reaction(self):
        conn = _make_connector()
        with pytest.raises(ValueError, match="not a bookmark"):
            conn.receive({
                "event": {
                    "type": "reaction_added",
                    "channel": "C123ENGINEERING",
                    "user": "U01ABC123",
                    "reaction": "thumbsup",
                    "ts": "1234567890.222",
                }
            })

    def test_accept_bookmark_reaction(self):
        conn = _make_connector()
        raw = conn.receive({
            "event": {
                "type": "reaction_added",
                "channel": "C123ENGINEERING",
                "user": "U01ABC123",
                "reaction": "brain",
                "ts": "1234567890.333",
                "item": {"type": "message", "channel": "C123ENGINEERING", "ts": "111.222"},
            }
        })
        assert "brain" in raw.payload.get("reaction", "")


class TestSlackTransform:
    def test_transform_message(self):
        conn = _make_connector()
        conn._channel_name_cache["C123"] = "engineering"
        conn._user_name_cache["U01"] = "Andrew"
        raw = RawData(
            source_id="slack-C123-1234",
            payload={
                "type": "message",
                "text": "We should use event sourcing for the treasury module.",
                "user": "U01",
                "ts": "1234567890.123",
                "reactions": [{"name": "brain", "count": 3}],
            },
            sender="U01",
            metadata={"event_type": "message", "channel": "C123", "ts": "1234567890.123"},
        )
        note = conn.transform(raw)
        assert "event sourcing" in note.body
        assert "engineering" in note.title or "engineering" in note.body
        assert note.source_connector == "slack-test"

    def test_transform_reaction(self):
        conn = _make_connector()
        conn._channel_name_cache["C123"] = "engineering"
        conn._user_name_cache["U01"] = "Andrew"
        raw = RawData(
            source_id="slack-C123-1234",
            payload={
                "type": "reaction_added",
                "reaction": "brain",
                "user": "U01",
                "item": {"channel": "C123", "ts": "1111.2222"},
            },
            sender="U01",
            metadata={"event_type": "reaction_added", "channel": "C123", "ts": "1234"},
        )
        note = conn.transform(raw)
        assert "Bookmark" in note.title
        assert ":brain:" in note.body


class TestSlackHealth:
    def test_health_check(self):
        conn = _make_connector()
        conn.start()
        status = conn.health_check()
        assert status.healthy is True
        assert len(status.extra["channels"]) == 2
```

**Test:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/lib/connectors/tests/test_slack.py -v
```

**Commit:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && git add plugin/lib/connectors/slack.py plugin/lib/connectors/tests/test_slack.py && git commit -m "$(cat <<'EOF'
feat: add Slack connector with channel/user filtering and reaction bookmarking

Handles message and reaction_added events. Filters by channel and user
allowlists. Reaction-based bookmarking with configurable reactions and
min_reactions threshold. Pull mode fetches highly-reacted messages.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Email connector (first-party)

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/email.py`

**What:** Poll email inbox via IMAP with per-sender routing and trust overrides. Support gog (Gmail OAuth) for authentication. Filter by folder, sender, and subject. Transform emails into vault notes with metadata.

### Step 9.1: Write the email connector

- [ ] Write `plugin/lib/connectors/email.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/email.py`

```python
"""
Email connector (Tier 2 -- First-party).

Polls email inbox via IMAP or gog (Gmail OAuth). Filters by folder,
sender, and subject. Per-sender routing and trust overrides.

Config keys:
  - provider: "imap" or "gog" (Gmail OAuth via gog utility)
  - imap_host: IMAP server hostname (for imap provider)
  - imap_port: IMAP port (default: 993)
  - username: IMAP username
  - password: IMAP password (use ${ENV_VAR} reference)
  - folders: list of IMAP folders to monitor (default: ["INBOX"])
  - poll_interval_minutes: how often to poll (default: 15)
  - sender_policy: "allowlist" | "domain" | "open"
  - sender_allowlist: list of sender addresses or dicts with trust overrides
  - subject_filters: list of subject patterns to match (optional, regex)
  - max_body_length: max email body characters to include (default: 4000)
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import re
import subprocess
import shutil
from datetime import datetime, timezone
from typing import Any, Optional

from .base import Connector, ConnectorStatus, RawData, VaultNote
from .trust import TrustVerifier, TrustDecision


class EmailConnector(Connector):
    """Poll email inbox and transform messages into vault notes."""

    type = "email"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._provider: str = self.connector_config.get("provider", "imap")
        self._imap_host: str = self.connector_config.get("imap_host", "")
        self._imap_port: int = self.connector_config.get("imap_port", 993)
        self._username: str = self.connector_config.get("username", "")
        self._password: str = self.connector_config.get("password", "")
        self._folders: list[str] = self.connector_config.get("folders", ["INBOX"])
        self._poll_interval: int = self.connector_config.get("poll_interval_minutes", 15)
        self._subject_filters: list[str] = self.connector_config.get("subject_filters", [])
        self._max_body_length: int = self.connector_config.get("max_body_length", 4000)
        self._trust_verifier = TrustVerifier.from_connector_config(self.connector_config)
        self._seen_message_ids: set[str] = set()
        self._imap: Optional[imaplib.IMAP4_SSL] = None

    def authenticate(self) -> bool:
        """Connect to IMAP server or verify gog is available."""
        if self._provider == "gog":
            return self._authenticate_gog()
        else:
            return self._authenticate_imap()

    def _authenticate_imap(self) -> bool:
        """Connect to IMAP server with credentials."""
        if not self._imap_host or not self._username:
            return False
        try:
            self._imap = imaplib.IMAP4_SSL(self._imap_host, self._imap_port)
            self._imap.login(self._username, self._password)
            return True
        except Exception as exc:
            self.record_error(f"IMAP auth failed: {exc}")
            return False

    def _authenticate_gog(self) -> bool:
        """Verify gog (Gmail OAuth) utility is available."""
        if not shutil.which("gog"):
            self.record_error("gog utility not found in PATH")
            return False
        try:
            result = subprocess.run(
                ["gog", "check"],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0
        except Exception as exc:
            self.record_error(f"gog check failed: {exc}")
            return False

    def pull(self) -> list[RawData]:
        """Fetch unread messages from configured folders."""
        results: list[RawData] = []

        for folder in self._folders:
            try:
                messages = self._fetch_from_folder(folder)
                results.extend(messages)
            except Exception as exc:
                self.record_error(f"Fetch failed for folder {folder}: {exc}")

        return results

    def _fetch_from_folder(self, folder: str) -> list[RawData]:
        """Fetch messages from a single IMAP folder."""
        results: list[RawData] = []

        if self._provider == "gog":
            return self._fetch_via_gog(folder)

        if self._imap is None:
            return results

        try:
            self._imap.select(folder, readonly=True)
            _, data = self._imap.search(None, "UNSEEN")
            if not data or not data[0]:
                return results

            msg_nums = data[0].split()
            for num in msg_nums[-50:]:  # limit to 50 most recent
                _, msg_data = self._imap.fetch(num, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue

                raw_email = msg_data[0][1]
                if isinstance(raw_email, bytes):
                    msg = email.message_from_bytes(raw_email)
                else:
                    msg = email.message_from_string(raw_email)

                raw = self._parse_email(msg, folder)
                if raw is not None:
                    results.append(raw)

        except Exception as exc:
            self.record_error(f"IMAP fetch error in {folder}: {exc}")

        return results

    def _fetch_via_gog(self, folder: str) -> list[RawData]:
        """Fetch messages using gog utility (Gmail OAuth)."""
        results: list[RawData] = []
        try:
            result = subprocess.run(
                ["gog", "fetch", "--folder", folder, "--format", "json", "--limit", "50"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                self.record_error(f"gog fetch failed: {result.stderr}")
                return results

            import json
            messages = json.loads(result.stdout)
            for msg_data in messages:
                message_id = msg_data.get("message_id", "")
                if message_id in self._seen_message_ids:
                    continue
                self._seen_message_ids.add(message_id)

                sender = msg_data.get("from", "")
                subject = msg_data.get("subject", "")
                body = msg_data.get("body", "")
                date = msg_data.get("date", "")

                # Sender verification
                verdict = self._trust_verifier.check_sender(sender)
                if verdict.decision == TrustDecision.REJECT:
                    continue

                # Subject filter
                if not self._matches_subject(subject):
                    continue

                results.append(RawData(
                    source_id=message_id or f"gog-{folder}-{date}",
                    payload={
                        "from": sender,
                        "subject": subject,
                        "body": body[:self._max_body_length],
                        "date": date,
                        "folder": folder,
                        "message_id": message_id,
                    },
                    sender=sender,
                    metadata={
                        "folder": folder,
                        "trust_override": verdict.trust_override,
                        "landing_zone_override": verdict.landing_zone_override,
                    },
                ))

        except Exception as exc:
            self.record_error(f"gog fetch error: {exc}")

        return results

    def _parse_email(self, msg: email.message.Message, folder: str) -> Optional[RawData]:
        """Parse a single email.message.Message into RawData."""
        message_id = msg.get("Message-ID", "")
        if message_id in self._seen_message_ids:
            return None
        self._seen_message_ids.add(message_id)

        # Decode sender
        from_raw = msg.get("From", "")
        sender_name, sender_addr = email.utils.parseaddr(from_raw)

        # Sender verification
        verdict = self._trust_verifier.check_sender(sender_addr)
        if verdict.decision == TrustDecision.REJECT:
            return None

        # Decode subject
        subject_raw = msg.get("Subject", "")
        decoded_parts = email.header.decode_header(subject_raw)
        subject = ""
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                subject += part.decode(charset or "utf-8", errors="replace")
            else:
                subject += str(part)

        # Subject filter
        if not self._matches_subject(subject):
            return None

        # Extract body
        body = self._extract_body(msg)

        date = msg.get("Date", "")

        return RawData(
            source_id=message_id or f"email-{folder}-{date}",
            payload={
                "from": sender_addr,
                "from_name": sender_name,
                "subject": subject,
                "body": body[:self._max_body_length],
                "date": date,
                "folder": folder,
                "message_id": message_id,
            },
            sender=sender_addr,
            metadata={
                "folder": folder,
                "trust_override": verdict.trust_override,
                "landing_zone_override": verdict.landing_zone_override,
            },
        )

    def _extract_body(self, msg: email.message.Message) -> str:
        """Extract text body from email message."""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        return payload.decode(charset, errors="replace")
            # Fallback to HTML
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        html = payload.decode(charset, errors="replace")
                        # Strip HTML tags (basic)
                        return re.sub(r"<[^>]+>", "", html)
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
        return ""

    def _matches_subject(self, subject: str) -> bool:
        """Check if subject matches any configured filter patterns."""
        if not self._subject_filters:
            return True
        for pattern in self._subject_filters:
            if re.search(pattern, subject, re.IGNORECASE):
                return True
        return False

    def transform(self, raw_data: RawData) -> VaultNote:
        """Transform an email into a VaultNote."""
        p = raw_data.payload
        sender = p.get("from", "unknown")
        sender_name = p.get("from_name", sender)
        subject = p.get("subject", "(no subject)")
        body = p.get("body", "")
        date = p.get("date", "")
        folder = p.get("folder", "INBOX")

        # Apply trust/landing zone overrides from sender verification
        trust_override = raw_data.metadata.get("trust_override")
        lz_override = raw_data.metadata.get("landing_zone_override")

        note_body = f"""## Email: {subject}

**From:** {sender_name} <{sender}>
**Date:** {date}
**Folder:** {folder}

### Content

{body}
"""

        trust = trust_override or self.trust_level
        landing = lz_override or self.landing_zone

        return VaultNote(
            title=f"Email: {subject}",
            body=note_body,
            source_connector=self.id,
            source_type=self.type,
            source_id=raw_data.source_id,
            trust_level=trust,
            landing_zone=landing,
            tags=["email", f"folder-{folder.replace('/', '-')}"],
            category="email",
            author=f"{sender_name} <{sender}>",
        )

    def health_check(self) -> ConnectorStatus:
        healthy = True
        if self._provider == "imap":
            healthy = self._imap is not None
        elif self._provider == "gog":
            healthy = bool(shutil.which("gog"))

        status = self.base_status(healthy=healthy)
        status.extra["provider"] = self._provider
        status.extra["folders"] = self._folders
        status.extra["seen_messages"] = len(self._seen_message_ids)
        return status
```

### Step 9.2: Write tests for email connector

- [ ] Write `plugin/lib/connectors/tests/test_email.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/tests/test_email.py`

```python
"""Tests for email connector."""

from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from lib.connectors.email import EmailConnector
from lib.connectors.base import RawData


def _make_connector(**overrides):
    cfg = {
        "id": "email-test",
        "type": "email",
        "trust_level": "medium",
        "mode": "pull",
        "landing_zone": "queue-human",
        "config": {
            "provider": "imap",
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "username": "test@example.com",
            "password": "secret",
            "folders": ["INBOX"],
            "sender_policy": "allowlist",
            "sender_allowlist": [
                {"address": "andrew@easylabs.io", "trust_override": "high"},
                "niko@easylabs.io",
            ],
            **overrides,
        },
    }
    return EmailConnector(cfg)


class TestEmailAuth:
    def test_gog_auth_no_binary(self):
        conn = _make_connector(provider="gog")
        with patch("shutil.which", return_value=None):
            assert conn.authenticate() is False


class TestEmailParsing:
    def test_parse_allowed_sender(self):
        conn = _make_connector()
        msg = EmailMessage()
        msg["From"] = "Andrew <andrew@easylabs.io>"
        msg["Subject"] = "Architecture Update"
        msg["Date"] = "Sat, 21 Mar 2026 10:00:00 -0000"
        msg["Message-ID"] = "<test-1@easylabs.io>"
        msg.set_content("We should adopt event sourcing.")

        raw = conn._parse_email(msg, "INBOX")
        assert raw is not None
        assert raw.payload["from"] == "andrew@easylabs.io"
        assert raw.payload["subject"] == "Architecture Update"
        assert "event sourcing" in raw.payload["body"]

    def test_reject_disallowed_sender(self):
        conn = _make_connector()
        msg = EmailMessage()
        msg["From"] = "hacker@evil.com"
        msg["Subject"] = "Spam"
        msg["Message-ID"] = "<spam-1@evil.com>"
        msg.set_content("Buy now!")

        raw = conn._parse_email(msg, "INBOX")
        assert raw is None

    def test_deduplicate_by_message_id(self):
        conn = _make_connector()
        msg = EmailMessage()
        msg["From"] = "andrew@easylabs.io"
        msg["Subject"] = "Test"
        msg["Message-ID"] = "<dup-1@easylabs.io>"
        msg.set_content("test")

        raw1 = conn._parse_email(msg, "INBOX")
        raw2 = conn._parse_email(msg, "INBOX")
        assert raw1 is not None
        assert raw2 is None

    def test_subject_filter_match(self):
        conn = _make_connector(subject_filters=["Architecture", "Decision"])
        msg = EmailMessage()
        msg["From"] = "andrew@easylabs.io"
        msg["Subject"] = "Architecture Decision: Event Sourcing"
        msg["Message-ID"] = "<filter-1@easylabs.io>"
        msg.set_content("We decided...")

        raw = conn._parse_email(msg, "INBOX")
        assert raw is not None

    def test_subject_filter_no_match(self):
        conn = _make_connector(subject_filters=["Architecture"])
        msg = EmailMessage()
        msg["From"] = "andrew@easylabs.io"
        msg["Subject"] = "Lunch plans"
        msg["Message-ID"] = "<filter-2@easylabs.io>"
        msg.set_content("Pizza?")

        raw = conn._parse_email(msg, "INBOX")
        assert raw is None


class TestEmailTransform:
    def test_transform_with_trust_override(self):
        conn = _make_connector()
        raw = RawData(
            source_id="<t1@easylabs.io>",
            payload={
                "from": "andrew@easylabs.io",
                "from_name": "Andrew",
                "subject": "Treasury Design",
                "body": "Here is the design...",
                "date": "2026-03-21",
                "folder": "INBOX",
                "message_id": "<t1@easylabs.io>",
            },
            sender="andrew@easylabs.io",
            metadata={
                "folder": "INBOX",
                "trust_override": "high",
                "landing_zone_override": None,
            },
        )
        note = conn.transform(raw)
        assert note.title == "Email: Treasury Design"
        assert note.trust_level == "high"
        assert "Andrew" in note.body
        assert note.source_connector == "email-test"

    def test_transform_default_trust(self):
        conn = _make_connector()
        raw = RawData(
            source_id="<t2@easylabs.io>",
            payload={
                "from": "niko@easylabs.io",
                "from_name": "Niko",
                "subject": "Meeting Notes",
                "body": "Notes from today...",
                "date": "2026-03-21",
                "folder": "INBOX",
                "message_id": "<t2@easylabs.io>",
            },
            sender="niko@easylabs.io",
            metadata={"folder": "INBOX", "trust_override": None, "landing_zone_override": None},
        )
        note = conn.transform(raw)
        assert note.trust_level == "medium"


class TestEmailHealth:
    def test_health_check_imap_no_connection(self):
        conn = _make_connector()
        status = conn.health_check()
        assert status.healthy is False  # no IMAP connection established
        assert status.extra["provider"] == "imap"
```

**Test:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/lib/connectors/tests/test_email.py -v
```

**Commit:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && git add plugin/lib/connectors/email.py plugin/lib/connectors/tests/test_email.py && git commit -m "$(cat <<'EOF'
feat: add email connector with IMAP/gog support and per-sender trust

Polls email via IMAP or gog (Gmail OAuth). Filters by folder, sender
allowlist, and subject patterns. Per-sender trust overrides and landing
zone routing. Deduplicates by Message-ID. Extracts text/plain with
HTML fallback.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Connector config schema and CLI

**What:** Define the `config/connectors.json` schema and build the `openclaw-connector` CLI for managing connectors (list, add, remove, test, status).

### Step 10.1: Create the connectors.json template

- [ ] Write `plugin/config/connectors.json.example`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/config/connectors.json.example`

```json
{
  "version": "1.0.0",
  "connectors": [
    {
      "id": "watch-inbox",
      "type": "filesystem",
      "enabled": true,
      "trust_level": "high",
      "mode": "pull",
      "landing_zone": "queue-agent",
      "config": {
        "watch_paths": ["~/.openclaw/data/knowledge/inbox/"],
        "extensions": [".md", ".txt", ".pdf", ".url", ".webloc"],
        "ignore_patterns": ["*.tmp", ".DS_Store", "*.swp"]
      }
    }
  ]
}
```

### Step 10.2: Write the connector CLI

- [ ] Write `plugin/bin/openclaw-connector`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-connector`

```python
#!/usr/bin/env python3
"""
openclaw-connector: CLI for managing connectors in the knowledge graph.

Usage:
  openclaw-connector list                     List all configured connectors
  openclaw-connector types                    List available connector types
  openclaw-connector add <type> <id> [opts]   Add a new connector
  openclaw-connector remove <id>              Remove a connector
  openclaw-connector test <id>                Test a connector's connectivity
  openclaw-connector status                   Show health status of all connectors
  openclaw-connector pull [--id <id>]         Run pull on all (or one) pull-mode connectors
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Add plugin lib to path
PLUGIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_DIR))

from lib.connectors.registry import ConnectorRegistry, CONNECTORS_CONFIG

# ANSI colors
BLUE = "\033[0;34m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
MAGENTA = "\033[0;35m"
DIM = "\033[2m"
BOLD = "\033[1m"
NC = "\033[0m"


def resolve_vault_path() -> str:
    """Determine vault path from environment or config."""
    val = os.environ.get("LACP_OBSIDIAN_VAULT") or os.environ.get("OPENCLAW_VAULT")
    if val:
        return val
    openclaw_home = os.environ.get("OPENCLAW_HOME", os.path.expanduser("~/.openclaw"))
    return os.path.join(openclaw_home, "data", "knowledge")


def cmd_list(args, registry: ConnectorRegistry):
    """List all configured connectors."""
    registry.load_config()
    connectors = registry._config.get("connectors", [])

    if not connectors:
        print(f"  {DIM}No connectors configured.{NC}")
        print(f"  Run: openclaw-connector add <type> <id>")
        return

    print(f"\n{BOLD}Configured Connectors{NC}")
    print("=" * 60)

    for c in connectors:
        enabled = c.get("enabled", True)
        status_icon = f"{GREEN}on{NC}" if enabled else f"{RED}off{NC}"
        trust = c.get("trust_level", "medium")
        mode = c.get("mode", "pull")
        landing = c.get("landing_zone", "queue-human")
        print(
            f"  [{status_icon}] {BOLD}{c['id']}{NC}"
            f"  type={c.get('type', '?')}"
            f"  trust={trust}"
            f"  mode={mode}"
            f"  zone={landing}"
        )

    print(f"\n  Total: {len(connectors)} connector(s)\n")


def cmd_types(args, registry: ConnectorRegistry):
    """List available connector types."""
    types = registry.list_available_types()

    print(f"\n{BOLD}Available Connector Types{NC}")
    print("=" * 60)

    for t in types:
        tier_color = GREEN if t["tier"] == "native" else BLUE if t["tier"] == "first-party" else MAGENTA
        print(f"  {tier_color}[{t['tier']}]{NC} {t['type']}")

    print()


def cmd_add(args, registry: ConnectorRegistry):
    """Add a new connector."""
    registry.load_config()

    entry = {
        "id": args.id,
        "type": args.type,
        "enabled": True,
        "trust_level": args.trust or "medium",
        "mode": args.mode or "pull",
        "landing_zone": args.zone or "queue-human",
        "config": {},
    }

    # Parse extra config from --set key=value pairs
    if args.set:
        for kv in args.set:
            if "=" in kv:
                k, v = kv.split("=", 1)
                # Try to parse as JSON for complex values
                try:
                    entry["config"][k] = json.loads(v)
                except json.JSONDecodeError:
                    entry["config"][k] = v

    try:
        registry.add_connector(entry)
        print(f"{GREEN}[ok]{NC} Added connector: {args.id} (type={args.type})")
        print(f"     Config: {registry.config_path}")
        print(f"     Edit config to add type-specific settings.")
    except ValueError as exc:
        print(f"{RED}[error]{NC} {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_remove(args, registry: ConnectorRegistry):
    """Remove a connector."""
    registry.load_config()
    if registry.remove_connector(args.id):
        print(f"{GREEN}[ok]{NC} Removed connector: {args.id}")
    else:
        print(f"{YELLOW}[warn]{NC} Connector not found: {args.id}")
        sys.exit(1)


def cmd_test(args, registry: ConnectorRegistry):
    """Test a connector's connectivity."""
    loaded = registry.load_all()

    conn = registry.get(args.id)
    if conn is None:
        print(f"{RED}[error]{NC} Connector not found or failed to load: {args.id}")
        sys.exit(1)

    print(f"Testing connector: {args.id} (type={conn.type})...")

    try:
        ok = conn.authenticate()
        if ok:
            print(f"  {GREEN}[ok]{NC} Authentication successful")
        else:
            print(f"  {RED}[fail]{NC} Authentication failed")
            sys.exit(1)
    except Exception as exc:
        print(f"  {RED}[fail]{NC} Authentication error: {exc}")
        sys.exit(1)

    # Try a pull if it's a pull-mode connector
    if conn.mode in ("pull", "both"):
        print(f"  Testing pull...")
        try:
            items = conn.pull()
            print(f"  {GREEN}[ok]{NC} Pull returned {len(items)} item(s)")
        except Exception as exc:
            print(f"  {YELLOW}[warn]{NC} Pull error: {exc}")

    # Health check
    try:
        status = conn.health_check()
        health_icon = f"{GREEN}healthy{NC}" if status.healthy else f"{RED}unhealthy{NC}"
        print(f"  Health: {health_icon}")
    except Exception as exc:
        print(f"  {YELLOW}[warn]{NC} Health check error: {exc}")

    print()


def cmd_status(args, registry: ConnectorRegistry):
    """Show health status of all connectors."""
    loaded = registry.load_all()
    started = registry.start_all()

    statuses = registry.status_all()

    if not statuses:
        print(f"  {DIM}No connectors loaded.{NC}")
        return

    print(f"\n{BOLD}Connector Status{NC}")
    print("=" * 60)

    for s in statuses:
        healthy = s.get("healthy", False)
        icon = f"{GREEN}healthy{NC}" if healthy else f"{RED}unhealthy{NC}"
        cid = s.get("connector_id", "?")
        ctype = s.get("connector_type", "?")
        ingested = s.get("notes_ingested", 0)
        errors = s.get("error_count", 0)
        last_pull = s.get("last_pull_time", "never")
        last_error = s.get("last_error", "")

        print(f"  {icon}  {BOLD}{cid}{NC} ({ctype})")
        print(f"         ingested={ingested}  errors={errors}  last_pull={last_pull}")
        if last_error:
            print(f"         {RED}last_error: {last_error}{NC}")

    print()


def cmd_pull(args, registry: ConnectorRegistry):
    """Run pull on connectors."""
    loaded = registry.load_all()
    started = registry.start_all()

    vault = resolve_vault_path()

    if args.id:
        conn = registry.get(args.id)
        if conn is None:
            print(f"{RED}[error]{NC} Connector not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        if conn.mode not in ("pull", "both"):
            print(f"{YELLOW}[warn]{NC} Connector {args.id} is push-only", file=sys.stderr)
            sys.exit(1)
        try:
            items = conn.pull()
            conn.record_pull()
            written = 0
            for raw in items:
                note = conn.transform(raw)
                path = note.write_to_vault(vault)
                conn.record_ingestion()
                written += 1
                print(f"  {GREEN}[ok]{NC} {path}")
            print(f"\n  Pulled {len(items)} item(s), wrote {written} note(s)")
        except Exception as exc:
            print(f"  {RED}[error]{NC} {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        written_paths = registry.pull_all(vault)
        for p in written_paths:
            print(f"  {GREEN}[ok]{NC} {p}")
        print(f"\n  Total: {len(written_paths)} note(s) written")


def main():
    parser = argparse.ArgumentParser(
        prog="openclaw-connector",
        description="Manage connectors for the knowledge graph.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # list
    subparsers.add_parser("list", help="List configured connectors")

    # types
    subparsers.add_parser("types", help="List available connector types")

    # add
    add_p = subparsers.add_parser("add", help="Add a new connector")
    add_p.add_argument("type", help="Connector type (e.g. filesystem, webhook, github)")
    add_p.add_argument("id", help="Unique connector ID")
    add_p.add_argument("--trust", default=None, help="Trust level (verified, high, medium, low)")
    add_p.add_argument("--mode", default=None, help="Mode (pull, push, both)")
    add_p.add_argument("--zone", default=None, help="Landing zone (e.g. queue-cicd)")
    add_p.add_argument("--set", action="append", help="Config key=value pair (repeatable)")

    # remove
    rm_p = subparsers.add_parser("remove", help="Remove a connector")
    rm_p.add_argument("id", help="Connector ID to remove")

    # test
    test_p = subparsers.add_parser("test", help="Test connector connectivity")
    test_p.add_argument("id", help="Connector ID to test")

    # status
    subparsers.add_parser("status", help="Show connector health status")

    # pull
    pull_p = subparsers.add_parser("pull", help="Run pull on connectors")
    pull_p.add_argument("--id", default=None, help="Pull from specific connector only")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    registry = ConnectorRegistry()

    dispatch = {
        "list": cmd_list,
        "types": cmd_types,
        "add": cmd_add,
        "remove": cmd_remove,
        "test": cmd_test,
        "status": cmd_status,
        "pull": cmd_pull,
    }

    handler = dispatch.get(args.command)
    if handler:
        handler(args, registry)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
```

### Step 10.3: Make CLI executable and verify

- [ ] Make executable and test help output

```bash
chmod +x /Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-connector
/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-connector --help
```

**Expected output:** Argument parser help text showing list, types, add, remove, test, status, pull subcommands.

**Commit:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && git add plugin/bin/openclaw-connector plugin/config/connectors.json.example && git commit -m "$(cat <<'EOF'
feat: add openclaw-connector CLI and connectors.json example config

CLI supports list, types, add, remove, test, status, and pull commands.
Example config includes a filesystem connector watching the inbox folder.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Community connector packaging

**What:** Define the community connector manifest spec (`connector.json`) and document how community connectors are discovered and loaded by the registry. The registry already handles community connectors (Task 3), so this task is about the manifest schema and a stub example.

### Step 11.1: Create a community connector example

- [ ] Write `docs/connector-manifest-spec.json` (the schema)

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/connector-manifest-schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "OpenClaw LACP Connector Manifest",
  "description": "Required connector.json for community connectors distributed as npm packages.",
  "type": "object",
  "required": ["id", "type", "version", "trust_level", "mode", "required_config"],
  "properties": {
    "id": {
      "type": "string",
      "description": "Unique connector type identifier (e.g. 'notion', 'linear')"
    },
    "type": {
      "type": "string",
      "description": "Connector type, typically same as id"
    },
    "version": {
      "type": "string",
      "description": "Semantic version of the connector",
      "pattern": "^\\d+\\.\\d+\\.\\d+"
    },
    "trust_level": {
      "type": "string",
      "enum": ["verified", "high", "medium", "low"],
      "description": "Default trust level for this connector's output"
    },
    "mode": {
      "type": "string",
      "enum": ["pull", "push", "both"],
      "description": "Whether the connector pulls data, receives pushes, or both"
    },
    "required_config": {
      "type": "array",
      "items": { "type": "string" },
      "description": "List of config keys that must be provided when adding this connector"
    },
    "landing_zone": {
      "type": "string",
      "description": "Default inbox subfolder (e.g. 'queue-human')",
      "default": "queue-human"
    },
    "description": {
      "type": "string",
      "description": "Human-readable description of what this connector does"
    },
    "author": {
      "type": "string",
      "description": "Author or organization name"
    },
    "homepage": {
      "type": "string",
      "description": "URL to documentation or project page"
    }
  },
  "additionalProperties": false
}
```

### Step 11.2: Create a stub community connector example

- [ ] Write `plugin/lib/connectors/examples/community-connector-template/connector.json`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/examples/community-connector-template/connector.json`

```json
{
  "id": "example",
  "type": "example",
  "version": "1.0.0",
  "trust_level": "medium",
  "mode": "pull",
  "required_config": ["api_token"],
  "landing_zone": "queue-human",
  "description": "Example community connector template",
  "author": "Your Name",
  "homepage": "https://github.com/your-org/openclaw-lacp-connector-example"
}
```

- [ ] Write `plugin/lib/connectors/examples/community-connector-template/index.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/examples/community-connector-template/index.py`

```python
"""
Example community connector template.

To create a community connector:
1. Copy this directory as openclaw-lacp-connector-<your-type>/
2. Edit connector.json with your connector's metadata
3. Implement the Connector methods below
4. Publish to npm: npm publish
5. Users install with: openclaw plugins install openclaw-lacp-connector-<your-type>
"""

from __future__ import annotations

from typing import Any

# Import from the main plugin (available at runtime)
import sys
from pathlib import Path

# The base classes are available when the connector is loaded by the registry
try:
    from lib.connectors.base import Connector, ConnectorStatus, RawData, VaultNote
except ImportError:
    # Fallback for standalone testing
    from plugin.lib.connectors.base import Connector, ConnectorStatus, RawData, VaultNote


class ExampleConnector(Connector):
    """
    Example community connector.

    Replace this with your actual connector implementation.
    The class name MUST be <Type>Connector in PascalCase
    (e.g. NotionConnector, LinearConnector).
    """

    type = "example"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._api_token: str = self.connector_config.get("api_token", "")

    def authenticate(self) -> bool:
        """Verify the API token is valid."""
        return bool(self._api_token)

    def pull(self) -> list[RawData]:
        """Fetch new data from the external source."""
        # TODO: Implement your pull logic here
        # Return a list of RawData objects
        return []

    def transform(self, raw_data: RawData) -> VaultNote:
        """Convert raw data into a vault note."""
        return VaultNote(
            title=raw_data.payload.get("title", "Untitled"),
            body=raw_data.payload.get("body", ""),
            source_connector=self.id,
            source_type=self.type,
            source_id=raw_data.source_id,
            trust_level=self.trust_level,
            landing_zone=self.landing_zone,
        )

    def health_check(self) -> ConnectorStatus:
        """Return connector health status."""
        return self.base_status(healthy=bool(self._api_token))
```

- [ ] Write `plugin/lib/connectors/examples/community-connector-template/package.json`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/connectors/examples/community-connector-template/package.json`

```json
{
  "name": "openclaw-lacp-connector-example",
  "version": "1.0.0",
  "description": "Example community connector for openclaw-lacp-fusion",
  "main": "index.py",
  "keywords": ["openclaw", "lacp", "connector"],
  "license": "MIT",
  "files": [
    "connector.json",
    "index.py",
    "transforms/"
  ]
}
```

**Commit:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && git add plugin/lib/connectors/connector-manifest-schema.json plugin/lib/connectors/examples/ && git commit -m "$(cat <<'EOF'
feat: add community connector manifest schema and template

Defines connector.json schema with required fields (id, type, version,
trust_level, mode, required_config). Includes example template with
package.json, connector.json, and index.py stub implementation.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Summary of all files

| File | Purpose |
|---|---|
| `plugin/lib/connectors/__init__.py` | Package init, exports base classes |
| `plugin/lib/connectors/base.py` | Connector ABC, VaultNote, RawData, ConnectorStatus |
| `plugin/lib/connectors/trust.py` | Two-layer trust, sender verification, HMAC, IP allowlist |
| `plugin/lib/connectors/registry.py` | Config loading, lifecycle, community connector discovery |
| `plugin/lib/connectors/filesystem.py` | Native: watch directories for files |
| `plugin/lib/connectors/webhook.py` | Native: generic HTTP webhook receiver |
| `plugin/lib/connectors/cron_fetch.py` | Native: poll URLs on schedule |
| `plugin/lib/connectors/github.py` | First-party: GitHub webhook events |
| `plugin/lib/connectors/slack.py` | First-party: Slack events and reaction bookmarking |
| `plugin/lib/connectors/email.py` | First-party: IMAP/gog email polling |
| `plugin/bin/openclaw-connector` | CLI: list, types, add, remove, test, status, pull |
| `plugin/config/connectors.json.example` | Example configuration |
| `plugin/lib/connectors/connector-manifest-schema.json` | Community connector manifest JSON schema |
| `plugin/lib/connectors/examples/community-connector-template/` | Starter template for community connectors |
| `plugin/lib/connectors/tests/test_base.py` | Tests for base classes |
| `plugin/lib/connectors/tests/test_trust.py` | Tests for trust verification |
| `plugin/lib/connectors/tests/test_registry.py` | Tests for registry |
| `plugin/lib/connectors/tests/test_filesystem.py` | Tests for filesystem connector |
| `plugin/lib/connectors/tests/test_webhook.py` | Tests for webhook connector |
| `plugin/lib/connectors/tests/test_cron_fetch.py` | Tests for cron-fetch connector |
| `plugin/lib/connectors/tests/test_github.py` | Tests for GitHub connector |
| `plugin/lib/connectors/tests/test_slack.py` | Tests for Slack connector |
| `plugin/lib/connectors/tests/test_email.py` | Tests for email connector |

## Dependencies

- Python 3.9+ (stdlib only -- no pip dependencies for core)
- `watchdog` optional (filesystem connector uses polling by default)
- `gog` utility optional (email connector Gmail OAuth mode)
- All HTTP done with `urllib.request` (no requests/httpx dependency)

## Integration points

- Curator scheduled loop calls `registry.pull_all(vault_path)` every cycle
- Curator HTTP surface routes webhook POSTs to `registry.receive(connector_id, payload, vault_path)`
- All notes land in `05_Inbox/queue-*/` folders for curator processing
- Trust levels determine curator promotion behavior (spec section 2.4)
