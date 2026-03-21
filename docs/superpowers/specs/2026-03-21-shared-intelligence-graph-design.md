# Shared Intelligence Graph

**Status:** Design (Pending Approval)
**Date:** 2026-03-21
**Authors:** Andrew, Claude

---

## 1. Overview

The Shared Intelligence Graph transforms openclaw-lacp-fusion from a single-machine knowledge system into a multi-node company intelligence network. Every agent across the organization contributes knowledge, and every agent benefits from the collective intelligence.

An engineer's agent discovers a bug pattern -- it propagates to every other engineer's agent. A PM documents a feature plan -- dev agents already have context when they start building. C-suite sets strategic direction -- every agent in the org understands the reasoning behind decisions.

The system adds three capabilities to the existing LACP plugin:

1. **Shared vault synchronization** via Obsidian Sync (E2EE) with obsidian-headless (`ob`) providing CLI vault access on every node.
2. **Connector framework** that ingests knowledge from external sources (GitHub, Slack, email, webhooks, filesystems) into the vault.
3. **Curator engine** that continuously organizes, links, prunes, and validates the knowledge graph using the mycelium algorithms already implemented in `plugin/lib/mycelium.py`.

### Three Operating Modes

The system supports three modes to match different deployment contexts:

- **Standalone** -- everything runs locally, the current default. All brain commands active, local vault only.
- **Connected** -- an agent node that reads from a shared vault and writes to its inbox. Vault mutations are delegated to the curator.
- **Curator** -- an always-on server that runs connectors, mycelium consolidation, full vault mutations, and serves as the canonical copy.

### Who It's For

- **Today:** A 2-person team (Andrew + Niko) with 19 active agents. The curator runs on a single server, all agents connect.
- **In 6 months:** 5-15 people, multiple repos, external contributors. Connector framework handles the information firehose.
- **Open source:** Anyone running openclaw-lacp-fusion can use Standalone mode immediately. Teams adopt Connected + Curator when they need shared intelligence.

---

## 2. Architecture

### 2.1 Operating Modes

| Aspect | Standalone | Connected | Curator |
|---|---|---|---|
| **Vault location** | Local (`~/.openclaw/vault/`) | Synced via `ob sync` (read + inbox writes) | Canonical copy, git-backed |
| **Brain mutation commands** | All active | BLOCKED (curator-managed) | Runs as part of scheduled loop |
| **Inbox writes** | Direct to graph | Writes to `05_Inbox/queue-agent/` | Processes all queues |
| **Mycelium consolidation** | Local on-demand | Disabled (curator runs it) | Scheduled every 2-6 hours |
| **Connectors** | None | None | All connectors run here |
| **ob sync** | Not required | `ob sync --continuous` daemon | `ob sync --continuous` daemon |
| **Git backup** | Not required | Not required | Periodic `git commit + push` |
| **HTTP surface** | None | None | 3 endpoints (validate, health, notify) |
| **Selection** | Default in INSTALL.sh | `openclaw-lacp-connect join` | INSTALL.sh wizard (curator option) |

Mode selection happens during the INSTALL.sh wizard. Standalone is the default. A Standalone installation can later become Connected by running `openclaw-lacp-connect join`. The Curator mode requires explicit setup with connector configuration, git backup, and invite token generation.

### 2.2 System Topology

```
                        ┌─────────────────────────┐
                        │   Obsidian Sync Cloud    │
                        │   (E2EE relay only)      │
                        └────────┬────────────────┘
                                 │
              ┌──────────────────┼──────────────────────┐
              │                  │                       │
   ┌──────────▼──────────┐  ┌───▼───────────────┐  ┌───▼───────────────┐
   │  Curator Server      │  │  Agent Node A     │  │  Agent Node B     │
   │                      │  │  (Connected)      │  │  (Connected)      │
   │  ob sync --continuous│  │                   │  │                   │
   │  Connectors:         │  │  ob sync          │  │  ob sync          │
   │   - GitHub           │  │  --continuous     │  │  --continuous     │
   │   - Slack            │  │                   │  │                   │
   │   - Email            │  │  Read: full vault │  │  Read: full vault │
   │   - Webhooks         │  │  Write: inbox     │  │  Write: inbox     │
   │  Mycelium engine     │  │  only             │  │  only             │
   │  Git backup          │  │                   │  │                   │
   │  3 HTTP endpoints    │  │  brain-code: yes  │  │  brain-code: yes  │
   │                      │  │  brain-expand:    │  │  brain-expand:    │
   │  Canonical vault     │  │  BLOCKED          │  │  BLOCKED          │
   └──────────┬───────────┘  └───────────────────┘  └───────────────────┘
              │
   ┌──────────▼───────────┐
   │  External Sources     │
   │                       │
   │  GitHub (webhooks)    │
   │  Slack  (events API)  │
   │  Email  (IMAP/gog)   │
   │  Any URL (cron-fetch) │
   │  Filesystem (watch)   │
   └───────────────────────┘
```

Key constraints:
- External sources connect **only** to the curator. Connected nodes never run connectors.
- All vault mutations (reorganization, link weaving, pruning) happen **only** on the curator. Connected nodes write exclusively to inbox queues.
- Obsidian Sync Cloud is the relay. It never sees plaintext (E2EE). Every node holds a full local copy.

### 2.3 Connector Architecture (OpenClaw-inspired)

Connectors are the input pipeline for external knowledge. They follow a tiered model inspired by OpenClaw's plugin system.

#### Tiers

**Tier 1 -- Native** (built into the curator, always available):
- `agent` -- agent-submitted facts via inbox writes (no connector needed, uses ob sync)
- `filesystem` -- watch any local folder for new/changed files
- `webhook` -- generic HTTP endpoint, accepts any service with webhook support, custom transform scripts
- `cron-fetch` -- poll any URL or API on a schedule, transform response into vault notes

**Tier 2 -- First-party** (installable, maintained by us):
- `github` -- PR summaries, branch lifecycle, deploy events, issue tracking
- `slack` -- channel messages, thread summaries, bookmarked messages
- `email` -- inbound email via IMAP or gog (Gmail auth), per-sender routing

**Tier 3 -- Community** (npm packages, anyone can build):
- Package naming: `openclaw-lacp-connector-<name>`
- Install via: `openclaw plugins install openclaw-lacp-connector-notion`
- Distributed as standard npm packages with a `connector.json` manifest

#### Connector Interface

Every connector implements these methods:

```python
class Connector:
    id: str            # unique connector id (e.g., "github-easylabs")
    type: str          # connector type (e.g., "github", "slack", "webhook")
    trust_level: str   # "verified", "high", "medium", "low"
    mode: str          # "pull", "push", "both"
    landing_zone: str  # default inbox subfolder (e.g., "queue-cicd")

    def authenticate(self) -> bool:
        """Establish connection to the external source."""

    def pull(self) -> list[RawData]:
        """Fetch new data from source (for pull/both mode)."""

    def receive(self, payload: dict) -> RawData:
        """Handle incoming webhook payload (for push/both mode)."""

    def transform(self, raw_data: RawData) -> VaultNote:
        """Convert raw external data into a vault-compatible note with frontmatter."""

    def health_check(self) -> dict:
        """Return connector status, last pull time, error count."""
```

#### Generic Connectors as Escape Hatches

For sources that don't have a dedicated connector, the generic connectors cover most cases:

- **`webhook`** -- any service that supports HTTP webhooks. Configure a URL on the curator's HTTP surface, write a small transform script (Python or JS) that maps the payload to a VaultNote. Supports HMAC signature verification.
- **`cron-fetch`** -- poll any URL or API on a schedule. Configure the URL, headers, polling interval, and a transform script. Useful for RSS feeds, status pages, API endpoints.
- **`filesystem`** -- watch any local folder. New or changed files are ingested as vault notes. Useful for dropbox-style ingestion, shared network folders, or output from other tools.
- **`imap`** -- poll any email inbox. Filter by sender, subject, or folder. Transform emails into vault notes with attachments handled separately.

#### Connector Configuration

Connectors are configured in `config/connectors.json`:

```json
{
  "connectors": [
    {
      "id": "github-easylabs",
      "type": "github",
      "trust_level": "verified",
      "mode": "push",
      "landing_zone": "queue-cicd",
      "config": {
        "webhook_secret": "${GITHUB_WEBHOOK_SECRET}",
        "repos": ["easy-labs/easy-api", "easy-labs/easy-dashboard"],
        "events": ["pull_request", "push", "deployment", "release"]
      }
    },
    {
      "id": "slack-engineering",
      "type": "slack",
      "trust_level": "medium",
      "mode": "both",
      "landing_zone": "queue-human",
      "config": {
        "bot_token": "${SLACK_BOT_TOKEN}",
        "channels": ["engineering", "architecture-decisions", "incidents"],
        "user_allowlist": ["U01ABC123", "U02DEF456"],
        "events": ["message", "reaction_added"],
        "min_reactions": 2
      }
    },
    {
      "id": "email-company",
      "type": "email",
      "trust_level": "medium",
      "mode": "pull",
      "landing_zone": "queue-human",
      "config": {
        "provider": "gog",
        "poll_interval_minutes": 15,
        "folders": ["INBOX/Knowledge", "INBOX/Architecture"],
        "sender_policy": "allowlist",
        "sender_allowlist": [
          "andrew@easylabs.io",
          "niko@easylabs.io"
        ]
      }
    },
    {
      "id": "webhook-sentry",
      "type": "webhook",
      "trust_level": "medium",
      "mode": "push",
      "landing_zone": "queue-cicd",
      "config": {
        "path": "/hooks/sentry",
        "hmac_secret": "${SENTRY_WEBHOOK_SECRET}",
        "hmac_header": "Sentry-Hook-Signature",
        "transform": "transforms/sentry-to-vault.py"
      }
    },
    {
      "id": "watch-docs",
      "type": "filesystem",
      "trust_level": "high",
      "mode": "pull",
      "landing_zone": "queue-agent",
      "config": {
        "watch_paths": ["/opt/company-docs/shared/"],
        "extensions": [".md", ".txt"],
        "ignore_patterns": ["*.tmp", ".DS_Store"]
      }
    }
  ]
}
```

#### Community Connector Packaging

A community connector is distributed as an npm package containing:

```
openclaw-lacp-connector-notion/
  package.json           # standard npm package
  connector.json         # manifest: id, type, trust_level, required_config
  index.py               # implementation of the Connector interface
  transforms/            # optional transform scripts
  README.md              # usage instructions
```

The `connector.json` manifest:

```json
{
  "id": "notion",
  "type": "notion",
  "version": "1.0.0",
  "trust_level": "medium",
  "mode": "pull",
  "required_config": ["api_token", "database_ids"],
  "landing_zone": "queue-human"
}
```

Install via: `openclaw plugins install openclaw-lacp-connector-notion`

### 2.4 Trust and Sender Verification

Trust operates at two layers to prevent untrusted or malicious content from contaminating the knowledge graph.

#### Layer 1: Connector Trust Level

Each connector declares a trust level that determines how its output is handled:

| Trust Level | Meaning | Curator Behavior |
|---|---|---|
| `verified` | Cryptographically verified source (e.g., signed Git commits) | Auto-promote to organized graph |
| `high` | Trusted internal source (e.g., agent facts, watched filesystem) | Light curator review, fast promote |
| `medium` | Known but unverified source (e.g., Slack messages, email from known senders) | Curator classifies and promotes |
| `low` | External or unknown source (e.g., external AI, unknown sender) | Curator validates before promoting, tagged `status: unverified` |

#### Layer 2: Sender Allowlist Per Connector

Each connector can enforce sender-level policies:

| Policy | Behavior |
|---|---|
| `allowlist` | Only messages from listed senders are accepted. All others are dropped. |
| `domain` | Accept from any sender matching the domain (e.g., `@easylabs.io`). |
| `open` | Accept from anyone. Lowest trust, always tagged `status: unverified`. |

#### Verification Method Per Connector Type

| Connector | Verification Method |
|---|---|
| `email` | Sender allowlist (exact address or domain match) |
| `slack` | Channel allowlist + user allowlist |
| `webhook` | HMAC signature verification + optional IP allowlist |
| `github` | Webhook secret validation + repo allowlist |
| `agent` | Agent ID from Layer 5 provenance (LACP session metadata) |
| `filesystem` | Path allowlist (only watched directories) |
| `cron-fetch` | URL allowlist (only configured endpoints) |

#### Email Connector with Per-Sender Trust Overrides

The email connector supports granular trust configuration per sender:

```json
{
  "id": "email-company",
  "type": "email",
  "trust_level": "medium",
  "config": {
    "provider": "gog",
    "sender_policy": "allowlist",
    "sender_allowlist": [
      {
        "address": "andrew@easylabs.io",
        "trust_override": "high",
        "landing_zone_override": "queue-agent"
      },
      {
        "address": "niko@easylabs.io",
        "trust_override": "high"
      },
      {
        "address": "*@partner-company.com",
        "trust_override": "medium",
        "landing_zone_override": "queue-human"
      }
    ]
  }
}
```

The `gog` utility handles Gmail OAuth authentication for the email connector. It manages token refresh and provides IMAP access without storing raw credentials.

#### Tiered Trust Behavior

- **`verified`** (GitHub commits, signed deploys): Notes are auto-promoted from the inbox to their correct location in the organized graph. The curator adds wikilinks and frontmatter but does not gate on content review.
- **`high`** (agent facts, trusted filesystem): Light curator review. The curator checks for duplicates and contradictions, then fast-promotes. Typically processed within one curator cycle.
- **`medium`** (Slack, known email senders): Curator classifies the note (determines category, tags, target folder), checks for relevance and duplication, then promotes. May sit in inbox for 1-2 curator cycles.
- **`low`** (external AI, unknown sources): Curator must validate content before promoting. Notes are tagged `status: unverified` and remain in the inbox until a human or high-trust source confirms them. If unconfirmed after 30 days, auto-archived.

---

## 3. Curator Engine

### 3.1 Dual Loop Architecture

The curator operates on two loops: a scheduled loop for batch processing, and a reactive loop for time-sensitive events.

#### Scheduled Loop (cron, every 2-6 hours)

Runs as an OpenClaw cron job with a dedicated skill: `@skill:curator-maintenance`

```bash
openclaw cron add \
  --every 4h \
  --skill curator-maintenance \
  --description "Run curator maintenance cycle"
```

Steps executed per cycle:

1. **Process inbox** -- Classify and route notes from all `queue-*` folders. Each note is analyzed for category, tags, relevance, and trust level. Notes are moved to their target folder or held for review.

2. **Run mycelium consolidation** -- Execute the full consolidation pipeline from `plugin/lib/consolidation.py`:
   - Compute storage and retrieval strength for all notes
   - Run spreading activation from recently-traversed notes
   - Identify pruning candidates (low S + low R)
   - Protect tendril nodes in active categories
   - Prune low-value notes to archive
   - Reinforce recently-accessed paths

3. **Weave wikilinks** -- Scan for related notes using title matching, tag overlap, and content similarity. Add `[[backlinks]]` between related notes. Remove broken links to deleted/archived notes.

4. **Staleness scan** -- Compute staleness scores for all notes. Flag notes exceeding thresholds (see Section 9). Move review-needed notes to `05_Inbox/review-stale/`.

5. **Conflict resolution** -- Detect Obsidian Sync conflict files (e.g., `note (conflict 2026-03-21).md`). Attempt auto-merge when changes are to different sections. Escalate contradicting changes to human review.

6. **Schema enforcement** -- Validate that all notes have required frontmatter fields (title, category, tags, created, updated, author, source, status). Add missing fields with sensible defaults. Flag malformed notes for review.

7. **Index update** -- Regenerate `00_Index.md` with current folder counts and recent changes. Update per-folder `index.md` files with note listings and statistics.

8. **Health report** -- Compute graph health metrics (note count, orphan rate, staleness distribution, link density). Optionally send summary via Slack or email connector. Write report to `05_Inbox/curator-health-report.md`.

#### Reactive Loop (filesystem watch via ob sync)

The curator also watches for filesystem changes in real-time via `ob sync --continuous`:

1. **New file in `queue-*`** -- Fast classify and route. If from a high-trust source, promote immediately without waiting for the scheduled cycle.

2. **Conflict file detected** -- Immediate merge attempt. If auto-merge succeeds, delete the conflict file. If not, create a review task.

3. **High-trust source** -- Fast-promote path. Verified and high-trust notes bypass the queue and go directly to their target folder with basic frontmatter validation.

### 3.2 Mycelium Integration

The curator runs the algorithms already implemented in `plugin/lib/mycelium.py`:

| Algorithm | Function | Purpose |
|---|---|---|
| Spreading activation | `spreading_activation()` | Propagate relevance from recently-traversed notes (Collins & Loftus, alpha=0.7 decay per hop, max of incoming activations) |
| Path reinforcement | `reinforce_access_paths()` | Strengthen frequently-used knowledge pathways (boost confidence on traversed node edges, bidirectional) |
| Flow score | `compute_flow_score()` | Identify hub nodes critical for graph connectivity (betweenness centrality proxy via sampled shortest paths) |
| Self-healing | `heal_broken_paths()` | Reconnect orphaned neighbors after pruning (find nearest hub by embedding similarity, add bidirectional edges) |
| Storage strength | `compute_storage_strength()` | FSRS-inspired strength from access count: `S = min(1.0, 0.1 + 0.05 * count)` |
| Retrieval strength | `compute_retrieval_strength()` | FSRS-inspired temporal decay: `R = exp(-days / stability)` where stability grows with count and edges |
| Importance score | `compute_importance_score()` | Combined: `0.4*S + 0.4*R + 0.2*flow` |
| Prediction error | `prediction_error_gate()` | Classify incoming notes as novel, redundant, or contradicting (cosine similarity + contradiction markers) |

The curator also runs:

- **`run_consolidation()`** from `plugin/lib/consolidation.py` -- Full pipeline: load vault, compute strengths, activate, identify prune candidates, protect tendrils, prune, heal, reinforce.
- **`generate_review_queue()`** from `plugin/lib/review_queue.py` -- FSRS-based review queue. Finds notes with low retrieval strength but meaningful storage strength (knowledge once learned, now fading). Prioritizes by `S * (1 - R)`.
- **`detect_knowledge_gaps()`** from `plugin/lib/knowledge_gaps.py` -- Finds sparse categories (under-researched areas), missing bridges (category pairs with no cross-links), and weak bridges (low-confidence cross-links).

### 3.3 Code Intelligence Integration

The curator uses `openclaw-brain-code` (Layer 4) for code-aware knowledge management:

**Proactive invalidation:**
When a major refactor merges, `brain-code impact <repo-path> <file>` identifies affected files. The curator scans the vault for notes mentioning those files and flags them as potentially outdated. This creates targeted review tasks rather than relying solely on time-based staleness.

**PR enrichment:**
The GitHub connector can call `brain-code symbols <repo-path> --pattern <regex>` to add symbol-level context to PR summary notes. Instead of just listing changed files, the note includes which functions, classes, and interfaces were modified.

**Dependency tracking:**
When a dependency is upgraded (detected by the GitHub connector watching `package.json`, `requirements.txt`, etc.), the curator checks `04_Systems/` for architecture docs that reference the upgraded dependency and flags them for review.

**GitNexus (optional):**
GitNexus enhances code intelligence with multi-language AST analysis. It provides deeper symbol resolution, cross-file call chains, and dependency graphs. Installed during the INSTALL.sh wizard if the user opts in. The curator uses it when available; falls back to the built-in `brain-code` AST analysis when not.

---

## 4. Onboarding and Discovery

### 4.1 Wizard Modes

The INSTALL.sh wizard asks for the operating mode and configures accordingly:

**Standalone (default):**
- Current behavior, no changes
- All brain commands active, local vault
- No ob sync required

**Connected:**
- Prompts for curator URL and invite token
- Runs `ob login` (interactive)
- Sets up `ob sync --continuous` as a daemon
- Configures shared vault path
- Disables local mutation commands (brain-expand --consolidate, brain-resolve, obsidian optimize)
- Starts heartbeat monitoring

**Curator:**
- Full server setup
- Connector configuration (which sources to enable)
- Mycelium schedule configuration (cycle interval)
- Git backup setup (remote, branch, push interval)
- Health endpoint configuration (port, token)
- Invite token generation for connected nodes
- Optional: GitNexus installation for enhanced code intelligence

### 4.2 Dependency Installation in Wizard

During the wizard's advanced section, the installer detects and offers to install optional dependencies:

**GitNexus (Layer 4 Code Intelligence):**
1. Check: `npx gitnexus --version`
2. If missing, offer: `npm install -g gitnexus`
3. If installed, run initial analysis on current repo: `npx gitnexus analyze`
4. Set `CODE_GRAPH_ENABLED=true` in env config

**lossless-claw (LCM Context Engine):**
1. Check: `ls ~/.openclaw/extensions/lossless-claw`
2. If missing, offer: `openclaw plugins install @martian-engineering/lossless-claw`
3. Verify `~/.openclaw/lcm.db` exists after install
4. Set `LACP_CONTEXT_ENGINE=lossless-claw` in env config

**obsidian-headless (Required for Connected and Curator modes):**
1. Check: `ob --version`
2. If missing, offer: `npm install -g obsidian-headless`
3. Required -- Connected and Curator modes cannot proceed without it
4. Standalone mode does not require it

All dependency installs handle failures gracefully. If an install fails, the wizard logs the error, sets the config to work without the dependency, and continues.

### 4.3 `openclaw-lacp-connect` CLI

The `openclaw-lacp-connect` command manages the connection between agent nodes and the curator.

**Commands:**

| Command | Description |
|---|---|
| `invite --email <addr> --role <role>` | Generate and send an invite token (curator admin only) |
| `join --token <token>` | Connect to a shared vault using an invite token |
| `status` | Show connection status, vault stats, sync daemon info |
| `disconnect` | Disconnect from shared vault (keeps local copy) |
| `pause` | Pause sync (keep local copy, stop daemon) |
| `resume` | Resume sync (restart daemon) |
| `set-role --role <role>` | Change agent role (developer, pm, executive, readonly) |
| `health` | Detailed health check (sync lag, conflict count, inbox size) |
| `members` | List all connected members (curator admin only) |

**Join Flow:**

```
openclaw-lacp-connect join --token <invite-token>
```

1. **Validate invite** -- POST to curator `/validate` endpoint with the invite token. Curator returns vault config (name, encryption password hint, role) if valid.
2. **Obsidian login** -- Run `ob login` (interactive). User enters their Obsidian account credentials.
3. **Sync setup** -- Run `ob sync-setup --vault "Company Brain" --path ~/.openclaw/vault`.
4. **Start sync daemon** -- Start `ob sync --continuous` as a background daemon (launchd on macOS, systemd on Linux).
5. **Configure shared vault** -- Update LACP config: set `LACP_OBSIDIAN_VAULT=~/.openclaw/vault`, set `LACP_MODE=connected`, set `LACP_CURATOR_URL`.
6. **Disable mutation commands** -- Set `LACP_MUTATIONS_ENABLED=false`. This blocks brain-expand --consolidate, brain-resolve, and obsidian optimize from running locally.
7. **Start heartbeat** -- Begin heartbeat monitoring (see Section 5).
8. **Confirm** -- Display: "Connected to Company Brain (4,231 notes, last sync: 2s ago)"

### 4.4 Curator Discovery

The curator exposes a minimal HTTP surface -- three endpoints, all behind token authentication:

**`POST /validate`**
Validate an invite token. Returns vault config and role assignment.
```json
// Request
{ "token": "inv_abc123..." }

// Response
{ "valid": true, "vault_name": "Company Brain", "role": "developer", "ob_sync_config": {...} }
```

**`POST /health`**
Agent health check. Returns curator status, last cycle time, graph stats.
```json
// Response
{ "status": "healthy", "last_cycle": "2026-03-21T14:30:00Z", "notes": 4231, "inbox_pending": 12 }
```

**`POST /notify`**
Fast-path notification for high-priority inbox items. Agents can notify the curator when they write something urgent to the inbox, triggering the reactive loop.
```json
// Request
{ "file": "05_Inbox/queue-agent/critical-bug-pattern.md", "priority": "high" }
```

Everything else flows through the vault filesystem via Obsidian Sync. No REST API for CRUD operations on notes. The vault IS the API.

---

## 5. Heartbeat and Outage Handling

The curator writes a heartbeat file to the shared vault at the end of every scheduled cycle:

**File:** `~/.openclaw/vault/.curator-heartbeat.json`

```json
{
  "last_seen": "2026-03-21T14:30:00Z",
  "status": "healthy",
  "cycle_duration_seconds": 42,
  "notes_processed": 18,
  "next_cycle": "2026-03-21T18:30:00Z",
  "missed_heartbeats": 0,
  "outage_log": [
    {
      "start": "2026-03-19T02:00:00Z",
      "end": "2026-03-19T06:15:00Z",
      "files_queued_during_outage": 7,
      "reconciliation_status": "completed"
    }
  ]
}
```

### Degradation Behavior

**Curator down (agents keep working):**
- Agents continue reading from their local vault copy (last synced state).
- New facts are written to `05_Inbox/queue-agent/` as normal. The inbox accumulates.
- Obsidian Sync continues relaying between connected nodes -- agents can see each other's inbox writes.

**3+ missed heartbeats (alert):**
- Connected agents log a warning: "Curator heartbeat missed (last seen: 4h ago)"
- Notify admin via configured channel (Slack, email, or stdout).
- Optionally enable lightweight local dedup during extended outages to prevent inbox bloat.

**Curator recovers:**
- On first cycle after recovery, curator processes the outage backlog first (all accumulated inbox items).
- Outage is logged to the `outage_log` array with file count and reconciliation status.
- Once backlog is cleared, marks outage as `reconciliation_status: "completed"` and resumes normal schedule.

---

## 6. Vault Structure and Schema

### Folder Tree

```
Company Brain/
├── 00_Index.md                          # Master index (curator-maintained)
│
├── 01_Projects/                         # Per-repo/per-project knowledge
│   ├── easy-api/
│   │   ├── index.md
│   │   ├── architecture.md
│   │   ├── api-patterns.md
│   │   ├── bug-patterns.md
│   │   └── onboarding.md
│   ├── easy-dashboard/
│   ├── easy-checkout/
│   └── easy-sdk/
│
├── 02_Concepts/                         # Cross-project knowledge
│   ├── authentication-patterns.md
│   ├── database-migration-strategy.md
│   ├── error-handling-conventions.md
│   └── testing-philosophy.md
│
├── 03_People/                           # Team context (opt-in)
│   ├── andrew.md
│   ├── niko.md
│   └── team-structure.md
│
├── 04_Systems/                          # Infrastructure and architecture
│   ├── deployment-architecture.md
│   ├── payment-flow.md
│   ├── auth-system.md
│   └── monitoring.md
│
├── 05_Inbox/                            # Unsorted incoming notes
│   ├── queue-agent/                     # Agent-submitted (auto-classified by curator)
│   ├── queue-cicd/                      # CI/CD-submitted PR summaries, deploy notes
│   ├── queue-human/                     # Human-submitted (drag-and-drop, email, Slack)
│   ├── queue-external/                  # External/low-trust sources
│   └── review-stale/                    # Curator-flagged notes needing human review
│
├── 06_Planning/                         # Product planning
│   ├── roadmap-q2-2026.md
│   ├── feature-treasury-v2.md
│   ├── feature-mobile-app.md
│   └── user-research/
│
├── 07_Research/                         # Research findings
│   ├── competitor-analysis/
│   ├── technology-evaluations/
│   └── market-research/
│
├── 08_Strategy/                         # Executive-level docs
│   ├── company-direction-2026.md
│   ├── hiring-plan.md
│   ├── fundraising-notes.md
│   └── partnerships/
│
├── 09_Changelog/                        # Auto-generated from git/CI
│   ├── branches/                        # Active feature branches
│   ├── merged/                          # Archived merged branches
│   ├── releases/                        # Release notes
│   ├── deploys/                         # Deploy logs
│   └── environments/                    # Current state per environment
│       ├── staging.md
│       ├── production.md
│       └── feature-branches.md
│
├── 10_Templates/                        # Note templates
│   ├── project-note.md
│   ├── meeting-note.md
│   ├── decision-record.md
│   ├── bug-report.md
│   └── pr-summary.md
│
└── .obsidian/                           # Synced Obsidian config
    ├── plugins/
    └── templates/
```

### Standardized Frontmatter Schema

Every note in the shared vault must have standardized frontmatter. The curator enforces this schema during inbox processing and scheduled validation.

```yaml
---
title: "API Authentication Architecture"           # Required. Human-readable title.
category: systems                                   # Required. Maps to folder: projects, concepts,
                                                    #   people, systems, inbox, planning, research,
                                                    #   strategy, changelog, templates.
tags: [auth, auth0, supabase, security]             # Required. At least one tag.
created: 2026-03-15                                 # Required. ISO date.
updated: 2026-03-21                                 # Required. ISO date, updated on any edit.
author: wren                                        # Required. Agent name or human name.
source: agent-promoted                              # Required. How it got here:
                                                    #   agent-promoted, ci-cd, human, curator,
                                                    #   connector-github, connector-slack,
                                                    #   connector-email, connector-webhook.
project: easy-api                                   # Optional. Associated project.
status: active                                      # Required. One of: active, review, stale,
                                                    #   unverified, archived.
last_traversed: 2026-03-21                          # Auto-managed. Last agent context injection.
traversal_count: 12                                 # Auto-managed. Total agent context injections.
confidence: 0.85                                    # Auto-managed. Curator's confidence score,
                                                    #   derived from freshness, traversals, and
                                                    #   source trust.
---
```

---

## 7. Local Command Behavior by Mode

| Command | Standalone | Connected | Curator |
|---|---|---|---|
| `brain-expand --consolidate` | Runs locally | BLOCKED (curator-managed) | Runs as part of curator loop |
| `brain-resolve` | Runs locally | BLOCKED | Runs as part of curator loop |
| `brain-ingest` | Writes to graph directly | Redirected to `05_Inbox/queue-agent/` | Runs as part of connector pipeline |
| `brain-graph index` | Runs locally | Allowed (read + index) | Runs as part of curator loop |
| `brain-code analyze` | Runs locally | Runs locally | Runs for code intelligence |
| `brain-code impact` | Runs locally | Runs locally | Runs for proactive invalidation |
| `brain-code symbols` | Runs locally | Runs locally | Runs for PR enrichment |
| `memory-kpi` | Runs locally | Allowed (read-only) | Runs as part of health report |
| `obsidian optimize` | Runs locally | BLOCKED | Runs as part of curator loop |
| `lacp_memory_query` (tool) | Queries local vault | Queries synced vault (read) | N/A |
| `lacp_promote_fact` (tool) | Writes directly | Writes to `05_Inbox/queue-agent/` | N/A |
| `lacp_ingest` (tool) | Writes directly | Writes to `05_Inbox/queue-agent/` | N/A |
| `lacp_guard_status` (tool) | Local guard | Local guard | N/A |
| `openclaw-guard` | Local | Local | Local |

**BLOCKED commands** in Connected mode display a message:

```
[LACP] brain-expand --consolidate is managed by the curator in Connected mode.
       Your changes will be processed in the next curator cycle.
       To run locally, switch to Standalone mode: openclaw-lacp-connect disconnect
```

**Redirected commands** in Connected mode silently write to the inbox queue instead of the organized graph. The agent sees confirmation that the note was queued:

```
[LACP] Fact queued for curator processing: 05_Inbox/queue-agent/api-auth-pattern-20260321.md
       Expected promotion within 4 hours (next curator cycle).
```

---

## 8. CI/CD Integration

### GitHub Action Template

A reusable GitHub Action generates vault notes from repository events:

```yaml
name: Vault Sync
on:
  pull_request:
    types: [opened, synchronize, closed]
  push:
    branches: [main, staging]
  deployment:
  release:
    types: [published]

jobs:
  vault-note:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Generate vault note
        uses: openclaw/vault-note-action@v1
        with:
          curator_url: ${{ secrets.CURATOR_URL }}
          curator_token: ${{ secrets.CURATOR_TOKEN }}
          event: ${{ github.event_name }}
          template: pr-summary  # from 10_Templates/
```

For teams without a curator, the action can write directly to a git-backed vault:

```yaml
      - name: Write to vault (git mode)
        uses: openclaw/vault-note-action@v1
        with:
          mode: git
          vault_repo: company/company-brain
          vault_token: ${{ secrets.VAULT_GITHUB_TOKEN }}
```

### Branch Lifecycle

```
Branch created (push)
  -> 09_Changelog/branches/<branch-name>/ created
  -> index.md generated with branch metadata

PR opened
  -> PR-<number>.md created in branch folder
  -> Summary generated from diff + commit messages
  -> brain-code symbols called for symbol-level context (if curator available)

PR updated (new commits)
  -> PR-<number>.md updated with latest diff summary
  -> Changed files list refreshed

PR merged
  -> Branch folder moved to 09_Changelog/merged/<branch-name>-<date>/
  -> PR note updated with merge metadata (merge commit, reviewer, merge date)
  -> Curator cross-links to relevant project notes in 01_Projects/

Branch deleted
  -> Handled by merge step above
  -> If deleted without merge, folder archived with "abandoned" status

Deploy to staging
  -> 09_Changelog/deploys/staging-<date>.md created
  -> Links to all PRs included in this deploy
  -> 09_Changelog/environments/staging.md updated

Deploy to production
  -> 09_Changelog/releases/v<version>.md created
  -> Full release notes aggregated from merged PRs since last release
  -> 09_Changelog/environments/production.md updated
```

### Environment-Aware Documentation

Each environment gets an auto-maintained status document:

- **`staging.md`** -- "What's on staging right now." Updated on each staging deploy. Lists all PRs deployed, current commit SHA, deploy timestamp, and any known issues.
- **`production.md`** -- "What's in production." Updated on each production deploy. Includes current version, release notes link, and rollback instructions.
- **`feature-branches.md`** -- "Active feature work." Lists all active branches, their PR status, and last activity. Updated on branch create/delete/PR events.

These files are always current -- any agent can read them to understand the state of any environment.

---

## 9. Staleness Detection

### Scoring Formula

```
staleness_score = days_since_traversed / (traversal_count + 1)
```

This formula balances recency against frequency. A note traversed 100 times but not in 30 days scores 0.29 (active). A note traversed once and not in 30 days scores 15.0 (aging).

### Thresholds and Curator Actions

| Score Range | Classification | Curator Action |
|---|---|---|
| < 10 | **Active** | No action. Note is recently and frequently used. |
| 10 - 30 | **Aging** | Monitor. Note is used but not recently. No intervention. |
| 30 - 90 | **Stale** | Add `status: stale` to frontmatter. Check for contradictions with newer notes. If contradictions found, create a merge/review task in `05_Inbox/review-stale/`. |
| > 90 | **Review needed** | Move to `05_Inbox/review-stale/`. Notify the original author's agent: "Is this still accurate?" If no response in 14 days, archive to `99_Archive/`. |

### Proactive Invalidation Triggers

Beyond time-based staleness, certain events trigger immediate review:

| Trigger | Detection Method | Curator Action |
|---|---|---|
| **Major refactor merged** | GitHub connector detects large PR (>20 files changed). `brain-code impact` identifies affected symbols. | Scan `01_Projects/` and `02_Concepts/` for notes referencing affected files/symbols. Flag as potentially outdated with diff summary. |
| **Dependency upgraded** | GitHub connector detects changes to `package.json`, `requirements.txt`, `go.mod`, etc. | Check `04_Systems/` for architecture docs referencing the upgraded package. Flag for review with version change context. |
| **Team member leaves** | Manual trigger or HR connector event. | Review all notes authored by that person. Create handoff tasks for notes with `status: active` and high traversal count. |
| **Strategic pivot** | Executive updates `08_Strategy/`. | Curator propagates to affected planning docs in `06_Planning/`. Flag conflicting roadmap items. |

### Code Intelligence Cross-Reference

For code-related notes (category `projects` or `systems`), the curator cross-references with git history:

1. Extract file paths and symbol names mentioned in the note.
2. Query `brain-code impact` or `git log` for those files since the note's `updated` date.
3. If files have been significantly modified (>30% of lines changed), flag the note as potentially outdated.
4. Include a summary of what changed in the review task.

---

## 10. Open Questions

1. **Obsidian Sync pricing for teams** -- Does the current plan support enough shared vault members? What's the per-seat cost? Need to verify pricing tiers support 5-15 members.

2. **obsidian-headless stability** -- It's in open beta. How reliable is `--continuous` mode for always-on daemon use? **Mitigation:** Build a watchdog/restart mechanism into the daemon management (launchd/systemd will handle restarts, but we need health checks).

3. **Plugin compatibility** -- obsidian-headless syncs `.obsidian/` config including community plugins. If one team member installs a plugin that modifies vault structure, does it affect everyone? **Proposed answer:** Use `.obsidian/` sync selectively. The curator manages plugin config; connected nodes pull but don't push `.obsidian/` changes.

4. **Vault encryption password management** -- E2EE requires a shared password. How do we distribute this securely during invite flow? **Proposed answer:** The `/validate` endpoint returns an encrypted hint. The actual password is communicated out-of-band (in person, secure message).

5. **Git vs Obsidian Sync for CI/CD** -- Should GitHub Actions use `ob sync` (requires Obsidian credentials on runner) or git-based vault? **Proposed answer:** Support both. Git mode for CI/CD writes (simpler, no credentials on runner). The curator pulls from the git-backed vault into the Obsidian-synced vault.

6. **Offline behavior** -- If an agent is offline for days and writes many vault changes, will sync catch up cleanly? **Mitigation:** Connected nodes only write to inbox queues (small, timestamped files). No edit conflicts possible. Curator handles dedup on recovery.

7. **GDPR/compliance** -- `03_People/` contains employee data. Obsidian Sync is E2EE, but local copies exist on every synced machine. **Mitigation:** Make `03_People/` opt-in per connected node via `ob sync-config --excluded-folders`. Sensitive docs can use a separate restricted vault.

8. **Vault backup strategy** -- Obsidian Sync has version history, but should we also run git backups? **Answer:** Yes. The curator runs periodic `git commit + push` to a private repo. This is a hard requirement for the curator mode, configured during wizard setup.

9. **ob sync bandwidth** -- E2EE means full file contents are synced (no server-side diffing). Large vaults with frequent changes could use meaningful bandwidth. **Mitigation:** Configure `--excluded-folders` for heavy media. Monitor bandwidth in health reports. Consider archival strategy after vault exceeds 10,000 notes.

10. **Conflict resolution edge cases** -- What happens when two agents write to the same inbox queue file simultaneously? **Answer:** Inbox queue files are timestamped with agent ID in the filename (e.g., `api-pattern-wren-20260321T143000.md`). No two agents write the same file. Conflicts can only occur on organized graph notes, which only the curator edits.

---

## 11. Implementation Phases

### Phase 1: Foundation
**Status:** Partially complete

- [x] Mycelium algorithms (`plugin/lib/mycelium.py`) -- DONE
- [x] Consolidation pipeline (`plugin/lib/consolidation.py`) -- DONE
- [x] Review queue (`plugin/lib/review_queue.py`) -- DONE
- [x] Knowledge gap detection (`plugin/lib/knowledge_gaps.py`) -- DONE
- [ ] Port `brain-resolve` from LACP (contradiction/supersession resolution)
- [ ] Port `memory-kpi` from LACP (vault quality metrics)
- [ ] Port `obsidian optimize` from LACP (graph physics tuning)
- [ ] Standalone mode fully operational with all brain commands

**Deliverable:** A single-machine LACP installation with full mycelium-powered knowledge management.

### Phase 2: Shared Vault
- [ ] `openclaw-lacp-connect` CLI (invite, join, status, disconnect, pause, resume, set-role, health, members)
- [ ] `ob sync --continuous` daemon management (launchd on macOS, systemd on Linux, watchdog)
- [ ] Curator discovery HTTP surface (3 endpoints: /validate, /health, /notify)
- [ ] Heartbeat file and outage detection
- [ ] Mode switching in LACP config (standalone/connected/curator)
- [ ] Command blocking/redirection in Connected mode

**Deliverable:** Two or more machines sharing a vault via Obsidian Sync, with one curator and N connected agents.

### Phase 3: Curator Engine
- [ ] Scheduled loop (cron job with curator-maintenance skill)
- [ ] Reactive loop (filesystem watch for inbox changes)
- [ ] Inbox processing (classify, route, promote)
- [ ] Wikilink weaving (title match, tag overlap, content similarity)
- [ ] Staleness scan and scoring
- [ ] Conflict file detection and auto-merge
- [ ] Schema enforcement
- [ ] Index regeneration (00_Index.md + per-folder indexes)
- [ ] Health report generation

**Deliverable:** Autonomous curator that maintains graph quality without human intervention.

### Phase 4: Connectors
- [ ] Connector interface and base class
- [ ] Connector configuration (`config/connectors.json`)
- [ ] Trust and sender verification framework
- [ ] GitHub connector (PR summaries, branch lifecycle, deploy events)
- [ ] Slack connector (channel messages, thread summaries)
- [ ] Email connector (IMAP/gog, per-sender routing)
- [ ] Generic webhook connector (HMAC, custom transforms)
- [ ] Generic cron-fetch connector (poll URLs on schedule)
- [ ] Filesystem connector (watch directories)
- [ ] Community connector packaging and install mechanism

**Deliverable:** External knowledge sources feeding into the vault automatically.

### Phase 5: CI/CD Pipeline
- [ ] GitHub Action template (`openclaw/vault-note-action`)
- [ ] PR summary note generation (diff + commit messages + symbols)
- [ ] Branch lifecycle management (create/merge/delete)
- [ ] Deploy tracking (staging, production)
- [ ] Environment status documents (staging.md, production.md, feature-branches.md)
- [ ] Release note aggregation

**Deliverable:** Repository activity automatically documented in the vault.

### Phase 6: Advanced
- [ ] Multi-vault topology (master + child vaults, cross-vault sync)
- [ ] Real-time presence (which agents are active, what they're working on)
- [ ] Knowledge graph visualization (Obsidian graph view via Publish or custom dashboard)
- [ ] Proactive invalidation via code intelligence (refactor detection, dependency changes)
- [ ] Cross-vault search via QMD embeddings
- [ ] Smart routing (curator auto-classifies to correct vault based on content)

**Deliverable:** Enterprise-scale knowledge management for larger teams.

---

## 12. Success Metrics

| Metric | Target | How Measured |
|---|---|---|
| **Knowledge graph density** | Average 3+ backlinks per note | Curator health report (wikilink count / note count) |
| **Staleness ratio** | < 5% of notes with staleness_score > 90 | Curator staleness scan |
| **Agent utilization** | > 70% of sessions inject facts from shared vault | `session-start.py` injection metadata |
| **Time to knowledge** | < 5 minutes from event to availability in all agents | Timestamp delta: connector ingest -> ob sync propagation |
| **Curator efficiency** | > 85% of inbox notes auto-classified correctly | Curator classification accuracy (sampled by human review) |
| **Zero-context starts** | > 90% of new sessions have useful pre-loaded context | `session-start.py` injection count > 0 |
| **Orphan rate** | < 3% of notes with zero backlinks | `knowledge_gaps.py` sparse category detection |
| **Connector uptime** | > 99% health check pass rate per connector | Connector `health_check()` logs |
| **Outage recovery** | < 1 curator cycle to reconcile after outage | Heartbeat outage_log reconciliation timestamps |
| **Review queue turnaround** | < 7 days for stale notes to be reviewed or archived | `review_queue.py` queue age tracking |
