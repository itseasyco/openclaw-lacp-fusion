# Phase C Status — Auto-Promotion & Injection Pipeline

## Deliverables

### CLI Scripts
- [x] `openclaw-lacp-promote` — Full pipeline: read, score, promote, audit
- [x] `openclaw-lacp-context` — Vault query, fact injection, format output
- [x] `openclaw-memory-status` — Dashboard: promotions, injections, trends, graph health, dedup

### Session Hook
- [x] `session-start.py` — Auto-calls `openclaw-lacp-context` on session start
- [x] Injects top-3 LACP facts into LCM context window
- [x] Stores injection metadata to `context.json['lacp_injected_facts']`
- [x] Metadata format: `{fact, source, timestamp, session_id, used: null}`
- [x] Graceful degradation if context CLI unavailable

### Audit Trail
- [x] Promotion events logged to `gated-runs.jsonl`
- [x] Format: `{timestamp, event, summary_id, score, category, receipt_hash, project, version}`
- [x] Provenance receipts with SHA-256 hash chains (Layer 5)
- [x] Promotion log in `promotions.jsonl` with receipt verification

### CLI Examples

```bash
# Full pipeline: score and promote a summary
openclaw-lacp-promote pipeline --file /path/to/sum_abc.md --project easy-api

# Dry run (score without promoting)
openclaw-lacp-promote pipeline --file /path/to/summary.json --threshold 80 --dry-run

# Manual promotion
openclaw-lacp-promote manual --summary sum_abc --fact "Brale is settlement layer" --reasoning "Affects treasury"

# Inject context
openclaw-lacp-context inject --project easy-api --topic "settlement" --format json

# Dashboard
openclaw-memory-status --project easy-api
openclaw-memory-status --json
```

### Testing Results
- `test_cli_promote.py`: 33 tests passing
- `test_cli_context.py`: 17 tests passing
- `test_phase_c_d_integration.py`: 12 tests passing (CLI integration)

## Architecture

```
Session Start
    |
    v
session-start.py hook
    |
    +-- _inject_lacp_context()
    |       |
    |       +-- Finds openclaw-lacp-context CLI
    |       +-- Calls: openclaw-lacp-context auto-inject --project <name> --max-facts 3
    |       +-- Returns formatted LACP facts
    |
    +-- _store_injection_metadata()
    |       |
    |       +-- Parses injected facts
    |       +-- Writes to context.json['lacp_injected_facts']
    |       +-- Metadata: {fact, source, timestamp, session_id, used: null}
    |
    +-- System message includes LACP Memory Context section
```

## Backward Compatibility
- All v1.0.0 CLI commands unchanged
- session-start.py hook is additive (no breaking changes)
- LACP injection is opt-in (skipped if no context CLI available)
- Config files optional with sensible defaults
