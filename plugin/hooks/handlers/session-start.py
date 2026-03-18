#!/usr/bin/env python3
"""OpenClaw SessionStart hook — git context injection for agent sessions.

Injects git context, detects + caches test commands, handles session matchers,
and outputs JSON with systemMessage protocol.

Hook protocol:
  - exit 0 with {"systemMessage": "..."} → inject system context
  - exit 0 with no output → no-op
  - exit 1 → hook error (logged but doesn't block session start)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def _read_payload() -> dict:
    """Read hook payload from stdin (JSON format)."""
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}


def _is_git_repo() -> bool:
    """Check if current directory is inside a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=os.getcwd(),
        )
        return result.returncode == 0
    except Exception:
        return False


def _git_branch() -> str | None:
    """Get current git branch name."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=os.getcwd(),
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def _git_recent_commits(count: int = 3) -> str | None:
    """Get recent commit history in oneline format."""
    try:
        result = subprocess.run(
            ["git", "log", f"--oneline", f"-{count}"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=os.getcwd(),
        )
        return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None
    except Exception:
        return None


def _git_modified_files() -> str | None:
    """Get list of modified (unstaged) files."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=os.getcwd(),
        )
        return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None
    except Exception:
        return None


def _git_staged_files() -> str | None:
    """Get list of staged files (added to index)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=os.getcwd(),
        )
        return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None
    except Exception:
        return None


def _git_status_summary() -> str | None:
    """Get git status summary (clean/dirty/staged)."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=os.getcwd(),
        )
        if result.returncode != 0:
            return None
        
        lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
        if not lines or not lines[0]:
            return "clean"
        
        staged = sum(1 for line in lines if line.startswith(('A ', 'M ', 'D ', 'R ', 'C ')))
        modified = sum(1 for line in lines if line.startswith((' M', ' D')))
        untracked = sum(1 for line in lines if line.startswith('??'))
        
        parts = []
        if staged > 0:
            parts.append(f"{staged} staged")
        if modified > 0:
            parts.append(f"{modified} modified")
        if untracked > 0:
            parts.append(f"{untracked} untracked")
        
        return ", ".join(parts) if parts else "clean"
    except Exception:
        return None


def _git_context() -> dict[str, str]:
    """Gather comprehensive git context."""
    context = {}
    
    branch = _git_branch()
    if branch:
        context["branch"] = branch
    
    commits = _git_recent_commits(3)
    if commits:
        context["recentCommits"] = commits
    
    modified = _git_modified_files()
    if modified:
        context["modifiedFiles"] = modified
    
    staged = _git_staged_files()
    if staged:
        context["stagedFiles"] = staged
    
    status = _git_status_summary()
    if status:
        context["status"] = status
    
    return context


def _detect_test_command() -> str | None:
    """Auto-detect test command from project files in cwd."""
    cwd = Path(os.getcwd())

    # Check package.json (Node.js projects)
    pkg_json = cwd / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text())
            scripts = pkg.get("scripts", {})
            if "test" in scripts:
                # Try to find best runner in order of preference
                for runner in ("bun", "pnpm", "yarn", "npm"):
                    try:
                        subprocess.run(
                            ["which", runner],
                            capture_output=True,
                            timeout=3,
                            check=True,
                        )
                        return f"{runner} test"
                    except Exception:
                        continue
        except (json.JSONDecodeError, OSError):
            pass

    # Check Makefile
    if (cwd / "Makefile").exists():
        try:
            content = (cwd / "Makefile").read_text()
            if re.search(r"^test\s*:", content, re.MULTILINE):
                return "make test"
        except OSError:
            pass

    # Check Rust (Cargo.toml)
    if (cwd / "Cargo.toml").exists():
        return "cargo test"

    # Check Python (pyproject.toml)
    if (cwd / "pyproject.toml").exists():
        try:
            # Try pytest first, then unittest
            subprocess.run(["which", "pytest"], capture_output=True, timeout=3, check=True)
            return "pytest"
        except Exception:
            return "python3 -m pytest"

    # Check Go (go.mod)
    if (cwd / "go.mod").exists():
        return "go test ./..."

    return None


def _cache_test_command(cmd: str) -> None:
    """Write test command to /tmp for stop hook to pick up later."""
    session_id = os.getenv("OPENCLAW_SESSION_ID", os.getenv("CLAUDE_SESSION_ID", "default"))
    path = Path(f"/tmp/openclaw-session-test-cmd-{session_id}")
    try:
        path.write_text(cmd)
    except OSError:
        pass


def _format_git_context(git_ctx: dict[str, str]) -> str:
    """Format git context as readable text."""
    lines = ["=== Git Context ==="]
    
    if "branch" in git_ctx:
        lines.append(f"Branch: {git_ctx['branch']}")
    
    if "status" in git_ctx:
        lines.append(f"Status: {git_ctx['status']}")
    
    if "recentCommits" in git_ctx:
        lines.append(f"\nRecent commits:\n{git_ctx['recentCommits']}")
    
    if "stagedFiles" in git_ctx:
        lines.append(f"\nStaged files:\n{git_ctx['stagedFiles']}")
    
    if "modifiedFiles" in git_ctx:
        lines.append(f"\nModified files:\n{git_ctx['modifiedFiles']}")
    
    return "\n".join(lines)


def _inject_lacp_context() -> str | None:
    """Inject top LACP facts via openclaw-lacp-context auto-inject.

    Calls the CLI to get top-3 relevant facts from LACP persistent memory
    and returns them as a formatted context string.
    """
    # Determine project name from git remote or cwd
    project = None
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
            cwd=os.getcwd(),
        )
        if result.returncode == 0 and result.stdout.strip():
            # Extract repo name from URL
            url = result.stdout.strip()
            project = url.rstrip("/").split("/")[-1].replace(".git", "")
    except Exception:
        pass

    if not project:
        project = Path(os.getcwd()).name

    # Find the context CLI
    plugin_bin = Path(__file__).parent.parent / "bin" if Path(__file__).parent.name == "handlers" else None
    if not plugin_bin:
        # Try relative to hooks dir
        plugin_bin = Path(__file__).resolve().parent.parent / "bin"

    context_cmd = plugin_bin / "openclaw-lacp-context" if plugin_bin else None

    if not context_cmd or not context_cmd.exists():
        # Try in PATH
        try:
            subprocess.run(["which", "openclaw-lacp-context"],
                           capture_output=True, check=True, timeout=3)
            context_cmd_str = "openclaw-lacp-context"
        except Exception:
            return None
    else:
        context_cmd_str = str(context_cmd)

    session_id = os.getenv("OPENCLAW_SESSION_ID", os.getenv("CLAUDE_SESSION_ID", "default"))

    try:
        result = subprocess.run(
            [context_cmd_str, "auto-inject",
             "--project", project,
             "--max-facts", "3",
             "--session-id", session_id,
             "--format", "text"],
            capture_output=True, text=True, timeout=10,
            cwd=os.getcwd(),
        )
        if result.returncode == 0 and result.stdout.strip():
            facts = result.stdout.strip()
            if facts:
                lines = ["=== LACP Memory Context ===",
                         f"Project: {project}",
                         ""]
                for line in facts.split("\n"):
                    if line.strip():
                        lines.append(f"  • {line.strip()}")
                lines.append("")
                return "\n".join(lines)
    except Exception:
        pass

    return None


def _store_injection_metadata(lacp_ctx: str) -> None:
    """Store LACP injection metadata to context.json for tracking usage."""
    session_id = os.getenv("OPENCLAW_SESSION_ID", os.getenv("CLAUDE_SESSION_ID", "default"))
    memory_root = Path(os.getenv("OPENCLAW_MEMORY_ROOT", str(Path.home() / ".openclaw" / "memory")))
    context_file = memory_root / "context.json"

    try:
        # Load existing context
        context: dict = {}
        if context_file.exists():
            context = json.loads(context_file.read_text())

        # Parse facts from the injected context string
        facts = []
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        for line in lacp_ctx.split("\n"):
            line = line.strip()
            if line.startswith("•") or line.startswith("- "):
                fact_text = line.lstrip("•- ").strip()
                if fact_text:
                    facts.append({
                        "fact": fact_text,
                        "source": "lacp-context-inject",
                        "timestamp": now,
                        "session_id": session_id,
                        "used": None,
                    })

        if facts:
            context["lacp_injected_facts"] = facts
            memory_root.mkdir(parents=True, exist_ok=True)
            context_file.write_text(json.dumps(context, indent=2, default=str))
    except Exception:
        pass  # Non-critical: don't block session start


def main() -> None:
    payload = _read_payload()
    matcher = payload.get("matcher", "")
    parts: list[str] = []

    # Git context (always, when in a repo)
    if _is_git_repo():
        git_ctx = _git_context()
        if git_ctx:
            parts.append(_format_git_context(git_ctx))

    # Detect and cache test command
    test_cmd = _detect_test_command()
    if test_cmd:
        parts.append(f"\nTest command detected: {test_cmd}")
        _cache_test_command(test_cmd)

    # LACP context injection (v2.0.0) — inject top-3 relevant facts
    lacp_ctx = _inject_lacp_context()
    if lacp_ctx:
        parts.append(f"\n{lacp_ctx}")
        _store_injection_metadata(lacp_ctx)

    # Compact-specific reminder (for sessions resuming after compaction)
    if matcher == "compact":
        parts.append(
            "\n=== Post-Compaction Reminder ===\n"
            "This session was resumed after compaction. Context has been summarized.\n"
            "Before making changes:\n"
            "  • Review git branch and recent commits above\n"
            "  • Verify you understand the current state\n"
            "  • Run tests before and after changes\n"
            "  • Check for modified files that may have been partially completed"
        )

    # Startup reminder (on initial session start)
    if matcher == "startup":
        parts.append(
            "\n=== Session Started ===\n"
            "You're starting a fresh OpenClaw session.\n"
            "Git context and test command have been injected above."
        )

    if parts:
        system_message = "\n".join(parts)
        print(json.dumps({"systemMessage": system_message}))
    else:
        # No context to inject
        print(json.dumps({"systemMessage": "Session started."}))


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except Exception as e:
        # Hook errors should log but not crash the session
        sys.stderr.write(f"session-start hook error: {e}\n")
        sys.exit(1)
