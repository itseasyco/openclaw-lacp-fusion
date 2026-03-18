# CLI Reference — OpenClaw LACP Fusion v2.0.0

Complete reference for all CLI commands in the OpenClaw LACP Fusion plugin.

## Brain Stack (Orchestrator)

### `openclaw-brain-stack init`
Initialize all 5 memory layers for a project.

```bash
openclaw-brain-stack init --project PATH --agent NAME [--with-obsidian] [--with-gitnexus] [--auto-ingest]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--project` | Project directory | `.` |
| `--agent` | Agent name | `unknown` |
| `--with-obsidian` | Initialize knowledge graph | off |
| `--with-gitnexus` | Initialize code intelligence | off |
| `--auto-ingest` | Enable ingestion pipeline | off |

### `openclaw-brain-stack doctor`
Health check of all memory layers.

```bash
openclaw-brain-stack doctor --project PATH [--verbose]
```

### `openclaw-brain-stack expand`
Re-summarize and deduplicate memory.

```bash
openclaw-brain-stack expand --project PATH [--layer NUM] [--max-tokens NUM]
```

---

## Brain Doctor (Health Check)

### `openclaw-brain-doctor`
Comprehensive health check with per-layer diagnostics.

```bash
openclaw-brain-doctor --project PATH [--verbose] [--layer NUM]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--project` | Project directory | `.` |
| `--verbose` | Show paths and details | off |
| `--layer` | Check specific layer (1-5) | all |

---

## Brain Expand (Maintenance)

### `openclaw-brain-expand`
Deduplicate, compress, and archive memory entries.

```bash
openclaw-brain-expand --project PATH [--layer NUM] [--max-tokens NUM] [--archive-days NUM]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--project` | Project directory | `.` |
| `--layer` | Expand specific layer | all |
| `--max-tokens` | Token budget for summaries | 5000 |
| `--archive-days` | Archive entries older than N days | 90 |

---

## Knowledge Graph (Layer 2)

### `openclaw-brain-graph init`
Initialize Obsidian vault structure.

```bash
openclaw-brain-graph init --vault-path PATH [--github-sync]
```

### `openclaw-brain-graph sync`
Sync project memory to vault.

```bash
openclaw-brain-graph sync --project PATH --vault-path PATH
```

### `openclaw-brain-graph find-connections`
Traverse wiki-links to find related notes.

```bash
openclaw-brain-graph find-connections --query TEXT --max-depth NUM
```

### `openclaw-brain-graph index`
Rebuild vault index.

```bash
openclaw-brain-graph index --project PATH [--update-qmd]
```

### `openclaw-brain-graph status`
Show vault statistics.

```bash
openclaw-brain-graph status --project PATH [--details]
```

### `openclaw-brain-graph query`
Search vault content.

```bash
openclaw-brain-graph query --project PATH --search-term TEXT
```

---

## Ingestion Pipeline (Layer 3)

### `openclaw-brain-ingest transcript`
Ingest a transcript file.

```bash
openclaw-brain-ingest transcript VAULT_PATH FILE [--speaker NAME] [--date DATE]
```

### `openclaw-brain-ingest url`
Ingest content from a URL.

```bash
openclaw-brain-ingest url VAULT_PATH URL [--title TITLE]
```

### `openclaw-brain-ingest pdf`
Ingest a PDF file.

```bash
openclaw-brain-ingest pdf VAULT_PATH FILE [--title TITLE]
```

### `openclaw-brain-ingest file`
Ingest a generic file.

```bash
openclaw-brain-ingest file VAULT_PATH FILE [--title TITLE]
```

### `openclaw-brain-ingest index`
Rebuild ingestion index.

```bash
openclaw-brain-ingest index VAULT_PATH [--qmd]
```

---

## Code Intelligence (Layer 4)

### `openclaw-brain-code analyze`
Run full AST analysis.

```bash
openclaw-brain-code analyze --project PATH [--output FORMAT] [--gitnexus]
```

### `openclaw-brain-code symbols`
Extract symbols from codebase.

```bash
openclaw-brain-code symbols --project PATH [--pattern GLOB]
```

### `openclaw-brain-code calls`
Trace call chains.

```bash
openclaw-brain-code calls --project PATH --symbol NAME [--depth NUM]
```

### `openclaw-brain-code impact`
Analyze change impact.

```bash
openclaw-brain-code impact --project PATH --file PATH [--scope SCOPE]
```

### `openclaw-brain-code find-usages`
Find all references to a symbol.

```bash
openclaw-brain-code find-usages --project PATH --symbol NAME
```

### `openclaw-brain-code export`
Export code graph.

```bash
openclaw-brain-code export --project PATH --output FILE
```

---

## Agent Identity (Layer 5a)

### `openclaw-agent-id register`
Register persistent agent identity.

```bash
openclaw-agent-id register --project PATH [--agent-name NAME]
```

### `openclaw-agent-id show`
Display agent identity.

```bash
openclaw-agent-id show --project PATH [--json]
```

### `openclaw-agent-id list`
List all registered identities.

```bash
openclaw-agent-id list [--project PATH]
```

### `openclaw-agent-id revoke`
Revoke an agent identity.

```bash
openclaw-agent-id revoke AGENT_ID
```

### `openclaw-agent-id touch`
Update last-active timestamp.

```bash
openclaw-agent-id touch [--project PATH]
```

---

## Provenance (Layer 5b)

### `openclaw-provenance start`
Start a session receipt.

```bash
openclaw-provenance start --project PATH [--agent-id ID]
```

Returns: session ID (stdout, last line).

### `openclaw-provenance end`
End and seal a session receipt.

```bash
openclaw-provenance end SESSION_ID [--exit-code NUM] [--files-modified NUM] [--project PATH]
```

Returns: JSON receipt (stdout).

### `openclaw-provenance verify`
Verify chain integrity.

```bash
openclaw-provenance verify --project PATH
```

### `openclaw-provenance export`
Export audit trail.

```bash
openclaw-provenance export --project PATH [--format jsonl|json|csv] [--output FILE]
```

### `openclaw-provenance status`
Check provenance status.

```bash
openclaw-provenance status --project PATH
```

---

## Obsidian Vault Management

### `openclaw-obsidian status`
Show vault state and statistics.

```bash
openclaw-obsidian status [--vault PATH]
```

### `openclaw-obsidian audit`
Check vault integrity.

```bash
openclaw-obsidian audit [--vault PATH]
```

### `openclaw-obsidian apply`
Sync project memory to vault.

```bash
openclaw-obsidian apply --project PATH [--vault PATH]
```

### `openclaw-obsidian backup`
Create vault backup archive.

```bash
openclaw-obsidian backup [--vault PATH] [--output FILE]
```

### `openclaw-obsidian restore`
Restore vault from backup.

```bash
openclaw-obsidian restore --from FILE [--vault PATH]
```

### `openclaw-obsidian optimize`
Cleanup and compact vault.

```bash
openclaw-obsidian optimize [--vault PATH]
```

---

## Repository Sync

### `openclaw-repo-research-sync`
Mirror repository docs into knowledge graph.

```bash
openclaw-repo-research-sync --project PATH [--vault PATH] [--include-comments] [--dry-run]
```

Syncs: README.md, docs/, CHANGELOG.md, and optionally code comments.

---

## Policy & Routing

### `openclaw-gated-run`
Execute with policy gates.

```bash
openclaw-gated-run --task DESC --agent NAME --channel CHANNEL --estimated-cost-usd NUM [--confirm-budget] -- COMMAND
```

### `openclaw-route`
Determine policy tier for a task.

```bash
openclaw-route AGENT CHANNEL TASK
```

---

## Session Memory

### `openclaw-memory-init`
Scaffold per-project session structure.

```bash
openclaw-memory-init PROJECT_PATH AGENT_ID CHANNEL [SESSION_ID]
```

### `openclaw-memory-append`
Log execution results to session memory.

```bash
openclaw-memory-append --project PATH [--cost NUM] [--exit-code NUM] [--learning TEXT]
```

---

## Verification

### `openclaw-verify`
Evidence verification engine.

```bash
openclaw-verify --mode heuristic|test|llm [OPTIONS]
```

---

## Environment Variables

All commands respect these environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `SESSION_MEMORY_ROOT` | Session memory storage | `~/.openclaw/projects` |
| `LACP_OBSIDIAN_VAULT` | Obsidian vault path | `~/obsidian/vault` |
| `PROVENANCE_ROOT` | Provenance chain storage | `~/.openclaw/provenance` |
| `AGENT_ID_STORE` | Agent identity storage | `~/.openclaw/agent-ids` |
| `LACP_KNOWLEDGE_ROOT` | Knowledge graph storage | `~/.openclaw/data/knowledge` |
| `GATED_RUNS_LOG` | Gated execution log | `~/.openclaw/logs/gated-runs.jsonl` |

---

## v2-lcm Commands

The following commands were introduced in v2.0.0 for bidirectional LCM integration. All support `--backend lcm|file` to override the config-driven context engine, and `--json` for machine-readable output.

### `openclaw-lacp-promote`

Score and promote LCM session summaries to LACP persistent memory.

#### `openclaw-lacp-promote auto`

Auto-score a summary and promote if it exceeds the threshold.

```bash
openclaw-lacp-promote auto --summary SUMMARY_ID --project PROJECT [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--summary` | Summary ID to evaluate (required) | -- |
| `--project` | Project name (required) | -- |
| `--backend` | Override context engine (`lcm` or `file`) | config-driven |
| `--threshold` | Override promotion threshold (0-100) | 70 |
| `--dry-run` | Score without writing to LACP | off |
| `--json` | JSON output | off |

Example:

```bash
# Score and promote a summary
openclaw-lacp-promote auto --summary sum_abc123 --project easy-api

# Dry run to check score without promoting
openclaw-lacp-promote auto --summary sum_abc123 --project easy-api --dry-run --json

# Use LCM backend regardless of config
openclaw-lacp-promote auto --summary sum_abc123 --project easy-api --backend lcm
```

#### `openclaw-lacp-promote manual`

Manually promote a fact with score 100 (bypasses scoring).

```bash
openclaw-lacp-promote manual --summary SUMMARY_ID --fact TEXT --reasoning TEXT [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--summary` | Source summary ID (required) | -- |
| `--fact` | Fact text to promote (required) | -- |
| `--reasoning` | Why this fact matters (required) | -- |
| `--project` | Project name | -- |
| `--backend` | Override context engine | config-driven |
| `--json` | JSON output | off |

Example:

```bash
openclaw-lacp-promote manual \
  --summary sum_abc123 \
  --fact "Finix is the payment processor" \
  --reasoning "Core architecture decision"
```

**Note:** The `--backend` flag overrides the `contextEngine` setting in config for that invocation only. This is useful for testing LCM before switching config, or for one-off file-based lookups.

---

### `openclaw-lacp-context`

Inject LACP facts into LCM session context and query context interactively.

#### `openclaw-lacp-context inject`

Inject relevant facts at session start.

```bash
openclaw-lacp-context inject --project PROJECT [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--project` | Project name (required) | -- |
| `--agent` | Agent name filter | -- |
| `--topic` | Topic filter for relevance scoring | -- |
| `--depth` | Graph/DAG traversal depth | 2 |
| `--format` | Output format: `text`, `json`, `markdown` | text |
| `--backend` | Override context engine (`lcm` or `file`) | config-driven |
| `--discover` | Enable auto-discovery mode (see below) | off |
| `--since` | ISO date filter (with `--discover`) | -- |
| `--until` | ISO date filter (with `--discover`) | -- |
| `--conversation` | Conversation ID filter (with `--discover`, requires lossless-claw) | -- |
| `--summary` | Specific summary ID to start from | -- |
| `--json` | JSON output | off |

Example:

```bash
# Basic injection
openclaw-lacp-context inject --project easy-api --topic "embedded-checkout"

# With auto-discovery from LCM
openclaw-lacp-context inject --project easy-api --discover --since 2026-03-11 --backend lcm

# Traverse from a specific summary
openclaw-lacp-context inject --summary sum_003 --depth 5 --backend lcm --format markdown
```

**Note:** The `--discover` flag enables auto-discovery of summaries by date/project/conversation. When using the lossless-claw backend, discovery supports conversation-level grouping via `--conversation`. With the file-based backend, discovery scans directories without conversation awareness.

#### `openclaw-lacp-context query`

Query facts interactively by topic.

```bash
openclaw-lacp-context query --topic TOPIC [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--topic` | Topic to search (required) | -- |
| `--project` | Scope to project | -- |
| `--min-score` | Minimum relevance score | 50 |
| `--format` | Output format | text |
| `--backend` | Override context engine | config-driven |
| `--json` | JSON output | off |

#### `openclaw-lacp-context list`

List available contexts for a project.

```bash
openclaw-lacp-context list --project PROJECT [--backend lcm|file] [--json]
```

---

### `openclaw-lacp-share`

Multi-agent memory sharing (Phase B). Enables cross-agent context queries with access control.

```bash
openclaw-lacp-share query --from-agent AGENT --project PROJECT [--topic TOPIC] [--backend lcm|file] [--json]
openclaw-lacp-share grant --to-agent AGENT --project PROJECT [--scope read|write] [--json]
openclaw-lacp-share revoke --agent AGENT --project PROJECT [--json]
openclaw-lacp-share list --project PROJECT [--json]
```

| Subcommand | Description |
|------------|-------------|
| `query` | Query another agent's promoted facts |
| `grant` | Grant access to your memory for another agent |
| `revoke` | Revoke a previously granted access |
| `list` | List current sharing grants for a project |

---

### `openclaw-lacp-calibrate`

Tune promotion scoring weights and thresholds based on historical data.

```bash
openclaw-lacp-calibrate --project PROJECT [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--project` | Project name (required) | -- |
| `--sample-size` | Number of recent summaries to evaluate | 100 |
| `--target-rate` | Target promotion rate (0.0-1.0) | 0.2 |
| `--backend` | Override context engine | config-driven |
| `--dry-run` | Show recommended changes without applying | off |
| `--json` | JSON output | off |

Example:

```bash
# Preview calibration changes
openclaw-lacp-calibrate --project easy-api --dry-run --json

# Apply calibration
openclaw-lacp-calibrate --project easy-api --target-rate 0.15
```

---

### `openclaw-lacp-dedup`

Deduplicate promoted facts in LACP memory. Identifies near-duplicate facts and merges or removes redundant entries.

```bash
openclaw-lacp-dedup --project PROJECT [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--project` | Project name (required) | -- |
| `--similarity` | Similarity threshold for dedup (0.0-1.0) | 0.85 |
| `--backend` | Override context engine | config-driven |
| `--dry-run` | Show duplicates without removing | off |
| `--json` | JSON output | off |

Example:

```bash
# Preview duplicates
openclaw-lacp-dedup --project easy-api --dry-run --json

# Remove duplicates with custom threshold
openclaw-lacp-dedup --project easy-api --similarity 0.9
```
