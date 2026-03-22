# Foundation Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the foundation layer by porting brain-resolve, memory-kpi, and obsidian-memory-optimize from LACP, wiring the mycelium algorithms into brain-expand, and registering new agent tools.

**Architecture:** Port 3 CLI tools from the original LACP repo, adapting paths and config for OpenClaw. Wire the already-implemented mycelium module (plugin/lib/mycelium.py) into the brain-expand orchestrator. Register 3 new agent tools via api.registerTool() in index.ts.

**Tech Stack:** Python 3.9+, Bash, TypeScript (index.ts), @sinclair/typebox for tool schemas

---

## Task 1: Port brain-resolve

Port `/Users/andrew/Development/Tools/lacp/bin/lacp-brain-resolve` (168 lines) to OpenClaw. The script resolves contradiction/supersession state for canonical memory notes. It supports resolutions: superseded, contradiction_resolved, validated, stale, archived. Updates YAML frontmatter with resolution state, reason, and superseded-by references.

### Step 1.1: Create openclaw-brain-resolve

- [ ] Write `plugin/bin/openclaw-brain-resolve`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-brain-resolve`

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import Any


@dataclass
class Match:
    path: Path
    text: str


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Resolve contradiction/supersession state for canonical memory notes")
    p.add_argument("--id", required=True, help="Canonical note id to resolve")
    p.add_argument(
        "--resolution",
        required=True,
        choices=["superseded", "contradiction_resolved", "validated", "stale", "archived"],
        help="Resolution state to apply",
    )
    p.add_argument("--superseded-by", default="", help="ID of replacement note (for superseded resolution)")
    p.add_argument("--reason", required=True, help="Resolution rationale")
    p.add_argument(
        "--vault",
        default=os.environ.get("LACP_OBSIDIAN_VAULT", os.environ.get("OPENCLAW_VAULT", "")),
        help="Obsidian vault root",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def resolve_vault(path_arg: str) -> Path:
    raw = path_arg.strip() if path_arg else ""
    if not raw:
        # OpenClaw default: ~/.openclaw/data/knowledge
        openclaw_home = os.environ.get("OPENCLAW_HOME", os.path.expanduser("~/.openclaw"))
        raw = os.path.join(openclaw_home, "data", "knowledge")
    return Path(raw).expanduser().resolve()


def has_frontmatter(text: str) -> bool:
    return text.startswith("---\n")


def parse_frontmatter(text: str) -> tuple[str, str, str]:
    if not has_frontmatter(text):
        return "", text, ""
    end = text.find("\n---\n", 4)
    if end == -1:
        return "", text, ""
    fm = text[4:end]
    body = text[end + 5 :]
    return "---\n", fm, body


def find_target_notes(vault: Path, node_id: str) -> list[Match]:
    out: list[Match] = []
    needle = f"id: {node_id}"
    for p in vault.rglob("*.md"):
        if "/.obsidian/" in p.as_posix():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if needle in text:
            out.append(Match(path=p, text=text))
    return out


def upsert_scalar(frontmatter: str, key: str, value: str) -> str:
    pat = re.compile(rf"(?m)^{re.escape(key)}:\s*.*$")
    line = f"{key}: {value}"
    if pat.search(frontmatter):
        return pat.sub(line, frontmatter)
    return frontmatter.rstrip() + "\n" + line + "\n"


def upsert_multiline_list(frontmatter: str, key: str, item: str) -> str:
    block_pat = re.compile(rf"(?ms)^{re.escape(key)}:\s*\n((?:\s{{2}}-\s.*\n)*)")
    m = block_pat.search(frontmatter)
    if m:
        block = m.group(1)
        entry = f'  - "{item}"\n'
        if entry in block:
            return frontmatter
        replacement = f"{key}:\n{block}{entry}"
        return frontmatter[: m.start()] + replacement + frontmatter[m.end() :]
    return frontmatter.rstrip() + f"\n{key}:\n  - \"{item}\"\n"


def apply_resolution(text: str, *, resolution: str, reason: str, superseded_by: str) -> str:
    prefix, fm, body = parse_frontmatter(text)
    if not prefix:
        created = datetime.now(UTC).strftime("%Y-%m-%d")
        fm = "\n".join([f"created: {created}", "type: concept", "layer: 2", "status: active"])
        prefix = "---\n"

    now = datetime.now(UTC).strftime("%Y-%m-%d")
    fm = upsert_scalar(fm, "resolution_status", resolution)
    fm = upsert_scalar(fm, "resolution_reason", json.dumps(reason))
    fm = upsert_scalar(fm, "resolved_at", now)

    if resolution == "superseded" and superseded_by:
        fm = upsert_scalar(fm, "status", "stale")
        fm = upsert_scalar(fm, "superseded_by", superseded_by)
        fm = upsert_multiline_list(fm, "links.supersedes_ids", superseded_by)
    elif resolution in {"archived", "stale"}:
        fm = upsert_scalar(fm, "status", resolution)
    elif resolution in {"validated", "contradiction_resolved"}:
        fm = upsert_scalar(fm, "status", "active")

    return f"{prefix}{fm}---\n{body}"


def main() -> int:
    args = build_parser().parse_args()
    vault = resolve_vault(args.vault)
    if not vault.exists():
        payload = {"ok": False, "kind": "brain_resolve", "error": f"vault_missing:{vault}"}
        print(json.dumps(payload, indent=2) if args.json else payload["error"])
        return 2

    matches = find_target_notes(vault, args.id)
    if not matches:
        payload = {"ok": False, "kind": "brain_resolve", "error": f"id_not_found:{args.id}", "vault": str(vault)}
        print(json.dumps(payload, indent=2) if args.json else payload["error"])
        return 3

    updated_paths: list[str] = []
    for m in matches:
        new_text = apply_resolution(
            m.text,
            resolution=args.resolution,
            reason=args.reason,
            superseded_by=args.superseded_by,
        )
        if new_text != m.text:
            updated_paths.append(str(m.path))
            if not args.dry_run:
                m.path.write_text(new_text, encoding="utf-8")

    payload: dict[str, Any] = {
        "ok": True,
        "kind": "brain_resolve",
        "vault": str(vault),
        "id": args.id,
        "resolution": args.resolution,
        "superseded_by": args.superseded_by,
        "reason": args.reason,
        "dry_run": args.dry_run,
        "updated_count": len(updated_paths),
        "updated_paths": updated_paths,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"brain-resolve ok=true id={args.id} resolution={args.resolution} updated={len(updated_paths)}")
        for p in updated_paths:
            print(f"  - {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**Key adaptations from LACP original:**
- `--vault` default now reads `LACP_OBSIDIAN_VAULT`, then `OPENCLAW_VAULT`, then falls back to `~/.openclaw/data/knowledge` (was `~/obsidian/vault`)
- `resolve_vault()` uses `OPENCLAW_HOME` env var (default `~/.openclaw`) for path construction
- No other logic changes needed; the script is path-agnostic once the vault is resolved

### Step 1.2: Make executable and verify

- [ ] Make the script executable and verify it runs

```bash
chmod +x /Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-brain-resolve
/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-brain-resolve --help
```

**Expected output:** Argument parser help text showing `--id`, `--resolution`, `--reason`, `--vault`, `--dry-run`, `--json` flags.

### Step 1.3: Write tests for brain-resolve

- [ ] Write test file `plugin/bin/tests/test_brain_resolve.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/tests/test_brain_resolve.py`

```python
"""Tests for openclaw-brain-resolve."""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

SCRIPT = str(Path(__file__).resolve().parent.parent / "openclaw-brain-resolve")


def _make_vault_with_note(tmp_path, note_id="test-note-001", status="active"):
    """Create a minimal vault with one canonical note."""
    note = tmp_path / "concepts" / f"{note_id}.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        f"---\nid: {note_id}\ntype: concept\nlayer: 2\nstatus: {status}\nconfidence: 0.8\n---\n\n# Test Note\n\nSome content.\n",
        encoding="utf-8",
    )
    return note


class TestBrainResolveHelp:
    def test_help_exits_zero(self):
        result = subprocess.run(
            ["python3", SCRIPT, "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "--resolution" in result.stdout


class TestBrainResolveMissingVault:
    def test_missing_vault_exits_2(self):
        result = subprocess.run(
            [
                "python3", SCRIPT,
                "--id", "nonexistent",
                "--resolution", "validated",
                "--reason", "test",
                "--vault", "/tmp/nonexistent-vault-abc123",
                "--json",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 2
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert "vault_missing" in payload["error"]


class TestBrainResolveNotFound:
    def test_id_not_found_exits_3(self, tmp_path):
        _make_vault_with_note(tmp_path, note_id="other-note")
        result = subprocess.run(
            [
                "python3", SCRIPT,
                "--id", "nonexistent-id",
                "--resolution", "validated",
                "--reason", "test",
                "--vault", str(tmp_path),
                "--json",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 3
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert "id_not_found" in payload["error"]


class TestBrainResolveValidated:
    def test_validated_updates_frontmatter(self, tmp_path):
        note = _make_vault_with_note(tmp_path, note_id="resolve-test-001")
        result = subprocess.run(
            [
                "python3", SCRIPT,
                "--id", "resolve-test-001",
                "--resolution", "validated",
                "--reason", "Confirmed via source",
                "--vault", str(tmp_path),
                "--json",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["updated_count"] == 1

        updated_text = note.read_text()
        assert "resolution_status: validated" in updated_text
        assert "status: active" in updated_text


class TestBrainResolveSuperseded:
    def test_superseded_sets_stale_and_ref(self, tmp_path):
        note = _make_vault_with_note(tmp_path, note_id="old-note-001")
        result = subprocess.run(
            [
                "python3", SCRIPT,
                "--id", "old-note-001",
                "--resolution", "superseded",
                "--superseded-by", "new-note-002",
                "--reason", "Replaced by updated version",
                "--vault", str(tmp_path),
                "--json",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True

        updated_text = note.read_text()
        assert "resolution_status: superseded" in updated_text
        assert "status: stale" in updated_text
        assert "superseded_by: new-note-002" in updated_text


class TestBrainResolveDryRun:
    def test_dry_run_does_not_write(self, tmp_path):
        note = _make_vault_with_note(tmp_path, note_id="dryrun-001")
        original = note.read_text()
        result = subprocess.run(
            [
                "python3", SCRIPT,
                "--id", "dryrun-001",
                "--resolution", "archived",
                "--reason", "No longer relevant",
                "--vault", str(tmp_path),
                "--dry-run", "--json",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["dry_run"] is True
        assert payload["updated_count"] == 1
        # File should NOT have changed
        assert note.read_text() == original
```

### Step 1.4: Run tests and verify

- [ ] Run brain-resolve tests

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/bin/tests/test_brain_resolve.py -v
```

**Expected output:** All 6 tests pass.

### Step 1.5: Commit

- [ ] Commit brain-resolve

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo
git add plugin/bin/openclaw-brain-resolve plugin/bin/tests/test_brain_resolve.py
git commit -m "$(cat <<'EOF'
feat: port brain-resolve from LACP to OpenClaw

Contradiction/supersession resolution tool for canonical memory notes.
Supports resolutions: superseded, contradiction_resolved, validated, stale, archived.
Adapted paths from ~/.claude/ to ~/.openclaw/ with OPENCLAW_HOME/OPENCLAW_VAULT env vars.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Port memory-kpi

Port `/Users/andrew/Development/Tools/lacp/bin/lacp-memory-kpi` (111 lines) to OpenClaw. The script reports vault quality metrics: frontmatter coverage, schema compliance, contradiction count, staleness distribution.

### Step 2.1: Create openclaw-memory-kpi

- [ ] Write `plugin/bin/openclaw-memory-kpi`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-memory-kpi`

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Report memory-quality KPIs for OpenClaw Obsidian vault")
    p.add_argument(
        "--vault",
        default=os.environ.get("LACP_OBSIDIAN_VAULT", os.environ.get("OPENCLAW_VAULT", "")),
        help="Vault path",
    )
    p.add_argument("--json", action="store_true")
    return p


def resolve_vault(raw: str) -> Path:
    value = raw.strip() if raw else ""
    if not value:
        openclaw_home = os.environ.get("OPENCLAW_HOME", os.path.expanduser("~/.openclaw"))
        value = os.path.join(openclaw_home, "data", "knowledge")
    return Path(value).expanduser().resolve()


def frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---\n", 4)
    if end == -1:
        return ""
    return text[4:end]


def has_field(fm: str, field: str) -> bool:
    return re.search(rf"(?m)^{re.escape(field)}:\s*", fm) is not None


def main() -> int:
    args = build_parser().parse_args()
    vault = resolve_vault(args.vault)
    if not vault.exists():
        payload = {"ok": False, "kind": "memory_kpi", "error": f"vault_missing:{vault}"}
        print(json.dumps(payload, indent=2) if args.json else payload["error"])
        return 2

    note_files = [p for p in vault.rglob("*.md") if "/.obsidian/" not in p.as_posix()]

    total = len(note_files)
    canonical = 0
    required_ok = 0
    contradiction_notes = 0
    stale_notes = 0
    source_backed = 0

    required = ["id", "type", "layer", "status", "confidence", "source_urls", "last_verified", "links"]

    for p in note_files:
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        fm = frontmatter(text)
        if not fm:
            continue

        has_canonical_shape = any(has_field(fm, f) for f in ["layer", "confidence", "source_urls", "links"])
        if has_canonical_shape:
            canonical += 1

        if all(has_field(fm, f) for f in required):
            required_ok += 1

        if "contradicts:" in fm and re.search(r"(?m)^\s*-\s", fm):
            contradiction_notes += 1

        if re.search(r"(?m)^status:\s*stale\s*$", fm):
            stale_notes += 1

        if re.search(r"(?m)^source_urls:\s*\n\s{2}-\s", fm):
            source_backed += 1

    payload = {
        "ok": True,
        "kind": "memory_kpi",
        "vault": str(vault),
        "kpis": {
            "total_notes": total,
            "canonical_notes": canonical,
            "required_schema_coverage_pct": round((required_ok / canonical) * 100, 2) if canonical else 0,
            "source_backed_pct": round((source_backed / canonical) * 100, 2) if canonical else 0,
            "contradiction_notes": contradiction_notes,
            "stale_notes": stale_notes,
        },
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        k = payload["kpis"]
        print("memory-kpi")
        print(f"  total_notes: {k['total_notes']}")
        print(f"  canonical_notes: {k['canonical_notes']}")
        print(f"  required_schema_coverage_pct: {k['required_schema_coverage_pct']}")
        print(f"  source_backed_pct: {k['source_backed_pct']}")
        print(f"  contradiction_notes: {k['contradiction_notes']}")
        print(f"  stale_notes: {k['stale_notes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**Key adaptations from LACP original:**
- `--vault` default reads `LACP_OBSIDIAN_VAULT`, then `OPENCLAW_VAULT`, then falls back to `~/.openclaw/data/knowledge`
- `resolve_vault()` uses `OPENCLAW_HOME` env var for path construction
- Description updated from "LACP" to "OpenClaw"

### Step 2.2: Make executable and verify

- [ ] Make the script executable and verify it runs

```bash
chmod +x /Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-memory-kpi
/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-memory-kpi --help
```

**Expected output:** Argument parser help text showing `--vault` and `--json` flags.

### Step 2.3: Write tests for memory-kpi

- [ ] Write test file `plugin/bin/tests/test_memory_kpi.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/tests/test_memory_kpi.py`

```python
"""Tests for openclaw-memory-kpi."""

import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = str(Path(__file__).resolve().parent.parent / "openclaw-memory-kpi")


def _make_vault(tmp_path, notes=None):
    """Create a vault with optional note specs."""
    if notes is None:
        notes = []
    for note in notes:
        path = tmp_path / note["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(note["content"], encoding="utf-8")
    return tmp_path


class TestMemoryKpiHelp:
    def test_help_exits_zero(self):
        result = subprocess.run(
            ["python3", SCRIPT, "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "--vault" in result.stdout


class TestMemoryKpiMissingVault:
    def test_missing_vault_exits_2(self):
        result = subprocess.run(
            ["python3", SCRIPT, "--vault", "/tmp/nonexistent-kpi-vault-xyz", "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 2
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert "vault_missing" in payload["error"]


class TestMemoryKpiEmptyVault:
    def test_empty_vault_returns_zeros(self, tmp_path):
        result = subprocess.run(
            ["python3", SCRIPT, "--vault", str(tmp_path), "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["kpis"]["total_notes"] == 0
        assert payload["kpis"]["canonical_notes"] == 0


class TestMemoryKpiWithNotes:
    def test_counts_canonical_and_stale(self, tmp_path):
        vault = _make_vault(tmp_path, notes=[
            {
                "path": "concepts/note1.md",
                "content": "---\nid: n1\ntype: concept\nlayer: 2\nstatus: active\nconfidence: 0.9\nsource_urls:\n  - https://example.com\nlast_verified: 2026-01-01\nlinks:\n  - n2\n---\n\n# Note 1\n",
            },
            {
                "path": "concepts/note2.md",
                "content": "---\nid: n2\ntype: concept\nlayer: 2\nstatus: stale\nconfidence: 0.5\n---\n\n# Note 2\n",
            },
            {
                "path": "random/no-frontmatter.md",
                "content": "# Just a plain note\n\nNo frontmatter here.\n",
            },
        ])
        result = subprocess.run(
            ["python3", SCRIPT, "--vault", str(vault), "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        kpis = payload["kpis"]
        assert kpis["total_notes"] == 3
        assert kpis["canonical_notes"] == 2  # both have layer/confidence
        assert kpis["stale_notes"] == 1
        assert kpis["source_backed_pct"] > 0  # note1 has source_urls


class TestMemoryKpiTextOutput:
    def test_text_format_works(self, tmp_path):
        _make_vault(tmp_path, notes=[
            {
                "path": "note.md",
                "content": "---\nid: x\nlayer: 1\nstatus: active\n---\n\nContent\n",
            },
        ])
        result = subprocess.run(
            ["python3", SCRIPT, "--vault", str(tmp_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "memory-kpi" in result.stdout
        assert "total_notes:" in result.stdout
```

### Step 2.4: Run tests and verify

- [ ] Run memory-kpi tests

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/bin/tests/test_memory_kpi.py -v
```

**Expected output:** All 5 tests pass.

### Step 2.5: Commit

- [ ] Commit memory-kpi

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo
git add plugin/bin/openclaw-memory-kpi plugin/bin/tests/test_memory_kpi.py
git commit -m "$(cat <<'EOF'
feat: port memory-kpi from LACP to OpenClaw

Vault quality metrics tool: frontmatter coverage, schema compliance,
contradiction count, staleness distribution. Adapted paths for OpenClaw.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Port obsidian-memory-optimize

Port `/Users/andrew/Development/Tools/lacp/bin/lacp-obsidian-memory-optimize` (89 lines) to OpenClaw. The script applies memory-centric Obsidian graph physics defaults: hide archive/trash, tune link distance, repel strength, node sizing, and color groups.

### Step 3.1: Create openclaw-obsidian-optimize

- [ ] Write `plugin/bin/openclaw-obsidian-optimize`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-obsidian-optimize`

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Apply memory-centric Obsidian graph defaults for OpenClaw")
    p.add_argument(
        "--vault",
        default=os.environ.get("LACP_OBSIDIAN_VAULT", os.environ.get("OPENCLAW_VAULT", "")),
        help="Vault root",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def resolve_vault(raw: str) -> Path:
    value = raw.strip() if raw else ""
    if not value:
        openclaw_home = os.environ.get("OPENCLAW_HOME", os.path.expanduser("~/.openclaw"))
        value = os.path.join(openclaw_home, "data", "knowledge")
    return Path(value).expanduser().resolve()


def default_graph_profile() -> dict:
    return {
        "collapse-filter": False,
        "search": "-path:inbox/queue-generated -path:99-archive -path:99_Archive -path:.trash",
        "showTags": True,
        "showAttachments": False,
        "hideUnresolved": True,
        "localJumps": 1,
        "neighborJumps": 1,
        "lineSizeMultiplier": 0.7,
        "nodeSizeMultiplier": 0.9,
        "lineStrength": 0.6,
        "centerStrength": 0.4,
        "repelStrength": 10,
        "linkDistance": 120,
        "close": False,
        "colorGroups": [
            {"query": "path:01-session", "color": {"a": 1, "rgb": 9360716}},
            {"query": "path:02-graph-core OR path:knowledge", "color": {"a": 1, "rgb": 4897072}},
            {"query": "path:03-ingest OR path:inbox/queue-generated", "color": {"a": 1, "rgb": 12632256}},
            {"query": "path:04-code-intel", "color": {"a": 1, "rgb": 5887948}},
            {"query": "path:05-identity-provenance", "color": {"a": 1, "rgb": 13882323}},
            {"query": "tag:#decision OR type:decision", "color": {"a": 1, "rgb": 16756224}},
            {"query": "tag:#concept OR type:concept", "color": {"a": 1, "rgb": 4247295}},
        ],
    }


def write_json(path: Path, payload: dict, dry_run: bool) -> bool:
    if dry_run:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return True


def main() -> int:
    args = build_parser().parse_args()
    vault = resolve_vault(args.vault)
    if not vault.exists():
        payload = {"ok": False, "kind": "obsidian_memory_optimize", "error": f"vault_missing:{vault}"}
        print(json.dumps(payload, indent=2) if args.json else payload["error"])
        return 2

    graph_path = vault / ".obsidian" / "graph.json"
    payload = default_graph_profile()
    wrote = write_json(graph_path, payload, args.dry_run)

    out = {
        "ok": True,
        "kind": "obsidian_memory_optimize",
        "vault": str(vault),
        "dry_run": args.dry_run,
        "graph": {"path": str(graph_path), "wrote": wrote, "profile": "openclaw-memory-v1"},
    }

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"obsidian-memory-optimize ok=true wrote={str(wrote).lower()} path={graph_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**Key adaptations from LACP original:**
- Same vault resolution pattern (LACP_OBSIDIAN_VAULT -> OPENCLAW_VAULT -> ~/.openclaw/data/knowledge)
- Added `99_Archive` to the search exclusion filter (OpenClaw uses `99_Archive` convention)
- Profile name changed from `lacp-memory-v1` to `openclaw-memory-v1`

### Step 3.2: Make executable and verify

- [ ] Make the script executable and verify it runs

```bash
chmod +x /Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-obsidian-optimize
/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-obsidian-optimize --help
```

**Expected output:** Argument parser help text showing `--vault`, `--dry-run`, `--json` flags.

### Step 3.3: Write tests for obsidian-optimize

- [ ] Write test file `plugin/bin/tests/test_obsidian_optimize.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/tests/test_obsidian_optimize.py`

```python
"""Tests for openclaw-obsidian-optimize."""

import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = str(Path(__file__).resolve().parent.parent / "openclaw-obsidian-optimize")


class TestObsidianOptimizeHelp:
    def test_help_exits_zero(self):
        result = subprocess.run(
            ["python3", SCRIPT, "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "--vault" in result.stdout


class TestObsidianOptimizeMissingVault:
    def test_missing_vault_exits_2(self):
        result = subprocess.run(
            ["python3", SCRIPT, "--vault", "/tmp/nonexistent-opt-vault-xyz", "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 2
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert "vault_missing" in payload["error"]


class TestObsidianOptimizeDryRun:
    def test_dry_run_does_not_write_file(self, tmp_path):
        result = subprocess.run(
            ["python3", SCRIPT, "--vault", str(tmp_path), "--dry-run", "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["dry_run"] is True
        assert payload["graph"]["wrote"] is False
        # File should NOT exist
        graph_path = tmp_path / ".obsidian" / "graph.json"
        assert not graph_path.exists()


class TestObsidianOptimizeWrites:
    def test_writes_graph_json(self, tmp_path):
        result = subprocess.run(
            ["python3", SCRIPT, "--vault", str(tmp_path), "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["graph"]["wrote"] is True
        assert payload["graph"]["profile"] == "openclaw-memory-v1"

        # Verify the file was written and contains expected keys
        graph_path = tmp_path / ".obsidian" / "graph.json"
        assert graph_path.exists()
        graph_data = json.loads(graph_path.read_text())
        assert "repelStrength" in graph_data
        assert graph_data["repelStrength"] == 10
        assert "colorGroups" in graph_data
        assert len(graph_data["colorGroups"]) == 7
        assert graph_data["linkDistance"] == 120


class TestObsidianOptimizeTextOutput:
    def test_text_format_works(self, tmp_path):
        result = subprocess.run(
            ["python3", SCRIPT, "--vault", str(tmp_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "obsidian-memory-optimize" in result.stdout
        assert "ok=true" in result.stdout
```

### Step 3.4: Run tests and verify

- [ ] Run obsidian-optimize tests

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/bin/tests/test_obsidian_optimize.py -v
```

**Expected output:** All 5 tests pass.

### Step 3.5: Ensure `__init__.py` exists in tests directory

- [ ] Create `plugin/bin/tests/__init__.py` if it does not exist

```bash
touch /Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/tests/__init__.py
```

### Step 3.6: Commit

- [ ] Commit obsidian-optimize

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo
git add plugin/bin/openclaw-obsidian-optimize plugin/bin/tests/test_obsidian_optimize.py plugin/bin/tests/__init__.py
git commit -m "$(cat <<'EOF'
feat: port obsidian-memory-optimize from LACP to OpenClaw

Memory-centric Obsidian graph physics tuning: hide archive/trash,
tune link distance, repel strength, node sizing, and color groups.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Wire mycelium into brain-expand

Add `--consolidate` and `--activate` flags to `plugin/bin/openclaw-brain-expand`. These flags invoke the already-implemented Python modules:
- `--consolidate` calls `plugin/lib/consolidation.py` (run_consolidation)
- `--activate` calls `plugin/lib/mycelium.py` (spreading_activation from recent seeds)
- Both also run the FSRS review queue (`plugin/lib/review_queue.py`) and knowledge gaps detection (`plugin/lib/knowledge_gaps.py`)

### Step 4.1: Add --consolidate and --activate to brain-expand

- [ ] Edit `plugin/bin/openclaw-brain-expand` to add the new flags

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-brain-expand`

Add the following changes to the existing file:

**4.1a — Add new flag parsing to `usage()`.** Replace the existing `usage()` function (lines 263-287) with:

```bash
usage() {
  cat <<EOF
$PROG v$VERSION — Memory Expansion & Maintenance

USAGE:
  $PROG [OPTIONS]

OPTIONS:
  --project PATH        Project directory (default: current)
  --layer NUM           Expand specific layer (1-5, default: all)
  --max-tokens NUM      Token budget for summaries (default: 5000)
  --archive-days NUM    Archive entries older than N days (default: 90)
  --consolidate         Run mycelium consolidation pipeline (prune, merge, reinforce, heal)
  --activate            Run spreading activation from recently-accessed notes
  --dry-run             Show what would be done without changes
  --json                Output results as JSON
  --help                Show this help

EXAMPLES:
  # Expand all layers
  $PROG --project ~/repos/easy-api

  # Expand just Layer 1 with custom token budget
  $PROG --project ~/repos/easy-api --layer 1 --max-tokens 8000

  # Run full consolidation + activation
  $PROG --project ~/repos/easy-api --consolidate --activate

  # Archive old entries
  $PROG --project ~/repos/easy-api --archive-days 60

EOF
}
```

**4.1b — Add consolidation and activation functions.** Insert the following block immediately before the `# Main` section comment (before line 260 `# ============================================================================`  that precedes `usage()`):

```bash
# ============================================================================
# Mycelium consolidation (calls Python modules)
# ============================================================================

PLUGIN_DIR="${OPENCLAW_PLUGIN_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"

run_consolidation() {
  local project="$1"
  local dry_run_flag="$2"
  local json_flag="$3"

  echo ""
  echo -e "${BLUE}Running Mycelium Consolidation Pipeline${NC}"

  local vault="${LACP_OBSIDIAN_VAULT:-${OPENCLAW_VAULT:-$HOME/.openclaw/data/knowledge}}"
  if [ ! -d "$vault" ]; then
    log_warn "Vault not found at $vault — skipping consolidation"
    return 0
  fi

  # Step 1: Run consolidation (prune, merge, reinforce, heal)
  log_info "Step 1/3: Running consolidation..."
  local consolidate_args="--vault '$vault'"
  if [ "$dry_run_flag" = "1" ]; then
    consolidate_args="$consolidate_args --dry-run"
  fi

  local consolidation_result
  consolidation_result=$(python3 -c "
import json, sys, os
sys.path.insert(0, '$PLUGIN_DIR')
from plugin.lib.consolidation import run_consolidation
result = run_consolidation(
    vault_path='$vault',
    apply=$( [ "$dry_run_flag" = "1" ] && echo "False" || echo "True" ),
    dry_run=$( [ "$dry_run_flag" = "1" ] && echo "True" || echo "False" ),
)
print(json.dumps(result, indent=2, default=str))
" 2>&1) || {
    log_error "Consolidation failed"
    echo "$consolidation_result" >&2
    return 1
  }

  if [ "$json_flag" = "1" ]; then
    echo "$consolidation_result"
  else
    local pruned
    pruned=$(echo "$consolidation_result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('pruned',0))" 2>/dev/null || echo "?")
    local healed
    healed=$(echo "$consolidation_result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('healed_count',0))" 2>/dev/null || echo "?")
    local reinforced
    reinforced=$(echo "$consolidation_result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('reinforced_count',0))" 2>/dev/null || echo "?")
    echo "  Pruned: $pruned | Healed: $healed | Reinforced: $reinforced"
  fi
  log_success "Consolidation complete"

  # Step 2: Generate FSRS review queue
  log_info "Step 2/3: Generating FSRS review queue..."
  local review_result
  review_result=$(python3 -c "
import json, sys
sys.path.insert(0, '$PLUGIN_DIR')
from plugin.lib.review_queue import write_review_queue
result = write_review_queue(vault_path='$vault')
print(json.dumps(result, indent=2, default=str))
" 2>&1) || {
    log_warn "Review queue generation failed (non-fatal)"
    echo "$review_result" >&2
  }

  if [ -n "$review_result" ]; then
    local review_count
    review_count=$(echo "$review_result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('count',0))" 2>/dev/null || echo "?")
    echo "  Review queue: $review_count items"
    log_success "Review queue generated"
  fi

  # Step 3: Detect knowledge gaps
  log_info "Step 3/3: Detecting knowledge gaps..."
  local gaps_result
  gaps_result=$(python3 -c "
import json, sys
sys.path.insert(0, '$PLUGIN_DIR')
from plugin.lib.knowledge_gaps import write_gap_report
result = write_gap_report(vault_path='$vault')
print(json.dumps(result, indent=2, default=str))
" 2>&1) || {
    log_warn "Knowledge gap detection failed (non-fatal)"
    echo "$gaps_result" >&2
  }

  if [ -n "$gaps_result" ]; then
    local sparse
    sparse=$(echo "$gaps_result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('gaps',{}).get('sparse_categories',[])))" 2>/dev/null || echo "?")
    local missing
    missing=$(echo "$gaps_result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('gaps',{}).get('missing_bridges',[])))" 2>/dev/null || echo "?")
    echo "  Gaps: $sparse sparse categories, $missing missing bridges"
    log_success "Knowledge gaps report generated"
  fi
}

run_activation() {
  local project="$1"
  local json_flag="$2"

  echo ""
  echo -e "${BLUE}Running Spreading Activation${NC}"

  local vault="${LACP_OBSIDIAN_VAULT:-${OPENCLAW_VAULT:-$HOME/.openclaw/data/knowledge}}"
  if [ ! -d "$vault" ]; then
    log_warn "Vault not found at $vault — skipping activation"
    return 0
  fi

  local activation_result
  activation_result=$(python3 -c "
import json, sys
sys.path.insert(0, '$PLUGIN_DIR')
from plugin.lib.consolidation import _load_vault_notes
from plugin.lib.mycelium import (
    compute_retrieval_strength,
    spreading_activation,
    reinforce_access_paths,
)

items = _load_vault_notes('$vault')

# Build seeds from recently-accessed notes (high retrieval strength)
recent_seeds = {}
for node_id, data in items.items():
    edge_count = len(data.get('edges', []))
    r = compute_retrieval_strength(data, edge_count=edge_count)
    if r > 0.7:
        recent_seeds[node_id] = r

# Run spreading activation
activations = {}
if recent_seeds:
    activations = spreading_activation(recent_seeds, items, alpha=0.7, max_hops=3)

# Reinforce accessed paths
total_reinforced = 0
for node_id in recent_seeds:
    result = reinforce_access_paths(node_id, items)
    total_reinforced += result.get('reinforced_count', 0)

output = {
    'seeds': len(recent_seeds),
    'activated_nodes': len(activations),
    'reinforced_edges': total_reinforced,
}
print(json.dumps(output, indent=2))
" 2>&1) || {
    log_error "Activation failed"
    echo "$activation_result" >&2
    return 1
  }

  if [ "$json_flag" = "1" ]; then
    echo "$activation_result"
  else
    local seeds
    seeds=$(echo "$activation_result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('seeds',0))" 2>/dev/null || echo "?")
    local activated
    activated=$(echo "$activation_result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('activated_nodes',0))" 2>/dev/null || echo "?")
    local reinforced
    reinforced=$(echo "$activation_result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('reinforced_edges',0))" 2>/dev/null || echo "?")
    echo "  Seeds: $seeds | Activated: $activated | Reinforced: $reinforced"
  fi
  log_success "Activation complete"
}
```

**4.1c — Update `main()` to parse and dispatch the new flags.** Replace the `main()` function (lines 290-337) with:

```bash
main() {
  local project="."
  local layer=""
  local max_tokens=5000
  local archive_days=90
  local dry_run=0
  local consolidate=0
  local activate=0
  local json_output=0

  while [ $# -gt 0 ]; do
    case "$1" in
      --project) project="$2"; shift 2 ;;
      --layer) layer="$2"; shift 2 ;;
      --max-tokens) max_tokens="$2"; shift 2 ;;
      --archive-days) archive_days="$2"; shift 2 ;;
      --dry-run) dry_run=1; shift ;;
      --consolidate) consolidate=1; shift ;;
      --activate) activate=1; shift ;;
      --json) json_output=1; shift ;;
      --help|-h|help) usage; exit 0 ;;
      *) echo "Unknown option: $1"; usage; exit 1 ;;
    esac
  done

  log_info "OpenClaw Brain Expand v$VERSION"
  log_info "Project: $project"
  log_info "Max tokens: $max_tokens"

  if [ "$dry_run" = "1" ]; then
    log_warn "DRY RUN — no changes will be made"
  fi

  # Standard layer expansion (unless only --consolidate/--activate requested)
  if [ "$consolidate" = "0" ] && [ "$activate" = "0" ]; then
    if [ -z "$layer" ] || [ "$layer" = "1" ]; then
      expand_layer1 "$project" "$max_tokens"
    fi

    if [ -z "$layer" ] || [ "$layer" = "2" ]; then
      expand_layer2 "$project" "$max_tokens"
    fi

    if [ -z "$layer" ] || [ "$layer" = "3" ]; then
      expand_layer3 "$project" "$max_tokens"
    fi

    if [ -z "$layer" ] || [ "$layer" = "5" ]; then
      expand_layer5 "$project" "$max_tokens"
    fi
  fi

  # Mycelium consolidation
  if [ "$consolidate" = "1" ]; then
    run_consolidation "$project" "$dry_run" "$json_output"
  fi

  # Spreading activation
  if [ "$activate" = "1" ]; then
    run_activation "$project" "$json_output"
  fi

  echo ""
  log_success "Expansion complete"
}

main "$@"
```

### Step 4.2: Verify brain-expand still works with existing flags

- [ ] Verify the modified brain-expand shows the new flags in help

```bash
/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-brain-expand --help
```

**Expected output:** Help text includes `--consolidate`, `--activate`, and `--json` alongside original flags.

### Step 4.3: Write tests for the new flags

- [ ] Write test file `plugin/bin/tests/test_brain_expand_mycelium.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/tests/test_brain_expand_mycelium.py`

```python
"""Tests for openclaw-brain-expand --consolidate and --activate flags."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

SCRIPT = str(Path(__file__).resolve().parent.parent / "openclaw-brain-expand")


def _make_vault(tmp_path):
    """Create a minimal vault with notes for consolidation/activation testing."""
    vault = tmp_path / "vault"
    vault.mkdir()
    concepts = vault / "concepts"
    concepts.mkdir()

    # Recent note (high retrieval strength)
    (concepts / "recent-note.md").write_text(
        "---\nid: recent-1\ntype: concept\nlayer: 2\nstatus: active\n"
        "count: 10\nlast_seen: 2026-03-20T12:00:00Z\nconfidence: 0.9\n---\n\n"
        "# Recent Note\n\nRecently accessed content.\n"
        "Links: [[old-note]]\n",
        encoding="utf-8",
    )

    # Old note (low retrieval strength)
    (concepts / "old-note.md").write_text(
        "---\nid: old-1\ntype: concept\nlayer: 2\nstatus: active\n"
        "count: 1\nlast_seen: 2024-01-01T00:00:00Z\nconfidence: 0.3\n---\n\n"
        "# Old Note\n\nNot accessed in a long time.\n"
        "Links: [[recent-note]]\n",
        encoding="utf-8",
    )

    # Inbox directory for review queue output
    inbox = vault / "05_Inbox"
    inbox.mkdir()

    return vault


class TestBrainExpandHelp:
    def test_help_shows_consolidate_flag(self):
        result = subprocess.run(
            ["bash", SCRIPT, "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "--consolidate" in result.stdout
        assert "--activate" in result.stdout
        assert "--json" in result.stdout


class TestBrainExpandConsolidate:
    def test_consolidate_dry_run(self, tmp_path):
        vault = _make_vault(tmp_path)
        env = os.environ.copy()
        env["LACP_OBSIDIAN_VAULT"] = str(vault)
        env["OPENCLAW_PLUGIN_DIR"] = str(Path(__file__).resolve().parent.parent.parent)

        result = subprocess.run(
            ["bash", SCRIPT, "--consolidate", "--dry-run"],
            capture_output=True, text=True, env=env,
        )
        # Should not crash — exit 0
        assert result.returncode == 0
        assert "Consolidation" in result.stderr or "Consolidation" in result.stdout


class TestBrainExpandActivate:
    def test_activate_runs(self, tmp_path):
        vault = _make_vault(tmp_path)
        env = os.environ.copy()
        env["LACP_OBSIDIAN_VAULT"] = str(vault)
        env["OPENCLAW_PLUGIN_DIR"] = str(Path(__file__).resolve().parent.parent.parent)

        result = subprocess.run(
            ["bash", SCRIPT, "--activate"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0
        assert "Activation" in result.stderr or "Activation" in result.stdout
```

### Step 4.4: Run tests and verify

- [ ] Run brain-expand mycelium tests

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/bin/tests/test_brain_expand_mycelium.py -v
```

**Expected output:** All 3 tests pass.

### Step 4.5: Commit

- [ ] Commit brain-expand mycelium wiring

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo
git add plugin/bin/openclaw-brain-expand plugin/bin/tests/test_brain_expand_mycelium.py
git commit -m "$(cat <<'EOF'
feat: wire mycelium consolidation and activation into brain-expand

Add --consolidate and --activate flags to openclaw-brain-expand.
--consolidate runs the full pipeline: prune, merge, reinforce, heal,
then generates FSRS review queue and knowledge gap report.
--activate runs spreading activation from recently-accessed notes
and reinforces access paths.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Register new agent tools in index.ts

Register three new tools in `plugin/index.ts`: `lacp_brain_resolve`, `lacp_memory_kpi`, and `lacp_vault_optimize`. These wrap the CLI scripts created in Tasks 1-3.

### Step 5.1: Add lacp_brain_resolve tool

- [ ] Add brain-resolve tool registration to index.ts

Insert the following block after the existing `lacp_graph_index` tool registration (after the closing `{ optional: true }` on line 286) and before `const toolCount = 6;` (line 288):

```typescript
    // Brain resolve: resolve contradictions/supersessions in knowledge notes
    api.registerTool({
      name: "lacp_brain_resolve",
      description:
        "Resolve contradiction or supersession state for a canonical memory note. " +
        "Use this when you find conflicting information in the knowledge vault — " +
        "mark notes as superseded, validated, stale, or archived with a reason.",
      parameters: Type.Object({
        id: Type.String({ description: "Canonical note ID to resolve" }),
        resolution: Type.String({
          description: 'Resolution: "superseded", "contradiction_resolved", "validated", "stale", "archived"',
          enum: ["superseded", "contradiction_resolved", "validated", "stale", "archived"],
        }),
        reason: Type.String({ description: "Why this resolution was applied" }),
        superseded_by: Type.Optional(Type.String({ description: "ID of replacement note (for superseded resolution)" })),
        dry_run: Type.Optional(Type.Boolean({ description: "Preview changes without writing. Default: false" })),
      }),
      async execute(_id, params: any) {
        const args = [
          "--id", params.id,
          "--resolution", params.resolution,
          "--reason", params.reason,
          "--json",
        ];
        if (params.superseded_by) args.push("--superseded-by", params.superseded_by);
        if (params.dry_run) args.push("--dry-run");
        const result = await runCli("openclaw-brain-resolve", args);
        return textResult(result.stdout || `brain-resolve failed: ${result.stderr}`);
      },
    });
```

### Step 5.2: Add lacp_memory_kpi tool

- [ ] Add memory-kpi tool registration to index.ts

Insert after the brain-resolve tool:

```typescript
    // Memory KPI: vault quality metrics
    api.registerTool({
      name: "lacp_memory_kpi",
      description:
        "Report memory-quality KPIs for the Obsidian knowledge vault — " +
        "total notes, canonical notes, schema coverage, source backing, " +
        "contradiction count, and staleness. Use this to assess vault health.",
      parameters: Type.Object({
        vault: Type.Optional(Type.String({ description: "Vault path (default: from config)" })),
      }),
      async execute(_id, params: any) {
        const args = ["--json"];
        if (params.vault) args.push("--vault", params.vault);
        const result = await runCli("openclaw-memory-kpi", args);
        return textResult(result.stdout || `memory-kpi failed: ${result.stderr}`);
      },
    });
```

### Step 5.3: Add lacp_vault_optimize tool

- [ ] Add vault-optimize tool registration to index.ts

Insert after the memory-kpi tool:

```typescript
    // Vault optimize: apply memory-centric Obsidian graph defaults
    api.registerTool({
      name: "lacp_vault_optimize",
      description:
        "Apply memory-centric graph physics defaults to the Obsidian vault — " +
        "tune link distance, repel strength, node sizing, and color groups " +
        "for optimal knowledge graph visualization. Hides archive/trash paths.",
      parameters: Type.Object({
        vault: Type.Optional(Type.String({ description: "Vault path (default: from config)" })),
        dry_run: Type.Optional(Type.Boolean({ description: "Preview changes without writing. Default: false" })),
      }),
      async execute(_id, params: any) {
        const args = ["--json"];
        if (params.vault) args.push("--vault", params.vault);
        if (params.dry_run) args.push("--dry-run");
        const result = await runCli("openclaw-obsidian-optimize", args);
        return textResult(result.stdout || `vault-optimize failed: ${result.stderr}`);
      },
    });
```

### Step 5.4: Update tool count

- [ ] Update the toolCount constant

Change line 288 from:

```typescript
    const toolCount = 6;
```

to:

```typescript
    const toolCount = 9;
```

### Step 5.5: Verify the complete index.ts compiles (syntax check)

- [ ] Verify TypeScript syntax is valid

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && npx tsc --noEmit plugin/index.ts 2>&1 || echo "Note: TypeScript check may need SDK types. Verify the file manually if tsc is not configured."
```

If `tsc` is not configured for this project, manually verify the file has no syntax errors by checking bracket matching:

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -c "
import re
text = open('plugin/index.ts').read()
opens = text.count('{') + text.count('(') + text.count('[')
closes = text.count('}') + text.count(')') + text.count(']')
print(f'Opens: {opens}, Closes: {closes}, Balanced: {opens == closes}')
assert opens == closes, 'Brackets are not balanced!'
print('Syntax check passed (bracket balance)')
"
```

**Expected output:** `Syntax check passed (bracket balance)`

### Step 5.6: Commit

- [ ] Commit tool registrations

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo
git add plugin/index.ts
git commit -m "$(cat <<'EOF'
feat: register brain-resolve, memory-kpi, vault-optimize agent tools

Add 3 new agent tools to index.ts:
- lacp_brain_resolve: resolve contradictions/supersessions in knowledge notes
- lacp_memory_kpi: report vault quality metrics
- lacp_vault_optimize: apply memory-centric Obsidian graph defaults
Tool count updated from 6 to 9.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Update INSTALL.sh

Add the new bin scripts to the copy list and add a lib/ copy section so the Python modules are available at the installed path.

### Step 6.1: Add lib/ copy section to INSTALL.sh

- [ ] Add lib directory copy to `setup_plugin_directory()`

In `/Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh`, find the block that copies bin scripts (around line 523-531):

```bash
        # Bin scripts
        if [ -d "$SCRIPT_DIR/plugin/bin" ]; then
            mkdir -p "$PLUGIN_PATH/bin"
            cp "$SCRIPT_DIR/plugin/bin"/openclaw-* "$PLUGIN_PATH/bin/" 2>/dev/null || true
            chmod +x "$PLUGIN_PATH/bin"/* 2>/dev/null || true
            local bin_count
            bin_count=$(ls -1 "$PLUGIN_PATH/bin"/ 2>/dev/null | wc -l | tr -d ' ')
            log_success "Bin scripts installed ($bin_count executables)"
        fi
```

Insert the following block immediately AFTER the bin scripts block (after line 531) and BEFORE the config block (line 533):

```bash
        # Lib modules (Python)
        if [ -d "$SCRIPT_DIR/plugin/lib" ]; then
            mkdir -p "$PLUGIN_PATH/lib"
            cp "$SCRIPT_DIR/plugin/lib"/*.py "$PLUGIN_PATH/lib/" 2>/dev/null || true
            if [ -d "$SCRIPT_DIR/plugin/lib/tests" ]; then
                mkdir -p "$PLUGIN_PATH/lib/tests"
                cp "$SCRIPT_DIR/plugin/lib/tests"/*.py "$PLUGIN_PATH/lib/tests/" 2>/dev/null || true
            fi
            local lib_count
            lib_count=$(ls -1 "$PLUGIN_PATH/lib"/*.py 2>/dev/null | wc -l | tr -d ' ')
            log_success "Lib modules installed ($lib_count Python modules)"
        fi
```

### Step 6.2: Update the validation section

- [ ] Find the validation/summary section in INSTALL.sh and ensure the new bin scripts are counted

The existing bin copy line (`cp "$SCRIPT_DIR/plugin/bin"/openclaw-* "$PLUGIN_PATH/bin/"`) already uses a glob pattern that matches all `openclaw-*` files. Since our new scripts are named `openclaw-brain-resolve`, `openclaw-memory-kpi`, and `openclaw-obsidian-optimize`, they will be copied automatically. No changes needed to the glob pattern.

Verify by running:

```bash
ls /Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-* | wc -l
```

**Expected output:** `28` (25 original + 3 new scripts)

### Step 6.3: Commit

- [ ] Commit INSTALL.sh updates

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo
git add INSTALL.sh
git commit -m "$(cat <<'EOF'
chore: add lib/ module copy and new bin scripts to INSTALL.sh

INSTALL.sh now copies plugin/lib/*.py to the install directory so that
brain-expand --consolidate/--activate can import the Python modules.
New bin scripts (brain-resolve, memory-kpi, obsidian-optimize) are
picked up automatically by the existing openclaw-* glob pattern.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Run full test suite and commit

### Step 7.1: Run all new tests

- [ ] Run the complete test suite for all new code

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/bin/tests/test_brain_resolve.py plugin/bin/tests/test_memory_kpi.py plugin/bin/tests/test_obsidian_optimize.py plugin/bin/tests/test_brain_expand_mycelium.py -v
```

**Expected output:** All tests pass (6 + 5 + 5 + 3 = 19 tests).

### Step 7.2: Run existing mycelium tests to verify no regressions

- [ ] Run existing mycelium test suite

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && python3 -m pytest plugin/lib/tests/test_mycelium.py -v
```

**Expected output:** All existing mycelium tests still pass.

### Step 7.3: Verify all bin scripts are executable

- [ ] Check executable permissions

```bash
ls -la /Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-brain-resolve /Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-memory-kpi /Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-obsidian-optimize
```

**Expected output:** All three files show `-rwxr-xr-x` (or similar executable permissions).

### Step 7.4: Verify tool count in index.ts

- [ ] Confirm tool count is 9

```bash
grep "toolCount" /Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/index.ts
```

**Expected output:** `const toolCount = 9;`

### Step 7.5: Run smoke test on each new CLI tool

- [ ] Smoke test all three new tools

```bash
# brain-resolve: verify --help works
python3 /Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-brain-resolve --help > /dev/null && echo "brain-resolve: OK"

# memory-kpi: verify --help works
python3 /Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-memory-kpi --help > /dev/null && echo "memory-kpi: OK"

# obsidian-optimize: verify --help works
python3 /Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-obsidian-optimize --help > /dev/null && echo "obsidian-optimize: OK"

# brain-expand: verify new flags appear in help
bash /Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-brain-expand --help 2>&1 | grep -q "consolidate" && echo "brain-expand --consolidate: OK"
bash /Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/openclaw-brain-expand --help 2>&1 | grep -q "activate" && echo "brain-expand --activate: OK"
```

**Expected output:**
```
brain-resolve: OK
memory-kpi: OK
obsidian-optimize: OK
brain-expand --consolidate: OK
brain-expand --activate: OK
```

---

## Summary of files created/modified

### New files:
| File | Purpose |
|------|---------|
| `plugin/bin/openclaw-brain-resolve` | Contradiction/supersession resolution CLI (168 lines, Python) |
| `plugin/bin/openclaw-memory-kpi` | Vault quality metrics CLI (111 lines, Python) |
| `plugin/bin/openclaw-obsidian-optimize` | Obsidian graph physics tuning CLI (89 lines, Python) |
| `plugin/bin/tests/__init__.py` | Test package marker |
| `plugin/bin/tests/test_brain_resolve.py` | Tests for brain-resolve (6 test classes) |
| `plugin/bin/tests/test_memory_kpi.py` | Tests for memory-kpi (5 test classes) |
| `plugin/bin/tests/test_obsidian_optimize.py` | Tests for obsidian-optimize (5 test classes) |
| `plugin/bin/tests/test_brain_expand_mycelium.py` | Tests for --consolidate/--activate flags (3 test classes) |

### Modified files:
| File | Change |
|------|--------|
| `plugin/bin/openclaw-brain-expand` | Added --consolidate, --activate, --json flags; mycelium pipeline dispatch |
| `plugin/index.ts` | Added 3 tool registrations (lacp_brain_resolve, lacp_memory_kpi, lacp_vault_optimize); toolCount 6->9 |
| `INSTALL.sh` | Added lib/ module copy section for Python modules |

### Existing files used (not modified):
| File | Role |
|------|------|
| `plugin/lib/mycelium.py` | Spreading activation, FSRS, reinforcement, healing, flow score |
| `plugin/lib/consolidation.py` | Full consolidation pipeline |
| `plugin/lib/review_queue.py` | FSRS review queue generation |
| `plugin/lib/knowledge_gaps.py` | Cross-category gap detection |
