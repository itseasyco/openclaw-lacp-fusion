#!/usr/bin/env python3
"""
PreToolGuard Hook for OpenClaw

Blocks dangerous command patterns before execution:
- npm publish, git reset --hard, docker --privileged
- curl|python pipes, fork bombs, scp to /root
- Protected file access (.env, secrets, PEM keys)

Implements TTL-based approval caching (12h default) using OpenClaw session IDs.
Configuration is loaded from guard-rules.json with mtime-based caching.
All matches (block, warn, log) are written to guard-blocks.jsonl.
"""

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, Dict, List, Any

# ============================================================================
# Path Resolution
# ============================================================================

def _resolve_plugin_dir() -> Path:
    """Resolve the plugin directory from env var or default."""
    env_dir = os.getenv("OPENCLAW_PLUGIN_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    return Path.home() / ".openclaw" / "extensions" / "openclaw-lacp-fusion"


PLUGIN_DIR = _resolve_plugin_dir()
CONFIG_PATH = PLUGIN_DIR / "config" / "guard-rules.json"
BLOCK_LOG_PATH = PLUGIN_DIR / "logs" / "guard-blocks.jsonl"

# ============================================================================
# Configuration Defaults (fallback if guard-rules.json not found)
# ============================================================================

DEFAULT_TTL_SECONDS = 12 * 3600  # 12 hours
APPROVAL_CACHE_DIR = Path.home() / ".openclaw" / "approval-cache"

# Hardcoded fallback patterns (used when guard-rules.json is missing)
_FALLBACK_DANGEROUS_PATTERNS = [
    (re.compile(r"\b(?:npm|yarn|pnpm|cargo)\s+publish\b", re.IGNORECASE),
     "npm-publish",
     "npm publish, yarn publish, etc.",
     "BLOCKED: Publishing to registry requires explicit user approval. Ask the user first."),

    (re.compile(r"\b(?:curl|wget)\b.*\|\s*(?:python3?|node|ruby|perl)\b", re.IGNORECASE),
     "curl-pipe-interpreter",
     "curl|python pipes (network-to-interpreter)",
     "BLOCKED: Piping network content to an interpreter is unsafe. Download first, review, then run."),

    (re.compile(r"\bchmod\s+(?:-R\s+)?777\b"),
     "chmod-777",
     "chmod 777 (overly permissive)",
     "BLOCKED: chmod 777 is overly permissive. Use specific permissions (e.g. 755, 644)."),

    (re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE),
     "git-reset-hard",
     "git reset --hard",
     "BLOCKED: git reset --hard is destructive. Ask the user first."),

    (re.compile(r"\bgit\s+clean\s+-f", re.IGNORECASE),
     "git-clean-force",
     "git clean -f",
     "BLOCKED: git clean -f is destructive. Ask the user first."),

    (re.compile(r"\bdocker\s+run\b[^\n\r]*--privileged\b", re.IGNORECASE),
     "docker-privileged",
     "docker run --privileged",
     "BLOCKED: docker run --privileged is a security risk. Use specific capabilities instead."),

    (re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
     "fork-bomb",
     "fork bomb",
     "BLOCKED: Fork bomb detected."),

    (re.compile(r"\b(?:scp|rsync)\b.*[\s:/]/root(?:/|$|\s)", re.IGNORECASE),
     "scp-rsync-root",
     "scp/rsync to /root",
     "BLOCKED: scp/rsync to /root is restricted. Use a non-root target path."),

    (re.compile(r"\b(?:curl|wget)\b.*(?:-d|--data|--data-binary)\s+@[^\s]*(?:\.env|\.ssh|credentials|\.key|\.pem|secrets)", re.IGNORECASE),
     "data-exfiltration",
     "data exfiltration from sensitive files",
     "BLOCKED: potential data exfiltration from sensitive file."),
]

_FALLBACK_PROTECTED_PATHS = re.compile(
    r"(\.env($|\.)|config\.toml($|\.)|(?:^|/)secret(?:s)?(?:/|$|\.)|\.claude/settings\.json$|authorized_keys$"
    r"|\.(pem|key)$|(^|/)\.gnupg(/|$))",
    re.IGNORECASE
)

# ============================================================================
# Guard Rules Config Loader (mtime-cached)
# ============================================================================

_config_cache: Dict[str, Any] = {
    "mtime": 0.0,
    "data": None,
    "compiled_rules": None,
    "compiled_path_rules": None,
}


def _parse_regex_flags(flags_str: str) -> int:
    """Convert flags string like 'IGNORECASE' to re module flags."""
    if not flags_str:
        return 0
    flag_map = {
        "IGNORECASE": re.IGNORECASE,
        "MULTILINE": re.MULTILINE,
        "DOTALL": re.DOTALL,
        "VERBOSE": re.VERBOSE,
    }
    result = 0
    for part in flags_str.split("|"):
        part = part.strip().upper()
        if part in flag_map:
            result |= flag_map[part]
    return result


def _load_guard_config() -> Optional[Dict]:
    """
    Load guard-rules.json with mtime-based caching.
    Returns None if file doesn't exist or is invalid.
    """
    if not CONFIG_PATH.exists():
        _config_cache["data"] = None
        _config_cache["compiled_rules"] = None
        _config_cache["compiled_path_rules"] = None
        return None

    try:
        current_mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        return _config_cache.get("data")

    if current_mtime == _config_cache["mtime"] and _config_cache["data"] is not None:
        return _config_cache["data"]

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        _config_cache["mtime"] = current_mtime
        _config_cache["data"] = data
        # Invalidate compiled caches so they get rebuilt
        _config_cache["compiled_rules"] = None
        _config_cache["compiled_path_rules"] = None
        return data
    except Exception as e:
        print(f"WARNING: Failed to load guard-rules.json: {e}", file=sys.stderr)
        return _config_cache.get("data")


def _get_compiled_rules(config: Dict) -> List[Tuple[re.Pattern, str, str, str, str]]:
    """
    Compile rules from config into (pattern, rule_id, label, message, category) tuples.
    Uses cache if available.
    """
    if _config_cache["compiled_rules"] is not None:
        return _config_cache["compiled_rules"]

    compiled = []
    for rule in config.get("rules", []):
        if not rule.get("enabled", True):
            continue
        try:
            flags = _parse_regex_flags(rule.get("flags", ""))
            pattern = re.compile(rule["pattern"], flags)
            compiled.append((
                pattern,
                rule["id"],
                rule.get("label", rule["id"]),
                rule.get("message", f"Blocked by rule: {rule['id']}"),
                rule.get("category", ""),
            ))
        except (re.error, KeyError) as e:
            print(f"WARNING: Skipping invalid rule '{rule.get('id', '?')}': {e}", file=sys.stderr)

    _config_cache["compiled_rules"] = compiled
    return compiled


def _get_command_rules(config: Dict) -> List[Tuple[re.Pattern, str, str, str, str]]:
    """Get only command-category rules (non protected-path)."""
    all_rules = _get_compiled_rules(config)
    return [(p, rid, label, msg, cat) for p, rid, label, msg, cat in all_rules if cat != "protected-path"]


def _get_path_rules(config: Dict) -> List[Tuple[re.Pattern, str, str, str, str]]:
    """Get only protected-path-category rules."""
    all_rules = _get_compiled_rules(config)
    return [(p, rid, label, msg, cat) for p, rid, label, msg, cat in all_rules if cat == "protected-path"]


# ============================================================================
# Repo Path Resolution
# ============================================================================


def _resolve_repo_path(payload: Dict) -> Optional[str]:
    """
    Resolve the current repo path from payload or cwd by looking for .git.
    Returns absolute path to the repo root or None.
    """
    # Try to get from payload
    tool_input = payload.get("tool_input", {})
    start_dir = tool_input.get("cwd", "") or tool_input.get("file_path", "")

    if start_dir:
        search_path = Path(start_dir).expanduser().resolve()
        if search_path.is_file():
            search_path = search_path.parent
    else:
        search_path = Path.cwd()

    # Walk up to find .git
    current = search_path
    for _ in range(50):  # safety limit
        if (current / ".git").exists():
            return str(current)
        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


# ============================================================================
# Allowlist Checking
# ============================================================================


def _check_command_allowlist(cmd: str, config: Dict, repo_path: Optional[str]) -> bool:
    """
    Check if command matches any allowlist entry (global + repo-specific).
    Returns True if command is explicitly allowed.
    """
    allowlists = [config.get("command_allowlist", [])]

    if repo_path:
        repo_overrides = config.get("repo_overrides", {})
        repo_config = repo_overrides.get(repo_path, {})
        allowlists.append(repo_config.get("command_allowlist", []))

    for allowlist in allowlists:
        for entry in allowlist:
            pattern_str = entry.get("pattern", "")
            if not pattern_str:
                continue
            try:
                if re.search(pattern_str, cmd):
                    return True
            except re.error:
                # Try exact match as fallback
                if pattern_str == cmd:
                    return True

    return False


def _check_path_allowlist(file_path: str, config: Dict, repo_path: Optional[str]) -> bool:
    """
    Check if file path matches any path allowlist entry (global + repo-specific).
    Returns True if path is explicitly allowed.
    """
    allowlists = [config.get("path_allowlist", [])]

    if repo_path:
        repo_overrides = config.get("repo_overrides", {})
        repo_config = repo_overrides.get(repo_path, {})
        allowlists.append(repo_config.get("path_allowlist", []))

    for allowlist in allowlists:
        for entry in allowlist:
            pattern_str = entry.get("pattern", "")
            if not pattern_str:
                continue
            try:
                if re.search(pattern_str, file_path):
                    return True
            except re.error:
                if pattern_str in file_path:
                    return True

    return False


# ============================================================================
# Block Level Resolution
# ============================================================================


def _resolve_block_level(rule_id: str, rule_block_level: str, config: Dict, repo_path: Optional[str]) -> str:
    """
    Resolve the effective block_level for a matched rule.

    Resolution order:
    1. repo_overrides[repo].rules_override[rule_id].block_level
    2. repo_overrides[repo].block_level
    3. rule's own block_level
    4. defaults.block_level
    """
    defaults = config.get("defaults", {})
    default_level = defaults.get("block_level", "block")

    if repo_path:
        repo_overrides = config.get("repo_overrides", {})
        repo_config = repo_overrides.get(repo_path, {})

        if repo_config:
            # Check rule-specific override
            rules_override = repo_config.get("rules_override", {})
            rule_override = rules_override.get(rule_id, {})
            if "block_level" in rule_override:
                return rule_override["block_level"]

            # Check repo-level override
            if "block_level" in repo_config:
                return repo_config["block_level"]

    # Rule's own block_level
    if rule_block_level:
        return rule_block_level

    return default_level


def _is_rule_enabled(rule_id: str, config: Dict, repo_path: Optional[str]) -> bool:
    """Check if a rule is enabled, considering repo overrides."""
    if repo_path:
        repo_overrides = config.get("repo_overrides", {})
        repo_config = repo_overrides.get(repo_path, {})
        if repo_config:
            rules_override = repo_config.get("rules_override", {})
            rule_override = rules_override.get(rule_id, {})
            if "enabled" in rule_override:
                return rule_override["enabled"]
    return True  # Default enabled (already filtered at compile time)


# ============================================================================
# Block Log Writer
# ============================================================================


def _write_block_log(
    rule_id: str,
    label: str,
    command: str,
    action_taken: str,
    block_level: str,
    session_id: str,
    repo_path: Optional[str],
) -> None:
    """Append an entry to the guard-blocks.jsonl log file."""
    try:
        BLOCK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "rule_id": rule_id,
            "label": label,
            "command": command,
            "action_taken": action_taken,
            "block_level": block_level,
            "session_id": session_id,
            "repo": repo_path or "",
            "agent_id": os.getenv("OPENCLAW_AGENT_ID", ""),
        }
        with open(BLOCK_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")
    except Exception as e:
        print(f"WARNING: Failed to write block log: {e}", file=sys.stderr)


# ============================================================================
# Session ID Resolution (OpenClaw-specific, replacing TMUX_PANE)
# ============================================================================


def _get_session_id() -> str:
    """
    Resolve OpenClaw session ID for approval caching scope.

    Priority:
    1. Explicit OPENCLAW_SESSION_ID environment variable
    2. Fallback to other terminal/window identifiers
    3. Fallback to CWD hash if no session available

    Returns a unique, stable session identifier.
    """
    # Explicit OpenClaw session ID
    explicit = os.getenv("OPENCLAW_SESSION_ID", "").strip()
    if explicit:
        return explicit

    # Try other terminal identifiers
    for key in ("TMUX_PANE", "WEZTERM_PANE", "ITERM_SESSION_ID", "TERM_SESSION_ID", "WINDOWID"):
        val = os.getenv(key, "").strip()
        if val:
            return f"{key}:{val}"

    # Fallback to CWD hash
    cwd = os.getcwd()
    digest = hashlib.sha1(cwd.encode("utf-8")).hexdigest()[:12]
    return f"cwd:{digest}"


# ============================================================================
# Approval Cache (TTL-based)
# ============================================================================


def _get_approval_key(session_id: str, pattern_name: str) -> str:
    """Generate unique key for approval cache entry."""
    key_data = f"{session_id}:{pattern_name}"
    digest = hashlib.sha256(key_data.encode()).hexdigest()[:16]
    return f"session_{digest}"


def _approval_cache_path(session_id: str, pattern_name: str) -> Path:
    """Get file path for approval cache entry."""
    key = _get_approval_key(session_id, pattern_name)
    return APPROVAL_CACHE_DIR / f"{key}.json"


def _is_approved(session_id: str, pattern_name: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool:
    """
    Check if a dangerous pattern was previously approved in this session.

    Returns True if approval exists and is still valid (within TTL).
    Returns False if no approval or approval expired.
    """
    cache_path = _approval_cache_path(session_id, pattern_name)
    if not cache_path.exists():
        return False

    try:
        cache_data = json.loads(cache_path.read_text())
        approved_at = cache_data.get("approved_at", 0)
        now = time.time()
        age = now - approved_at
        return age < ttl_seconds
    except Exception:
        return False


def _mark_approved(session_id: str, pattern_name: str) -> None:
    """Mark a pattern as approved in this session."""
    APPROVAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _approval_cache_path(session_id, pattern_name)
    cache_data = {
        "pattern": pattern_name,
        "session_id": session_id,
        "approved_at": int(time.time()),
        "approved_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ttl_seconds": DEFAULT_TTL_SECONDS,
    }
    cache_path.write_text(json.dumps(cache_data, indent=2) + "\n")


# ============================================================================
# Payload Parsing
# ============================================================================


def _read_payload() -> Dict:
    """Read and parse JSON payload from stdin."""
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except Exception as e:
        print(f"WARNING: Failed to parse payload: {e}", file=sys.stderr)
        return {}


def _get_command(payload: Dict) -> str:
    """Extract command from tool payload."""
    # Handle OpenClaw tool_input format
    tool_input = payload.get("tool_input", {})
    cmd = tool_input.get("command", "")
    return str(cmd) if cmd else ""


def _get_file_path(payload: Dict) -> str:
    """Extract file path from tool payload."""
    tool_input = payload.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return ""
    try:
        return str(Path(file_path).expanduser().resolve())
    except Exception:
        return str(file_path)


# ============================================================================
# Dangerous Pattern Detection (config-driven with fallback)
# ============================================================================


def _detect_dangerous_command(cmd: str, session_id: str, payload: Dict) -> Tuple[int, Optional[str]]:
    """
    Check command against dangerous patterns from config or fallback.

    Returns:
        (0, None) if safe or allowed
        (1, error_msg) if blocked
        (0, None) if warn or log (with side effects: log + stderr)
    """
    if not cmd.strip():
        return 0, None

    config = _load_guard_config()
    repo_path = _resolve_repo_path(payload)

    if config is not None:
        return _detect_with_config(cmd, session_id, config, repo_path)
    else:
        return _detect_with_fallback(cmd, session_id, repo_path)


def _detect_with_config(cmd: str, session_id: str, config: Dict, repo_path: Optional[str]) -> Tuple[int, Optional[str]]:
    """Check command against config-driven rules."""
    # Step 1: Check command allowlist
    if _check_command_allowlist(cmd, config, repo_path):
        return 0, None

    # Step 2: Check command against enabled rules (non-path rules only)
    command_rules = _get_command_rules(config)
    ttl = config.get("defaults", {}).get("ttl_seconds", DEFAULT_TTL_SECONDS)
    log_blocks = config.get("defaults", {}).get("log_blocks", True)

    for pattern, rule_id, label, message, category in command_rules:
        if not _is_rule_enabled(rule_id, config, repo_path):
            continue

        if pattern.search(cmd):
            # Check approval cache
            if _is_approved(session_id, label, ttl):
                print(f"[pretool-guard] Pattern '{label}' approved in this session (cached)", file=sys.stderr)
                return 0, None

            # Resolve block_level from rule config
            rule_cfg_level = ""
            for r in config.get("rules", []):
                if r.get("id") == rule_id:
                    rule_cfg_level = r.get("block_level", "")
                    break

            block_level = _resolve_block_level(rule_id, rule_cfg_level, config, repo_path)

            # Log for all match types
            if log_blocks:
                _write_block_log(rule_id, label, cmd, block_level, block_level, session_id, repo_path)

            if block_level == "block":
                return 1, f"BLOCKED: {message}"
            elif block_level == "warn":
                print(f"[pretool-guard] WARNING: {message} (rule: {rule_id})", file=sys.stderr)
                return 0, None
            elif block_level == "log":
                # Silent log only
                return 0, None
            else:
                # Unknown level, default to block for safety
                return 1, f"BLOCKED: {message}"

    return 0, None


def _detect_with_fallback(cmd: str, session_id: str, repo_path: Optional[str]) -> Tuple[int, Optional[str]]:
    """Fallback: check command against hardcoded patterns (block_level=block)."""
    for pattern, rule_id, label, error_msg in _FALLBACK_DANGEROUS_PATTERNS:
        if pattern.search(cmd):
            if _is_approved(session_id, label):
                print(f"[pretool-guard] Pattern '{label}' approved in this session (cached)", file=sys.stderr)
                return 0, None

            # Log even in fallback mode
            _write_block_log(rule_id, label, cmd, "block", "block", session_id, repo_path)
            return 1, error_msg

    return 0, None


def _detect_protected_file_access(file_path: str, payload: Dict, session_id: str) -> Tuple[int, Optional[str]]:
    """
    Check if file path matches protected patterns from config or fallback.

    Returns:
        (0, None) if safe
        (1, error_msg) if blocked
        (0, None) if warn/log (with side effects)
    """
    if not file_path:
        return 0, None

    config = _load_guard_config()
    repo_path = _resolve_repo_path(payload)

    if config is not None:
        return _detect_path_with_config(file_path, session_id, config, repo_path)
    else:
        return _detect_path_with_fallback(file_path, repo_path, session_id)


def _detect_path_with_config(file_path: str, session_id: str, config: Dict, repo_path: Optional[str]) -> Tuple[int, Optional[str]]:
    """Check file path against config-driven path rules."""
    # Check path allowlist first
    if _check_path_allowlist(file_path, config, repo_path):
        return 0, None

    path_rules = _get_path_rules(config)
    log_blocks = config.get("defaults", {}).get("log_blocks", True)

    for pattern, rule_id, label, message, category in path_rules:
        if not _is_rule_enabled(rule_id, config, repo_path):
            continue

        if pattern.search(file_path):
            # Resolve block_level
            rule_cfg_level = ""
            for r in config.get("rules", []):
                if r.get("id") == rule_id:
                    rule_cfg_level = r.get("block_level", "")
                    break

            block_level = _resolve_block_level(rule_id, rule_cfg_level, config, repo_path)

            if log_blocks:
                _write_block_log(rule_id, label, file_path, block_level, block_level, session_id, repo_path)

            if block_level == "block":
                return 1, f"BLOCKED: Protected file access: {file_path}\n{message}"
            elif block_level == "warn":
                print(f"[pretool-guard] WARNING: {message} ({file_path})", file=sys.stderr)
                return 0, None
            elif block_level == "log":
                return 0, None
            else:
                return 1, f"BLOCKED: Protected file access: {file_path}\n{message}"

    return 0, None


def _detect_path_with_fallback(file_path: str, repo_path: Optional[str], session_id: str) -> Tuple[int, Optional[str]]:
    """Fallback: check file path against hardcoded protected patterns."""
    if _FALLBACK_PROTECTED_PATHS.search(file_path):
        _write_block_log("protected-path", "protected file", file_path, "block", "block", session_id, repo_path)
        return 1, (
            f"BLOCKED: Protected file access: {file_path}\n"
            f"This file contains sensitive data and cannot be modified via this interface."
        )
    return 0, None


# ============================================================================
# Main Guard Logic
# ============================================================================


def run_command_guard(payload: Dict) -> Tuple[int, Optional[str]]:
    """
    Guard for pre-tool-use commands.

    Returns: (exit_code, error_message_or_none)
      0 = allowed
      1 = blocked (dangerous)
      2 = error
    """
    cmd = _get_command(payload)
    session_id = _get_session_id()

    exit_code, error = _detect_dangerous_command(cmd, session_id, payload)
    return exit_code, error


def run_file_guard(payload: Dict) -> Tuple[int, Optional[str]]:
    """
    Guard for file write/read operations.

    Returns: (exit_code, error_message_or_none)
      0 = allowed
      1 = blocked (protected)
      2 = error
    """
    file_path = _get_file_path(payload)
    session_id = _get_session_id()

    exit_code, error = _detect_protected_file_access(file_path, payload, session_id)
    return exit_code, error


# ============================================================================
# CLI Interface
# ============================================================================


def main() -> int:
    """Main entry point for hook."""
    if len(sys.argv) < 2:
        print("Usage: pretool-guard.py <command|file> [payload.json]", file=sys.stderr)
        print("  command - check command before execution", file=sys.stderr)
        print("  file    - check file before read/write", file=sys.stderr)
        return 2

    mode = sys.argv[1].strip().lower()
    payload = _read_payload()

    if mode == "command":
        exit_code, error = run_command_guard(payload)
        if error:
            print(error, file=sys.stderr)
        return exit_code

    elif mode == "file":
        exit_code, error = run_file_guard(payload)
        if error:
            print(error, file=sys.stderr)
        return exit_code

    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
