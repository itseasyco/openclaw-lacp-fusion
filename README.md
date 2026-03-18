# OpenClaw LACP Fusion Plugin

A complete, production-ready plugin system for OpenClaw that brings **LACP (Local Agent Control Plane)** capabilities — execution hooks, policy gates, session memory, and evidence verification.

> **Based on:** [LACP by 0xNyk](https://github.com/0xNyk/lacp) — adapted and extended for OpenClaw integration

## Features

### 🔐 Execution Hooks (Phase 1)
- **session-start** — Git context injection at execution start
- **pretool-guard** — Blocks dangerous patterns (npm publish, rm -rf, chmod 777, etc.)
- **stop-quality-gate** — Detects incomplete work (TODOs, test failures, rationalizations)
- **write-validate** — Validates YAML frontmatter schema on file writes

### 🛡️ Policy Gates (Phase 2)
- **Risk-based routing** — Tasks categorized into safe/review/critical tiers
- **Cost ceilings** — Per-tier spending limits ($1/$10/$100)
- **Approval caching** — TTL-based approval tracking (30 min default)
- **Gated execution** — Policy enforcement before task execution

### 💾 Session Memory (Phase 3)
- **Per-project sessions** — Isolated memory per project/agent/session
- **Execution logging** — JSON metadata (cost, gate decisions, exit codes)
- **Git history** — Each session gets independent git repo for change tracking

### ✅ Evidence Verification (Phase 4)
- **Task schemas** — Define task structure and success criteria
- **Harness contracts** — Specify verification mode (test-based, LLM, heuristic)
- **Evidence collection** — Artifacts, logs, execution time
- **Verification engine** — Hybrid mode with all three methods simultaneously

## Quick Start

### Installation

```bash
# Download latest release
wget https://github.com/itseasyco/openclaw-lacp-fusion/releases/download/v1.0.0/openclaw-lacp-fusion-1.0.0.zip

# Extract and install
unzip openclaw-lacp-fusion-1.0.0.zip
cd openclaw-lacp-fusion
bash INSTALL.sh

# Verify
python3 -m pytest ~/.openclaw/plugins/openclaw-lacp-fusion/hooks/tests/ -v
```

### Select a Profile

```bash
echo "balanced" > ~/.openclaw/plugins/openclaw-lacp-fusion/.profile
```

Options: `minimal-stop` (dev), `balanced` (recommended), `hardened-exec` (production)

### Test It

```bash
# Check policy routing
~/.openclaw/plugins/openclaw-lacp-fusion/bin/openclaw-route \
  --agent wren --channel webchat --task "git commit"

# Run gated execution
~/.openclaw/plugins/openclaw-lacp-fusion/bin/openclaw-gated-run \
  --task "Test run" --agent wren --channel webchat --estimated-cost-usd 0.01 \
  -- echo "Hello from gated execution"
```

## Documentation

| Document | Purpose |
|----------|---------|
| [COMPLETE-GUIDE.md](./docs/COMPLETE-GUIDE.md) | Full user guide (800+ lines) |
| [DEPLOYMENT-TO-OPENCLAW.md](./docs/DEPLOYMENT-TO-OPENCLAW.md) | Integration steps |
| [MEMORY-SCAFFOLDING.md](./docs/MEMORY-SCAFFOLDING.md) | Memory system architecture |
| [POLICY-GUIDE.md](./docs/POLICY-GUIDE.md) | Policy configuration |
| [ROUTING-REFERENCE.md](./docs/ROUTING-REFERENCE.md) | Routing engine details |

## Requirements

- **OpenClaw:** 0.23.0+
- **Python:** 3.9+
- **Bash:** 5.0+
- **Git:** Any version

All prerequisites are checked automatically during installation.

## Architecture

```
OpenClaw LACP Fusion
├── Phase 1: Hooks
│   ├── session-start.py       Git context injection
│   ├── pretool-guard.py       Dangerous pattern blocking
│   ├── stop-quality-gate.py   Quality gate enforcement
│   └── write-validate.py      Schema validation
├── Phase 2: Policy
│   ├── risk-policy.json       Tier + routing rules
│   └── openclaw-route         Routing engine
├── Phase 3: Memory
│   ├── openclaw-memory-init   Memory initialization
│   └── openclaw-memory-append Execution logging
└── Phase 4: Verification
    ├── task-schema.json       Task definition spec
    └── openclaw-verify        Verification engine
```

## Quality Metrics

| Metric | Value |
|--------|-------|
| **Tests** | 122/122 passing (100%) |
| **Documentation** | 2,650+ lines |
| **Code Quality** | Production-grade |
| **Security** | Full audit logging + pattern blocking |
| **Installation** | One-command setup |

## Usage Examples

### Gated Execution

```bash
# Safe task (no approval needed)
openclaw-gated-run \
  --task "Run tests" \
  --agent zoe \
  --channel engineering \
  --estimated-cost-usd 0.50 \
  -- npm test

# Review task (needs approval)
openclaw-gated-run \
  --task "Deploy to staging" \
  --agent zoe \
  --channel engineering \
  --estimated-cost-usd 5.00 \
  -- ./deploy-staging.sh

# Critical task (needs confirmation)
openclaw-gated-run \
  --task "Production migration" \
  --agent zoe \
  --channel engineering \
  --estimated-cost-usd 50.00 \
  --confirm-budget \
  -- ./migrate-production.sh
```

### Session Memory

```bash
# Initialize new project session
openclaw-memory-init \
  --project "my-project" \
  --agent "zoe" \
  --session "session-001"

# Append execution results
openclaw-memory-append \
  --project "my-project" \
  --agent "zoe" \
  --session "session-001" \
  --cost 2.50 \
  --exit-code 0 \
  --learnings "Successfully deployed new feature"
```

## Monitoring & Audit

All executions logged to `logs/gated-runs.jsonl`:

```bash
# Tail execution log
tail -f ~/.openclaw/plugins/openclaw-lacp-fusion/logs/gated-runs.jsonl | jq .

# Find blocked executions
grep '"gate_decisions":{"blocked":true}' ~/.openclaw/plugins/openclaw-lacp-fusion/logs/gated-runs.jsonl | jq .
```

## Testing

```bash
# Run full test suite
python3 -m pytest tests/ -v

# Run specific phase
python3 -m pytest tests/test_phase1_hooks.py -v

# Coverage report
python3 -m pytest tests/ --cov=. --cov-report=html
```

**Current Status:** 122/122 tests passing ✅

## Troubleshooting

### "Policy gate blocked my task"
- Check logs: `tail -f logs/gated-runs.jsonl`
- Verify routing: `bin/openclaw-route --agent <name> --channel <name> --task "<desc>"`
- Check cost ceiling: Increase or use `--confirm-budget`

### "Hook not executing"
- Verify profile: `cat ~/.openclaw/plugins/openclaw-lacp-fusion/.profile`
- Check handler: `ls ~/.openclaw/plugins/openclaw-lacp-fusion/hooks/handlers/`
- Run tests: `python3 -m pytest tests/`

### "Tests fail after installation"
- Check environment: `python3 --version`, `bash --version`
- Check permissions: `ls -la ~/.openclaw/plugins/openclaw-lacp-fusion/`
- See full error: `python3 -m pytest --tb=long`

## Contributing

We welcome contributions! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Write tests for your changes
4. Ensure all tests pass (`python3 -m pytest tests/ -v`)
5. Submit a pull request

## License

MIT License — See [LICENSE](./LICENSE) file

## Support

- **Issues:** https://github.com/itseasyco/openclaw-lacp-fusion/issues
- **Discord:** https://discord.com/invite/clawd
- **Email:** plugins@openclaw.ai

## Release History

- **1.0.0** (2026-03-18) — Initial release
  - All 4 phases complete
  - 122 tests passing
  - Production ready

## Credits

Built by OpenClaw Community through 11 parallel agents (Phases 1-4) in ~2.5 hours.

- **Phase 1 (Hooks):** Agents A-E
- **Phase 2 (Policy):** Agents F-H
- **Phase 3-4 (Memory/Evidence):** Agents I-K

---

**Ready to install?** Download the [latest release](https://github.com/itseasyco/openclaw-lacp-fusion/releases) and run `bash INSTALL.sh`

**Want to contribute?** Fork this repo and submit a PR!

**Questions?** See [COMPLETE-GUIDE.md](./docs/COMPLETE-GUIDE.md) or file an issue

---

## Attribution

This plugin is based on the original [LACP](https://github.com/0xNyk/lacp) project by [0xNyk](https://github.com/0xNyk). 

**Key contributions:**
- Original LACP architecture and concepts from 0xNyk
- OpenClaw plugin adaptation, hooks system, and extensions by the Easy Labs + OpenClaw Community team
- All phases (1-4) built and tested for OpenClaw v0.23.0+
