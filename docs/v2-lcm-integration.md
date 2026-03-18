# v2.0.0 — LCM Bidirectional Integration

## Architecture

v2.0.0 introduces a bidirectional bridge between LACP (persistent memory) and LCM (session-bound context). This enables a knowledge flywheel: each session enriches the persistent memory, and each new session starts with the accumulated knowledge.

### Flow

```
Session Starts
    ↓
[openclaw-lacp-context inject] → Facts injected into LCM window
    ↓
Agent reasons (informed by LACP)
    ↓
Session ends → LCM creates summary (sum_xxx)
    ↓
[openclaw-lacp-promote] → Score summary, auto-promote high-value facts to LACP
    ↓
[openclaw-brain-graph sync --from-lcm] → Enrich Obsidian knowledge graph
    ↓
Next session → Cycle repeats with enriched memory
```

### Components

| Component | Type | Purpose |
|-----------|------|---------|
| `promotion_scorer.py` | Python module | Score LCM summaries for promotion |
| `lcm_lacp_linker.py` | Python module | Create cross-references between LCM and LACP |
| `openclaw-lacp-context` | Bash CLI | Inject LACP facts into LCM sessions |
| `openclaw-lacp-promote` | Bash CLI | Promote facts from LCM to LACP |
| `openclaw-lacp-share` | Bash CLI | Multi-agent sharing (Phase B stubs) |
| `openclaw-brain-graph sync` | Bash CLI | Sync promoted facts to Obsidian graph |

### Components (Phase C/D)

| Component | Type | Purpose |
|-----------|------|---------|
| `semantic_dedup.py` | Python module | Embedding-based deduplication for promoted facts |
| `confidence_calibration.py` | Python module | Track/adjust promotion thresholds dynamically |
| `sharing_policy.py` | Python module | Multi-agent role-based access control (reader/writer/curator) |
| `openclaw-memory-status` | Bash CLI | Memory system dashboard and health monitor |
| `openclaw-lacp-calibrate` | Bash CLI | Confidence calibration CLI |
| `openclaw-lacp-policies` | Bash CLI | Multi-agent sharing policy management |

### Enhanced Flow (Phase C)

```
Session Starts
    ↓
[session-start.py hook] → Auto-calls openclaw-lacp-context auto-inject
    ↓
Top-3 LACP facts injected into LCM context window
    ↓
Injection metadata written to context.json + injection log
    ↓
Agent reasons (informed by LACP persistent memory)
    ↓
Session ends → LCM creates summary (sum_xxx.md or sum_xxx.json)
    ↓
[openclaw-lacp-promote pipeline --file sum_xxx.md]
    ↓
PromotionScorer scores summary → if score >= threshold:
    ↓
Facts promoted to Layer 1 (MEMORY.md) + Layer 2 (vault)
    ↓
Cross-references created via LCMLACPLinker
    ↓
Provenance receipt recorded (Layer 5)
    ↓
Audit trail logged to gated-runs.jsonl
    ↓
Next session → Cycle repeats with enriched memory
```

### Phase D Optimization

```
Before promotion:
    SemanticDedup.is_duplicate(fact) → Skip if similarity > 0.85

After promotion:
    CalibrationTracker.record_promotion() → Track for calibration
    CalibrationTracker.mark_used() → Mark if fact referenced in next session

Periodically:
    openclaw-lacp-calibrate --update → Auto-adjust threshold via F1 optimization

Multi-agent:
    SharingPolicy.can_promote(agent, project) → Role-based access check
    openclaw-lacp-policies grant --agent wren --role writer --project easy-api
```

## Roadmap

### Phase A (v2.0.0) — Foundation ✓
- Promotion scoring system
- Context injection CLI
- Promotion pipeline CLI
- LCM ↔ LACP cross-references
- Knowledge graph auto-enrichment

### Phase B (v2.0.0) — Multi-Agent Sharing (stubs) ✓
- Cross-agent memory queries (stub)
- Granular access control (stub)
- Shared fact deduplication (stub)
- Agent trust scoring (stub)

### Phase C (v2.0.0) — Integration ✓
- Full auto-promotion pipeline (`promote pipeline --file`)
- Auto-injection on session start (session-start.py hook)
- Context injection with metadata tracking (context.json)
- Injection/promotion audit trail (gated-runs.jsonl)
- Memory system dashboard (`openclaw-memory-status`)

### Phase D (v2.0.0) — Optimization ✓
- Embedding-based semantic deduplication (n-gram + word overlap cosine similarity)
- Confidence calibration with threshold auto-adjustment (F1 optimization)
- Multi-agent sharing policy engine (reader/writer/curator roles)
- LRU embedding cache (500 items, disk-persisted)
- Calibration curve and precision/recall/F1 metrics
- Policy audit logging (capped at 1000 entries)

## CLI Reference

### openclaw-lacp-promote
```bash
# Full pipeline: read file → score → promote
openclaw-lacp-promote pipeline --file sum_abc.md --project easy-api
openclaw-lacp-promote pipeline --file sum_abc.json --threshold 80 --dry-run

# Manual commands
openclaw-lacp-promote auto --summary sum_abc --score 85 --category arch
openclaw-lacp-promote manual --summary sum_abc --fact "Brale is settlement layer"
openclaw-lacp-promote list --project easy-api --since 2026-03-18
openclaw-lacp-promote verify --receipt-hash abc123
```

### openclaw-lacp-context
```bash
# Auto-inject top-3 facts at session start
openclaw-lacp-context auto-inject --project easy-api --max-facts 3

# Manual injection
openclaw-lacp-context inject --project easy-api --topic "payment"

# View history
openclaw-lacp-context history --project easy-api --since 2026-03-18
```

### openclaw-memory-status
```bash
# Full dashboard
openclaw-memory-status

# JSON output
openclaw-memory-status --json

# Filter by project
openclaw-memory-status --project easy-api
```

### openclaw-lacp-calibrate
```bash
# View calibration summary
openclaw-lacp-calibrate --show-metrics

# Show calibration curve
openclaw-lacp-calibrate --show-curve

# Auto-update threshold based on F1 optimization
openclaw-lacp-calibrate --update

# Metrics at specific threshold
openclaw-lacp-calibrate --threshold 75 --json
```

### openclaw-lacp-policies
```bash
# List all agents
openclaw-lacp-policies list-agents

# Grant access
openclaw-lacp-policies grant --agent wren --role writer --project easy-api

# Revoke access
openclaw-lacp-policies revoke --agent wren --project easy-api

# Check permissions
openclaw-lacp-policies check --agent wren --project easy-api

# Summary
openclaw-lacp-policies summary --json
```

## Backward Compatibility

- All v1.0.0 CLI commands work unchanged
- All v1.0.0 tests pass
- v2.0.0 features are opt-in (new commands only)
- LACP Layer 1-5 compatibility maintained
- Config is backward compatible
- session-start.py hook gracefully degrades if context CLI unavailable
