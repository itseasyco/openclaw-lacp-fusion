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

## LCM-LACP Integration (v2.0.0)

### `openclaw-lacp-promote`
Promote LCM session facts to LACP persistent memory.

```bash
openclaw-lacp-promote auto --summary <id> [--score <n>] [--category <cat>]
openclaw-lacp-promote pipeline --file <path> [--project <name>] [--threshold <n>] [--similarity-threshold <n>] [--calibrate-confidence] [--dry-run]
openclaw-lacp-promote manual --summary <id> --fact <text> --reasoning <why>
openclaw-lacp-promote list [--project <name>] [--since <date>]
openclaw-lacp-promote verify --receipt-hash <hash>
```

| Option | Description | Default |
|--------|-------------|---------|
| `--similarity-threshold` | Dedup cosine similarity threshold | `0.85` |
| `--calibrate-confidence` | Auto-calibrate threshold from usage data | off |
| `--dry-run` | Score but don't promote | off |

### `openclaw-lacp-context`
Inject LACP facts into LCM session context.

```bash
openclaw-lacp-context inject --project <name> [--format json|markdown]
openclaw-lacp-context query --topic <topic> [--project <name>]
openclaw-lacp-context list [--project <name>]
```

### `openclaw-lacp-dedup`
Semantic deduplication for promoted facts.

```bash
openclaw-lacp-dedup check --fact <text> [--vault <path>] [--threshold <n>]
openclaw-lacp-dedup batch --file <path> [--vault <path>] [--threshold <n>]
openclaw-lacp-dedup stats
```

| Option | Description | Default |
|--------|-------------|---------|
| `--threshold` | Cosine similarity threshold (0.0-1.0) | `0.85` |
| `--vault` | Vault path | `$OPENCLAW_VAULT_ROOT` |

### `openclaw-lacp-calibrate`
Confidence calibration for promotion thresholds.

```bash
openclaw-lacp-calibrate [/path/to/vault] [--show-metrics] [--show-curve] [--update] [--threshold <n>] [--json]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--update` | Auto-update threshold in config | off |
| `--show-curve` | Display calibration history | off |
| `--show-metrics` | Show precision/recall at thresholds | off |

### `openclaw-lacp-share`
Multi-agent memory sharing.

```bash
openclaw-lacp-share register --agent <id> --role <role>
openclaw-lacp-share enable
openclaw-lacp-share disable
openclaw-lacp-share grant-access --agent <id> --project <name> [--role <role>]
openclaw-lacp-share revoke-access --agent <id> --project <name>
openclaw-lacp-share check --agent <id> --project <name> --action <action>
openclaw-lacp-share list-available --from <agent>
openclaw-lacp-share query --from <agent> --topic <topic>
```

| Option | Description | Default |
|--------|-------------|---------|
| `--policy-file` | Path to sharing policy config | `~/.openclaw/config/sharing-policy.json` |
| `--role` | Agent role: reader, writer, curator | `reader` |
| `--json` | Output as JSON | off |

### `openclaw-lacp-policies`
View and manage sharing policies (admin).

```bash
openclaw-lacp-policies list-agents [--project <name>]
openclaw-lacp-policies list-projects [--agent <id>]
openclaw-lacp-policies grant --agent <id> --role <role> --project <name>
openclaw-lacp-policies revoke --agent <id> --project <name>
openclaw-lacp-policies check --agent <id> --project <name>
openclaw-lacp-policies summary [--json]
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
