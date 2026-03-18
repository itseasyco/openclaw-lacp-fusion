# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-03-18

### Attribution

This release is based on the original [LACP](https://github.com/0xNyk/lacp) architecture by [0xNyk](https://github.com/0xNyk).

**Credits:**
- **Original LACP concept & design:** 0xNyk
- **OpenClaw plugin adaptation:** Easy Labs + OpenClaw Community
- **Implementation & testing:** 11-agent fleet (2.5 hours)

### Added

**Phase 1: Execution Hooks**
- session-start hook for git context injection
- pretool-guard hook for dangerous pattern blocking (18 patterns)
- stop-quality-gate hook for quality enforcement
- write-validate hook for schema validation
- 3 safety profiles (minimal-stop, balanced, hardened-exec)
- 60 unit tests for hooks system

**Phase 2: Policy Gates**
- Risk-based policy routing (safe/review/critical tiers)
- Cost ceiling enforcement per tier ($1/$10/$100)
- Approval caching with TTL (30 min default)
- openclaw-gated-run wrapper for policy enforcement
- JSONL audit logging for all executions
- 44 integration tests for policy system

**Phase 3: Session Memory**
- Per-project memory scaffolding
- openclaw-memory-init script for memory initialization
- openclaw-memory-append script for execution logging
- Structured JSON metadata (cost, gates, exit codes, learnings)
- Per-session git repositories for change tracking
- 18 functional tests for memory system

**Phase 4: Evidence Verification**
- Task schema specification (JSON Schema Draft-07)
- Harness contract definition for verification modes
- openclaw-verify verification engine
- Hybrid verification (test-based + LLM + heuristic)
- Evidence artifact collection
- 18 verification tests

**Documentation**
- Complete user guide (800+ lines)
- Deployment guide for OpenClaw integration
- Memory scaffolding architecture documentation
- Policy configuration reference
- Routing engine reference
- Contributing guidelines
- Code of conduct

**Infrastructure**
- Installation script with prerequisite checking
- Plugin manifest (plugin.json)
- MIT License
- .gitignore for Python/Node projects
- GitHub Actions CI workflow
- Issue templates (bug, feature request)

### Test Coverage
- 122/122 tests passing (100%)
- All critical paths covered
- Integration tests for all phases
- Error handling and edge cases

### Known Limitations
- Remote sandbox routing (E2B/Daytona) not included
- Obsidian vault integration optional
- Performance tuning deferred to v1.1.0

---

## Future Versions

### [1.0.1] - TBD
- Bug fixes and stability improvements
- Performance optimizations
- Enhanced error messages

### [1.1.0] - TBD
- Optional Obsidian vault integration
- Custom hook plugins support
- Web dashboard for approval management
- Slack/Discord notifications

### [1.2.0] - TBD
- Advanced memory mycelium (spreading activation)
- Extended policy rule languages
- CI/CD pipeline integration templates

### [2.0.0] - TBD
- Breaking API changes (if any)
- Major architectural improvements
- Full remote sandbox support

---

## Versioning

This project follows [Semantic Versioning](https://semver.org/):

- **MAJOR** version for incompatible API changes
- **MINOR** version for new features in a backwards compatible manner
- **PATCH** version for backwards compatible bug fixes

---

## How to Upgrade

### From 1.0.0 to 1.0.1 (when available)

```bash
# Backup current
cp -r ~/.openclaw/plugins/openclaw-lacp-fusion ~/.openclaw/plugins/openclaw-lacp-fusion.1.0.0

# Download and install new version
wget https://github.com/itseasyco/openclaw-lacp-fusion/releases/download/v1.0.1/openclaw-lacp-fusion-1.0.1.zip
unzip openclaw-lacp-fusion-1.0.1.zip
cd openclaw-lacp-fusion
bash INSTALL.sh

# Verify
python3 -m pytest ~/.openclaw/plugins/openclaw-lacp-fusion/hooks/tests/ -v
```

### From 1.0.x to 2.0.0 (when available)

Breaking changes will be documented in the release notes. A migration guide will be provided.

---

## Credits

- **Agent Fleet:** 11 agents across 4 phases
- **Build Time:** ~2.5 hours
- **Code:** 15,000+ lines
- **Tests:** 122 tests
- **Documentation:** 2,650+ lines

---

## Support

- **GitHub Issues:** https://github.com/itseasyco/openclaw-lacp-fusion/issues
- **Discord:** https://discord.com/invite/clawd
- **Email:** plugins@openclaw.ai

---

## License

Copyright (c) 2026 OpenClaw Community

Licensed under the MIT License. See [LICENSE](./LICENSE) file for details.
