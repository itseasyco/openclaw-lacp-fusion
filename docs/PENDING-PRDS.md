# Pending PRDs

Tracked items that need formal PRDs written after the Shared Intelligence Graph brainstorm session completes.

---

## PRD 1: Port brain-resolve, memory-kpi, obsidian-memory-optimize from LACP

**Source:** `/Users/andrew/Development/Tools/lacp/bin/lacp-brain-resolve` (168 lines), `lacp-memory-kpi` (111 lines), `lacp-obsidian-memory-optimize` (89 lines)
**Target:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/bin/`
**Priority:** High — needed for curator engine and shared intelligence graph

### What to port:
- **brain-resolve** — Contradiction/supersession resolution for knowledge notes. Supports resolutions: superseded, contradiction_resolved, validated, stale, archived. Updates frontmatter with resolution state, reason, and superseded-by references.
- **memory-kpi** — Vault quality metrics: frontmatter coverage, schema compliance, orphan rate, staleness distribution, traversal frequency stats.
- **obsidian-memory-optimize** — Graph physics tuning for Obsidian's graph view. Applies memory-centric defaults (hide archive/trash, tune link distance, repel strength, node sizing). Size-based profiles (small/medium/large).

### Adaptation needed:
- Update paths from `~/.claude/` to `~/.openclaw/`
- Integrate with existing OpenClaw plugin config structure
- Register as agent tools via `api.registerTool()` in index.ts
- Add to INSTALL.sh distribution and bin copy step

---

## PRD 2: Wizard dependency installation (GitNexus, lossless-claw)

**Priority:** Medium — improves first-time setup experience

### What to build:
The INSTALL.sh wizard should detect and offer to install optional dependencies:

**GitNexus (Layer 4 Code Intelligence):**
- During wizard, if user enables code intelligence:
  - Check if `gitnexus` is installed (`npx gitnexus --version`)
  - If not, offer to install: `npm install -g gitnexus`
  - Run initial analysis on current repo: `npx gitnexus analyze`
  - Configure `CODE_GRAPH_ENABLED=true` in env config

**lossless-claw (LCM Context Engine):**
- During wizard, if user selects `lossless-claw` as context engine:
  - Check if lossless-claw plugin is installed (`ls ~/.openclaw/extensions/lossless-claw`)
  - If not, offer to install: `openclaw plugins install @martian-engineering/lossless-claw`
  - Run through lossless-claw's own setup if it has one
  - Verify `~/.openclaw/lcm.db` exists after install
  - Configure `LACP_CONTEXT_ENGINE=lossless-claw` in env config

### Considerations:
- Must handle install failures gracefully (fall back to file-based/no-gitnexus)
- Should show progress during npm install (can be slow)
- Needs gum spinner or progress indicator during install
- If user declines install, set config to work without the dependency

---

## PRD 3: Mycelium Network Memory Implementation

**Priority:** High — required for curator engine quality management
**Source specs:** Test contracts in `/Users/andrew/Development/Tools/lacp/scripts/ci/test-brain-memory.sh`

### Functions to implement (from test contracts):

| Function | Module | Behavior (from tests) |
|---|---|---|
| `spreading_activation(seeds, items, alpha, max_hops)` | sync_research_knowledge | Collins & Loftus propagation. alpha=0.7 decay per hop. Takes max of incoming activations, not sum. |
| `compute_storage_strength(item)` | sync_research_knowledge | FSRS storage strength from access count. count=10 → >0.59 |
| `compute_retrieval_strength(item, edge_count)` | sync_research_knowledge | FSRS retrieval strength with temporal decay. Old items with 0 edges → <0.5 |
| `compute_importance_score(item)` | sync_research_knowledge | Combined importance from storage + retrieval + graph position |
| `reinforce_access_paths(node_id, items)` | sync_research_knowledge | Mycelium path reinforcement. Boosts confidence of traversed nodes. |
| `heal_broken_paths(pruned_set, items, hubs)` | sync_research_knowledge | Reconnect orphaned neighbors after pruning |
| `compute_flow_score(node_id, items, sample_size)` | sync_research_knowledge | Betweenness centrality proxy for hub detection |
| `run_consolidation(...)` | memory_consolidation | Full consolidation pipeline: prune, merge, reinforce, heal |

### Implementation approach:
- Implement as `plugin/lib/mycelium.py` (importable module)
- **TDD from LACP test contracts** — implement functions, run against test specs from `/Users/andrew/Development/Tools/lacp/scripts/ci/test-brain-memory.sh`, iterate until passing
- Also implement supporting pipeline scripts: `detect_knowledge_gaps.py`, `generate_review_queue.py`, `route_inbox.py`, `archive_inbox.py`
- Integrate with brain-expand (`--consolidate` and `--activate` flags)
- Expose via `openclaw-brain-expand --consolidate --activate`
- Register key functions as agent tools (importance scoring, flow scoring)

### Status: APPROVED FOR IMMEDIATE IMPLEMENTATION (TDD from test contracts, not waiting on source code)

---

## PRD 4: Shared Intelligence Graph (from current brainstorm)

**Priority:** Strategic — the full shared vault + connectors + curator system
**Spec:** `docs/SHARED-INTELLIGENCE-SPEC.md`
**Status:** Currently brainstorming — PRD will be written after design approval

### Sub-PRDs (will be decomposed during planning):
- 4a: Source Connector Framework
- 4b: openclaw-lacp-connect (invite/join/sync daemon)
- 4c: Curator Engine (mycelium + inbox processing + staleness)
- 4d: CI/CD → Vault Pipeline (GitHub Actions)
- 4e: obsidian-headless integration

---

## Execution Order

1. **PRD 3** (Mycelium) — foundation for everything else
2. **PRD 1** (Port brain-resolve/kpi/optimize) — needed for curator
3. **PRD 2** (Wizard dependencies) — improves UX, can parallel with above
4. **PRD 4** (Shared Intelligence) — the big one, depends on 1-3
