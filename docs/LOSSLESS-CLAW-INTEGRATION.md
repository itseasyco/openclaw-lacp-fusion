# Lossless-Claw Integration

## What is lossless-claw?

Lossless-claw is the native LCM (Lossless Context Memory) context engine for OpenClaw LACP. It stores session summaries in a SQLite database organized as a directed acyclic graph (DAG). Each summary node can reference a parent, forming chains that represent full conversation histories across sessions.

Unlike the default file-based approach (which scans vault directories and memory files), lossless-claw provides:

- Structured storage with indexed queries instead of filesystem scans
- DAG traversal to reconstruct full conversation history across sessions
- Auto-discovery of summaries by date range, project, or conversation ID
- Batch querying with configurable page sizes

The database lives at `~/.openclaw/lcm.db` by default and contains a `summaries` table with columns for `summary_id`, `content`, `parent_id`, `conversation_id`, `project`, `agent`, `timestamp`, `citations`, `tags`, and `metadata`.

## How to Enable

Set `contextEngine` to `"lossless-claw"` in your plugin configuration.

### Config Example

In `~/.openclaw/openclaw.json`:

```json
{
  "plugins": {
    "entries": {
      "openclaw-lacp-fusion": {
        "enabled": true,
        "config": {
          "contextEngine": "lossless-claw",
          "lcmDbPath": "~/.openclaw/lcm.db",
          "lcmQueryBatchSize": 50,
          "promotionThreshold": 70,
          "autoDiscoveryInterval": "6h"
        }
      }
    }
  }
}
```

Or use a standalone plugin config file. See `plugin/config/example-openclaw-lacp.lossless-claw.json` for the minimal example.

### Config Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `contextEngine` | `string \| null` | `null` | Set to `"lossless-claw"` to enable. `null` uses file-based. |
| `lcmDbPath` | `string` | `~/.openclaw/lcm.db` | Path to the LCM SQLite database. |
| `lcmQueryBatchSize` | `int` | `50` | Maximum summaries returned per query (1-1000). |
| `promotionThreshold` | `int` | `70` | Minimum score (0-100) for auto-promotion to LACP. |
| `autoDiscoveryInterval` | `string` | `"6h"` | How often auto-discovery runs. Valid: 1h, 2h, 4h, 6h, 8h, 12h, 24h. |

## Auto-Discovery

Use the `--discover` flag on `openclaw-lacp-context` to find summaries by date range, project, or conversation ID without knowing specific summary IDs.

```bash
# Discover all summaries from the last 7 days
openclaw-lacp-context inject --project easy-api --discover --since 2026-03-11

# Discover summaries for a specific conversation
openclaw-lacp-context inject --project easy-api --discover --conversation conv_abc123

# Discover with project filter and date range
openclaw-lacp-context inject --discover --project easy-checkout --since 2026-03-01 --until 2026-03-15
```

Auto-discovery requires `contextEngine: "lossless-claw"`. When using the file-based backend, `--discover` will scan directories but without DAG awareness or conversation-level grouping.

## Context Injection Workflow

Context injection happens at session start. The flow is:

```
1. Session starts
2. session-start hook fires
3. openclaw-lacp-context inject runs
4. Backend fetches relevant summaries (by project, keywords, recency)
5. Facts are scored for relevance to the current session topic
6. Top-scoring facts are formatted and prepended to the LCM context window
7. Agent begins reasoning with accumulated organizational knowledge
```

The injection command:

```bash
openclaw-lacp-context inject \
  --project easy-api \
  --agent wren \
  --topic "embedded-checkout" \
  --depth 2 \
  --format markdown \
  --backend lcm
```

This queries the LCM database for summaries related to "embedded-checkout" in the easy-api project, traverses parent chains up to depth 2, and outputs prompt-ready markdown.

## DAG Traversal

The `traverse_dag` method walks parent chains to build full conversation history. Each summary in the `summaries` table has an optional `parent_id` column pointing to the preceding summary in the same conversation.

```
sum_003 (current)
  └── parent_id → sum_002
       └── parent_id → sum_001
            └── parent_id → null (root)
```

Traversal starts at a given summary and walks backward through `parent_id` references until it reaches a root node (null parent) or hits the configured depth limit.

```bash
# Traverse from a specific summary, depth 5
openclaw-lacp-context inject --summary sum_003 --depth 5 --backend lcm
```

The result includes:

| Field | Description |
|-------|-------------|
| `root` | The earliest ancestor summary reached |
| `chain` | Ordered list of summaries from current to root |
| `depth_reached` | How many levels were traversed |

The file-based backend does not support true DAG traversal. It returns a single-node chain if the summary is found by file search.

## Migration from File-Based to LCM

### Step 1: Ensure lcm.db exists

The LCM database must exist at `~/.openclaw/lcm.db` (or your configured `lcmDbPath`) and contain a `summaries` table.

```bash
# Verify the database exists and has the right schema
sqlite3 ~/.openclaw/lcm.db ".tables"
# Expected output should include: summaries
```

If the database does not exist, it should be created by lossless-claw's own initialization process. LACP does not create this database -- it reads from it.

### Step 2: Update config

Set `contextEngine` to `"lossless-claw"` in your `openclaw.json`:

```json
{
  "plugins": {
    "entries": {
      "openclaw-lacp-fusion": {
        "enabled": true,
        "config": {
          "contextEngine": "lossless-claw"
        }
      }
    }
  }
}
```

### Step 3: Test with --backend flag

Before committing to the config change, test with the CLI override:

```bash
# Test context injection with the LCM backend
openclaw-lacp-context inject --project easy-api --backend lcm --format json

# Test promotion with the LCM backend
openclaw-lacp-promote auto --summary sum_abc123 --backend lcm
```

The `--backend` flag overrides the config-driven engine for that single invocation.

### Step 4: Remove file-based overrides

Once lossless-claw is working:

1. Remove any `--backend file` flags from scripts or hooks.
2. Remove explicit `--file` paths from context injection commands (the LCM backend queries the database directly).
3. Keep vault and memory directories intact -- they are still used by Layer 1 and Layer 2 independently of the context engine.

## Troubleshooting

### Database not found

```
ValueError: lossless-claw backend requested but LCM database not found.
Expected at: ~/.openclaw/lcm.db.
```

**Cause:** `contextEngine` is set to `"lossless-claw"` but `lcm.db` does not exist at the configured path.

**Fix:** Either create the LCM database through lossless-claw's initialization, or set `contextEngine` to `null` to fall back to file-based.

### Empty results from LCM queries

**Cause:** The `summaries` table exists but contains no rows, or the project/date filters are too restrictive.

**Fix:**
```bash
# Check row count
sqlite3 ~/.openclaw/lcm.db "SELECT COUNT(*) FROM summaries;"

# Check available projects
sqlite3 ~/.openclaw/lcm.db "SELECT DISTINCT project FROM summaries;"

# Broaden filters
openclaw-lacp-context inject --discover --backend lcm
```

### Fallback to file-based

If the LCM database becomes unavailable mid-session, the `get_backend` factory will raise a `ValueError`. To handle this gracefully, use the `--backend file` override or set `contextEngine` to `null` in config until the database issue is resolved.

### Slow queries

If discovery is slow on large databases, reduce `lcmQueryBatchSize`:

```json
{
  "config": {
    "lcmQueryBatchSize": 20
  }
}
```

## CLI Commands and the --backend Flag

All v2-lcm CLI commands accept a `--backend` flag that overrides the config-driven engine selection:

| Command | --backend support | Notes |
|---------|-------------------|-------|
| `openclaw-lacp-context` | Yes | `--backend lcm` or `--backend file` |
| `openclaw-lacp-promote` | Yes | `--backend lcm` or `--backend file` |
| `openclaw-lacp-share` | Yes | `--backend lcm` or `--backend file` |
| `openclaw-lacp-calibrate` | Yes | `--backend lcm` or `--backend file` |
| `openclaw-lacp-dedup` | Yes | `--backend lcm` or `--backend file` |

See [CLI-REFERENCE.md](./CLI-REFERENCE.md) for full command documentation.
