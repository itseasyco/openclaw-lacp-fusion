# openclaw-lacp-fusion — Outstanding Changes

All items discovered during install test on 2026-03-21. Must be completed before distribution.

---

## Section A: Install/Build Fixes (found during test)

### A1. INSTALL.sh — `"source": "local"` -> `"path"`
- **File:** `INSTALL.sh` (update_gateway_config function)
- **Status:** DONE in repo
- Gateway only accepts `npm`, `archive`, or `path` for plugins.installs.*.source

### A2. INSTALL.sh — Generate `package.json`
- **File:** `INSTALL.sh` (setup_plugin_directory function)
- **Status:** PARTIAL — generates package.json but needs final fields
- Must include: `"type": "module"`, `"main": "index.ts"`, `"openclaw": { "extensions": ["./index.ts"] }`
- Gateway uses this to discover and load the plugin

### A3. Add `index.ts` entry point
- **File:** new `plugin/index.ts` template in repo
- **Status:** TODO — only exists in installed extension, not in repo source
- Uses `import type { OpenClawPluginApi } from "openclaw/plugin-sdk"` (NOT `definePluginEntry` — that API doesn't exist in current SDK)
- Must export default object with `register(api)` method
- Registers 4 lifecycle hooks via `api.on()`:
  - `session_start` -> `hooks/handlers/session-start.py`
  - `before_tool_call` -> `hooks/handlers/pretool-guard.py`
  - `agent_end` -> `hooks/handlers/stop-quality-gate.py`
  - `before_message_write` -> `hooks/handlers/write-validate.py`
- Each hook shells out to Python via `execFileSync("python3", [scriptPath], { input: eventJson })`
- Reference implementation: `~/.openclaw/extensions/openclaw-lacp-fusion/index.ts`

### A4. INSTALL.sh — Symlink `openclaw` SDK into `node_modules`
- **Status:** TODO
- The `index.ts` imports `openclaw/plugin-sdk` which must be resolvable
- INSTALL.sh should detect SDK location:
  1. Check other installed plugins: `~/.openclaw/extensions/*/node_modules/openclaw`
  2. Check global openclaw install: `$(which openclaw)/../lib/node_modules/openclaw`
  3. Fail with helpful message if not found
- Create: `$PLUGIN_PATH/node_modules/openclaw -> <detected_sdk_path>`

### A5. `openclaw.plugin.json` — Add `kind` and `name` fields
- **File:** `openclaw.plugin.json` (repo root)
- **Status:** TODO in repo (done in installed copy)
- Add: `"kind": "provider"`, `"name": "OpenClaw LACP Fusion"` at top level

### A6. INSTALL.sh — Post-install health check
- **Status:** TODO
- Run after install completes, before printing summary
- Checks:
  - `package.json` exists with required fields
  - `index.ts` exists
  - `openclaw` SDK resolvable in `node_modules`
  - `openclaw.plugin.json` has `kind` and `name`
  - `openclaw.json` gateway config is valid JSON with plugin entry
  - All 4 hook handler .py files exist and are executable

---

## Section B: Wizard UX Improvements

### B1. INSTALL.sh — Replace `read -r` prompts with `gum` (with fallback)
- **Status:** DONE in repo
- `gum` provides arrow-key selection, file browser, confirm dialogs
- Falls back to numbered-list + `read` when `gum` not installed
- Added `prompt_browse_directory()` helper

### B2. INSTALL.sh — Obsidian vault auto-detection
- **Status:** DONE in repo
- Removed hardcoded `/Volumes/Cortex` path
- Scans common locations for `.obsidian/` directories (the marker Obsidian creates)
- macOS: `~/Documents`, `~/Library/Mobile Documents`, `~/Desktop`, `$HOME`, `/Volumes/*`
- Linux: `~/Documents`, `~/Desktop`, `$HOME`
- Shows found vaults as selectable options + browse/type/skip

### B3. INSTALL.sh — Inline descriptions for choice options
- **Status:** DONE in extracted copy, DONE in repo
- Context engine, safety profile, and policy tier choices show descriptions inline

---

## Section C: New Profiles

### C1. `autonomous` profile
- **Status:** TODO
- All 4 hooks enabled
- pretool-guard: `block_level: "warn"` (logs but does not block)
- stop-quality-gate: allows stop with warning, does not block
- Use case: Andrew's daily driver, autonomous agents that should keep working

### C2. `context-only` profile
- **Status:** TODO
- Only `session-start` enabled
- No safety gates at all
- Use case: lightest touch, just inject git context

### C3. `guard-rail` profile
- **Status:** TODO
- `pretool-guard` + `stop-quality-gate` enabled
- No context injection, no write validation
- Use case: safety without context overhead

### C4. `full-audit` profile
- **Status:** TODO
- All 4 hooks enabled
- Extra verbose logging
- Provenance tracking cranked up
- Use case: compliance, paper trails, audit scenarios

---

## Section D: Guard System Overhaul (new feature)

### D1. Guard config file structure
- **Location:** `~/.openclaw/extensions/openclaw-lacp-fusion/config/guard-rules.json`
- **Purpose:** Stores all guard rules, their state, allowlists, and block levels
- **Structure:**
```json
{
  "version": "1.0.0",
  "defaults": {
    "block_level": "block",
    "ttl_seconds": 43200,
    "log_blocks": true
  },
  "rules": [
    {
      "id": "npm-publish",
      "pattern": "\\b(?:npm|yarn|pnpm|cargo)\\s+publish\\b",
      "label": "npm publish, yarn publish, etc.",
      "message": "Publishing to registry requires explicit user approval.",
      "block_level": "block",
      "enabled": true,
      "category": "destructive"
    }
  ],
  "command_allowlist": [
    {
      "pattern": "git reset --hard HEAD~1",
      "reason": "Commonly used in dev workflow",
      "added_at": "2026-03-21T09:00:00Z",
      "scope": "global"
    }
  ],
  "path_allowlist": [
    {
      "pattern": ".env.example",
      "reason": "Example env files are safe",
      "added_at": "2026-03-21T09:00:00Z",
      "scope": "global"
    }
  ],
  "repo_overrides": {
    "/Users/andrew/projects/my-repo": {
      "block_level": "warn",
      "rules_override": {
        "npm-publish": { "enabled": false },
        "git-reset-hard": { "block_level": "warn" }
      },
      "command_allowlist": [
        { "pattern": "docker run --privileged", "reason": "Needed for CI builds" }
      ]
    }
  }
}
```

### D2. Block log
- **Location:** `~/.openclaw/extensions/openclaw-lacp-fusion/logs/guard-blocks.jsonl`
- **Format:** Append-only JSONL, one entry per event
```json
{
  "timestamp": "2026-03-21T09:52:00Z",
  "rule_id": "npm-publish",
  "command": "npm publish --access public",
  "action_taken": "block",
  "session_id": "abc123",
  "repo": "/Users/andrew/projects/easy-api",
  "agent_id": "wren"
}
```

### D3. Update `pretool-guard.py` to use config
- **Status:** TODO
- Load guard-rules.json on each invocation (or cache with mtime check)
- Resolution order:
  1. Check command against `command_allowlist` (global + repo-specific) -> allow
  2. Check command against rules
  3. For matched rule, determine block_level: repo_override > rule-specific > defaults
  4. Act on block_level: `block` (exit 1), `warn` (log + exit 0), `log` (silent log + exit 0)
  5. Write to block log (guard-blocks.jsonl)

### D4. `openclaw-guard` CLI tool
- **Location:** `plugin/bin/openclaw-guard`
- **Purpose:** Interactive TUI to manage guard rules
- **Commands:**
  - `openclaw-guard rules` — list all rules with status (uses gum table or plain table)
  - `openclaw-guard blocks [--tail N]` — show recent blocks from log
  - `openclaw-guard toggle <rule-id>` — enable/disable a rule
  - `openclaw-guard level <rule-id> <block|warn|log>` — set block level for a rule
  - `openclaw-guard allow <command-pattern> [--repo <path>] [--reason <text>]` — add to allowlist
  - `openclaw-guard deny <command-pattern>` — remove from allowlist
  - `openclaw-guard config` — interactive full configuration (gum-powered)
  - `openclaw-guard config --repo <path>` — configure overrides for a specific repo
  - `openclaw-guard defaults --level <block|warn|log>` — set global default block level
  - `openclaw-guard reset` — reset to factory defaults

### D5. Agent integration for repo-specific guard config
- When an agent enters a repo, the session-start hook should:
  1. Check if repo has an override in guard-rules.json
  2. If no override exists, inject a system message asking the agent:
     "This repo has no custom guard configuration. Apply default guard rules, or would you like to customize?"
  3. Agent can then call `openclaw-guard config --repo <path>` to set up overrides
- This is a modification to `session-start.py` + the `index.ts` hook registration

---

## Section E: Repo Packaging

### E1. Update INSTALL.sh with all Section A fixes
- Consolidate all partial fixes into final INSTALL.sh

### E2. Add `index.ts` template to repo source
- Add to `plugin/index.ts` so it ships in the ZIP

### E3. Rebuild distribution ZIP
- After all changes, rebuild `plugin-dist/openclaw-lacp-fusion-v2.1.0.zip`
- Bump version to 2.1.0

### E4. Update tests
- Add post-install health check tests
- Add guard config/allowlist unit tests
- Add guard CLI integration tests

---

## Priority Order

1. Section A (install fixes) — users can't install without these
2. Section D (guard system) — core feature request
3. Section C (new profiles) — depends on D for autonomous profile
4. Section B (remaining wizard UX) — already mostly done
5. Section E (packaging) — final step
