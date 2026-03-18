# Context Backends

## Architecture

The v2-lcm module uses a backend abstraction to decouple context retrieval from storage format. All CLI commands and internal modules operate against the `ContextBackend` interface, allowing transparent switching between implementations.

```
                    +-----------------------+
                    |   ContextBackend      |
                    |   (abstract class)    |
                    +-----------+-----------+
                                |
              +-----------------+-----------------+
              |                                   |
   +----------+----------+           +------------+----------+
   |    FileBackend      |           |     LCMBackend        |
   |  (file-based)       |           |  (lossless-claw)      |
   +---------------------+           +-----------------------+
   | Scans vault dirs    |           | Queries SQLite DAG    |
   | Reads memory root   |           | traverse_dag()        |
   | Explicit --file     |           | Keyword search        |
   | paths               |           | Batch discovery       |
   +---------------------+           +-----------------------+
              |                                   |
    ~/.openclaw/vault/              ~/.openclaw/lcm.db
    ~/.openclaw/memory/             (summaries table)
```

### ContextBackend Interface

All backends implement these methods:

| Method | Signature | Description |
|--------|-----------|-------------|
| `fetch_summary` | `(summary_id: str) -> dict` | Fetch a single summary by ID |
| `discover_summaries` | `(filters: dict) -> list` | Find summaries matching filters (since, until, project, limit) |
| `find_context` | `(task: str, project?, limit?) -> list` | Keyword search for task-relevant context |
| `traverse_dag` | `(summary_id: str, depth?) -> dict` | Walk parent chain to build conversation history |
| `backend_name` | `() -> str` | Return `"file"` or `"lossless-claw"` |
| `is_available` | `() -> bool` | Check whether the backend can serve requests |

---

## FileBackend

The default backend when `contextEngine` is `null` or unset.

### How It Works

FileBackend scans the filesystem for context:

1. **Explicit files** -- Any paths provided via the `--file` flag or `files` config key are searched first.
2. **Memory root** -- Recursively scans `~/.openclaw/memory/` (or configured `memoryRoot`) for `.md` and `.json` files.
3. **Vault directories** -- Recursively scans `~/.openclaw/vault/` (or configured `vaultPath`) for markdown notes.
4. **Keyword matching** -- For `find_context`, extracts keywords from the task description and scores files by term frequency overlap.
5. **Date filtering** -- For `discover_summaries`, filters by file timestamps or embedded date fields.

### When to Use

- Simple setups without a running lossless-claw instance
- Projects that store context as flat files or Obsidian vault notes
- Quick prototyping before committing to the full LCM pipeline
- Environments where SQLite is not available or practical

### Limitations

- No true DAG traversal. `traverse_dag()` returns a single-node chain if the summary is found.
- No conversation-level grouping. Summaries are discovered individually by file path.
- No auto-discovery by conversation ID. The `--discover` flag scans directories but cannot group by conversation.
- Performance degrades on large vaults (filesystem scan on every query).

---

## LCMBackend

The native lossless-claw context engine. Activated by setting `contextEngine` to `"lossless-claw"`.

### How It Works

LCMBackend queries the `summaries` table in `~/.openclaw/lcm.db`:

1. **Direct fetch** -- `fetch_summary` performs a primary key lookup by `summary_id`.
2. **Discovery** -- `discover_summaries` builds a SQL query with optional WHERE clauses for `since`, `until`, `project`, and `conversation_id`. Results are ordered by timestamp descending.
3. **Keyword search** -- `find_context` fetches recent summaries (up to `lcmQueryBatchSize`) and scores them against extracted keywords from the task description.
4. **DAG traversal** -- `traverse_dag` walks `parent_id` references from a starting summary backward through the chain, up to the configured depth.

### When to Use

- Full lossless-claw integration with persistent session summaries
- Projects that need conversation history reconstruction (DAG traversal)
- Multi-project environments with structured discovery queries
- Production setups requiring indexed, batch-capable context retrieval

### Requirements

- `~/.openclaw/lcm.db` must exist (or the path configured in `lcmDbPath`)
- The database must contain a `summaries` table with at minimum: `summary_id`, `content`, `parent_id`, `timestamp`, `project`
- Python `sqlite3` module (included in standard library)

---

## Comparison

| Feature | FileBackend | LCMBackend |
|---------|-------------|------------|
| Storage format | Flat files (MD, JSON) | SQLite database |
| DAG traversal | No (single-node only) | Yes (full parent chain) |
| Auto-discovery by date | Yes (filesystem scan) | Yes (SQL query) |
| Auto-discovery by conversation | No | Yes |
| Auto-discovery by project | Yes (directory convention) | Yes (SQL WHERE) |
| Keyword search | Yes (file content scan) | Yes (batch + score) |
| Batch size control | Limited (scan-based) | Yes (`lcmQueryBatchSize`) |
| Setup complexity | None (works out of the box) | Requires lcm.db with summaries table |
| Performance on large datasets | Degrades (O(n) file scan) | Stable (indexed queries) |
| Explicit file paths (--file) | Yes | No (queries DB only) |
| Always available | Yes | Only if lcm.db exists |

---

## get_backend Factory

The `get_backend(config)` function in `plugin/v2-lcm/backends/__init__.py` handles backend selection:

```python
from backends import get_backend

config = load_openclaw_lacp_config()
backend = get_backend(config)

# Use the backend
summaries = backend.discover_summaries({"project": "easy-api", "limit": 20})
context = backend.find_context("deploy treasury flow", project="easy-api")
chain = backend.traverse_dag("sum_abc123", depth=5)
```

Selection logic:

1. If `config["contextEngine"] == "lossless-claw"`:
   - Instantiate `LCMBackend(config)`
   - Verify `is_available()` returns `True`
   - If not available, raise `ValueError` with a message pointing to the missing database
2. Otherwise (null or unset):
   - Instantiate `FileBackend(config)`
   - FileBackend is always available

---

## Config-Driven Selection

Backend selection is driven by the `contextEngine` key in plugin config:

```json
{
  "contextEngine": "lossless-claw"
}
```

This can be set in three places (resolution order, later overrides earlier):

1. **Defaults** -- `contextEngine: null` (file-based)
2. **openclaw.json** -- Gateway config at `plugins.entries.openclaw-lacp-fusion.config.contextEngine`
3. **CLI override** -- `--backend lcm` or `--backend file` on any v2-lcm command

The `--backend` flag takes precedence over all config. This allows testing a different backend without modifying configuration files.
