# Wizard Dependencies & Mode Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add operating mode selection (standalone/connected/curator) and optional dependency installation (GitNexus, lossless-claw, obsidian-headless) to the INSTALL.sh wizard.

**Architecture:** Extend the existing INSTALL.sh wizard with a mode selection step that changes the install flow. Add dependency detection and installation with gum-powered UX (read fallback). All changes are to INSTALL.sh and config generation functions.

**Tech Stack:** Bash 4.0+, gum (optional), npm, openclaw CLI

---

## Task 1: Add mode selection to wizard

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh`

**What:** Insert a mode selection prompt after the safety profile section (line 302) and before the advanced config section (line 304). Store the mode in `WIZARD_MODE`. For Connected mode, prompt for curator URL and invite token. For Curator mode, set placeholder flags.

- [ ] **1a.** Add the `WIZARD_MODE` variable initialization and mode selection prompt. Insert the following block after line 302 (`echo -e "  ${GREEN}...Safety profile...${NC}"` / `echo ""`) and before the `# 4. Advanced config` comment on line 304.

In `run_wizard()`, after the safety profile section (after the line `echo ""` that follows the safety profile confirmation), add:

```bash
    # 4. Operating mode
    echo -e "${BOLD}Operating Mode${NC}"
    echo -e "  ${DIM}Controls how this node participates in the knowledge network.${NC}"
    echo -e "  ${DIM}Standalone is the default — everything runs locally.${NC}"
    echo ""
    local mode_choice
    mode_choice=$(prompt_choice "Mode" \
        "standalone — local vault, all brain commands active (default)" \
        "connected  — sync to shared vault, mutations delegated to curator" \
        "curator    — server node: connectors, mycelium, git backup, invites")
    WIZARD_MODE="${mode_choice%%[[:space:]]*}"
    echo -e "  ${GREEN}✓${NC} Operating mode: $WIZARD_MODE"
    echo ""

    # Connected mode: collect curator URL and invite token
    WIZARD_CURATOR_URL=""
    WIZARD_CURATOR_TOKEN=""
    if [ "$WIZARD_MODE" = "connected" ]; then
        echo -e "${BOLD}Curator Connection${NC}"
        echo -e "  ${DIM}Your curator admin should have given you a URL and invite token.${NC}"
        echo ""
        WIZARD_CURATOR_URL=$(prompt_value "Curator URL" "https://curator.example.com")
        WIZARD_CURATOR_TOKEN=$(prompt_value "Invite token" "")
        if [ -z "$WIZARD_CURATOR_TOKEN" ]; then
            log_warning "No invite token provided — you can set this later via openclaw-lacp-connect join"
        fi
        echo -e "  ${GREEN}✓${NC} Curator URL: $WIZARD_CURATOR_URL"
        echo ""
    fi

    # Curator mode: placeholder flags (full setup is a future task)
    if [ "$WIZARD_MODE" = "curator" ]; then
        echo -e "${BOLD}Curator Server Setup${NC}"
        echo -e "  ${DIM}Full curator configuration (connectors, schedule, git backup, invites)${NC}"
        echo -e "  ${DIM}will be available in a future release. Setting curator flags for now.${NC}"
        echo ""
        log_info "Curator mode flags will be written to config."
        echo ""
    fi
```

- [ ] **1b.** Renumber the subsequent sections. The old `# 4. Advanced config` becomes `# 5. Advanced config`, and the old `# 5. Confirmation` becomes `# 6. Confirmation`.

- [ ] **1c.** Set defaults for `WIZARD_MODE`, `WIZARD_CURATOR_URL`, and `WIZARD_CURATOR_TOKEN` at the top of `run_wizard()` (after the existing variable declarations) so they are always defined:

```bash
    WIZARD_MODE="standalone"
    WIZARD_CURATOR_URL=""
    WIZARD_CURATOR_TOKEN=""
```

- [ ] **1d.** Update the Installation Summary block (around line 394) to include the mode. Add a mode line after the plugin version line:

```bash
    echo -e "  |  Mode:            ${WIZARD_MODE}"
```

And for connected mode, show the curator URL:

```bash
    if [ "$WIZARD_MODE" = "connected" ]; then
        echo -e "  |  Curator URL:     ${DIM}${WIZARD_CURATOR_URL}${NC}"
    fi
```

**Test:**

```bash
# Dry-run: source the file and check that the mode prompt text is present
grep -n "Operating Mode" /Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh
# Expected: one match in the wizard section

grep -n "WIZARD_MODE" /Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh
# Expected: multiple matches (declaration, prompt, summary, export)
```

**Commit:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && git add INSTALL.sh && git commit -m "feat: add operating mode selection (standalone/connected/curator) to wizard

Adds mode prompt after safety profile. Connected mode collects curator URL
and invite token. Curator mode sets placeholder flags for future setup.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Add obsidian-headless detection and install

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh`

**What:** After mode selection, if mode is Connected or Curator, check for `ob --version`. If missing, offer to install `obsidian-headless`. If still missing after the offer, block Connected/Curator with a helpful message and fall back to Standalone.

- [ ] **2a.** Add an `install_obsidian_headless()` helper function after the existing `prompt_browse_directory()` function (around line 205) and before `run_wizard()`:

```bash
# ─── Dependency installers ───────────────────────────────────────────────────

check_and_install_obsidian_headless() {
    # Returns 0 if ob is available, 1 if not
    if command -v ob &>/dev/null; then
        local ob_ver
        ob_ver=$(ob --version 2>/dev/null || echo "unknown")
        log_success "obsidian-headless found (ob $ob_ver)"
        return 0
    fi

    log_warning "obsidian-headless (ob) not found"
    echo -e "  ${DIM}Required for Connected and Curator modes (vault sync via ob sync).${NC}"
    echo ""

    if prompt_yes_no "Install obsidian-headless globally? (npm install -g obsidian-headless)" "y"; then
        echo ""
        if [ "$HAS_GUM" = "true" ]; then
            if gum spin --spinner dot --title "Installing obsidian-headless..." -- npm install -g obsidian-headless 2>/dev/null; then
                log_success "obsidian-headless installed"
            else
                log_error "obsidian-headless installation failed"
                return 1
            fi
        else
            log_info "Installing obsidian-headless (this may take a moment)..."
            if npm install -g obsidian-headless 2>&1 | tail -3; then
                log_success "obsidian-headless installed"
            else
                log_error "obsidian-headless installation failed"
                return 1
            fi
        fi

        # Verify
        if command -v ob &>/dev/null; then
            local ob_ver
            ob_ver=$(ob --version 2>/dev/null || echo "unknown")
            log_success "Verified: ob $ob_ver"
            return 0
        else
            log_error "ob command not found after install — check your PATH"
            return 1
        fi
    else
        log_info "Skipped obsidian-headless installation"
        return 1
    fi
}
```

- [ ] **2b.** In the mode selection section (added in Task 1), after the Connected/Curator prompts but before the Advanced config section, add the ob dependency check:

```bash
    # Dependency: obsidian-headless (required for connected/curator)
    if [ "$WIZARD_MODE" = "connected" ] || [ "$WIZARD_MODE" = "curator" ]; then
        echo -e "${BOLD}Required Dependency: obsidian-headless${NC}"
        echo ""
        if ! check_and_install_obsidian_headless; then
            echo ""
            log_warning "Cannot proceed with $WIZARD_MODE mode without obsidian-headless."
            log_info "Falling back to standalone mode. You can switch later with:"
            log_info "  1. npm install -g obsidian-headless"
            log_info "  2. openclaw-lacp-connect join --token <token>"
            echo ""
            WIZARD_MODE="standalone"
            WIZARD_CURATOR_URL=""
            WIZARD_CURATOR_TOKEN=""
            echo -e "  ${YELLOW}!${NC} Mode changed to: standalone"
            echo ""
        fi
    fi
```

**Test:**

```bash
grep -n "check_and_install_obsidian_headless" /Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh
# Expected: function definition + call site (at least 2 matches)

grep -n "obsidian-headless" /Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh
# Expected: multiple matches (function, prompt text, install command)
```

**Commit:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && git add INSTALL.sh && git commit -m "feat: add obsidian-headless detection and install for connected/curator modes

Checks for ob CLI before allowing connected or curator mode. Offers npm
install -g obsidian-headless with gum spinner. Falls back to standalone
if ob is unavailable after the prompt.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Add GitNexus detection and install

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh`

**What:** In the advanced section, when user enables code intelligence (`WIZARD_CODE_GRAPH`), check for `npx gitnexus --version`. If missing, offer to install globally. Handle failure by setting `CODE_GRAPH_ENABLED=false`.

- [ ] **3a.** Add a `check_and_install_gitnexus()` helper function next to the obsidian-headless helper (in the dependency installers section):

```bash
check_and_install_gitnexus() {
    # Returns 0 if gitnexus is available, 1 if not
    if npx gitnexus --version &>/dev/null 2>&1; then
        local gn_ver
        gn_ver=$(npx gitnexus --version 2>/dev/null || echo "unknown")
        log_success "GitNexus found ($gn_ver)"
        return 0
    fi

    log_warning "GitNexus not found"
    echo -e "  ${DIM}GitNexus provides Layer 4 code intelligence (AST analysis, dependency graphs).${NC}"
    echo ""

    if prompt_yes_no "Install GitNexus globally? (npm install -g gitnexus)" "y"; then
        echo ""
        if [ "$HAS_GUM" = "true" ]; then
            if gum spin --spinner dot --title "Installing GitNexus..." -- npm install -g gitnexus 2>/dev/null; then
                log_success "GitNexus installed"
            else
                log_error "GitNexus installation failed"
                return 1
            fi
        else
            log_info "Installing GitNexus (this may take a moment)..."
            if npm install -g gitnexus 2>&1 | tail -3; then
                log_success "GitNexus installed"
            else
                log_error "GitNexus installation failed"
                return 1
            fi
        fi

        # Verify
        if npx gitnexus --version &>/dev/null 2>&1; then
            log_success "Verified: GitNexus ready"
            return 0
        else
            log_error "gitnexus command not found after install"
            return 1
        fi
    else
        log_info "Skipped GitNexus installation"
        return 1
    fi
}
```

- [ ] **3b.** Replace the existing code graph prompt line in the advanced section. The current line (around line 318) is:

```bash
        WIZARD_CODE_GRAPH=$(prompt_yes_no "Enable code intelligence (AST analysis)?" "n" && echo "true" || echo "false")
```

Replace it with a block that also handles GitNexus detection:

```bash
        WIZARD_CODE_GRAPH="false"
        if prompt_yes_no "Enable code intelligence (AST analysis)?" "n"; then
            echo ""
            echo -e "${BOLD}Dependency: GitNexus${NC}"
            echo ""
            if check_and_install_gitnexus; then
                WIZARD_CODE_GRAPH="true"
                log_success "Code intelligence enabled with GitNexus"
            else
                echo ""
                log_warning "GitNexus not available — code intelligence disabled"
                log_info "Install later: npm install -g gitnexus"
                WIZARD_CODE_GRAPH="false"
            fi
            echo ""
        fi
```

**Test:**

```bash
grep -n "check_and_install_gitnexus" /Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh
# Expected: function definition + call site (at least 2 matches)

grep -n "GitNexus" /Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh
# Expected: multiple matches (function, prompt text, install command, success/fail messages)
```

**Commit:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && git add INSTALL.sh && git commit -m "feat: add GitNexus detection and install in advanced config section

When user enables code intelligence, checks for gitnexus and offers npm
install. Uses gum spinner when available. Falls back to CODE_GRAPH_ENABLED=false
on failure.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Add lossless-claw detection and install

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh`

**What:** When the user selects `lossless-claw` as context engine (or `auto` resolves to check for it), detect if it is installed. If missing, offer to install via `openclaw plugins install`. Verify `lcm.db` exists. Fall back to file-based on failure.

- [ ] **4a.** Add a `check_and_install_lossless_claw()` helper function in the dependency installers section:

```bash
check_and_install_lossless_claw() {
    # Returns 0 if lossless-claw is available, 1 if not
    if [ -d "$OPENCLAW_HOME/extensions/lossless-claw" ]; then
        log_success "lossless-claw found at $OPENCLAW_HOME/extensions/lossless-claw"
        return 0
    fi

    log_warning "lossless-claw not found"
    echo -e "  ${DIM}lossless-claw provides the native LCM database context engine.${NC}"
    echo ""

    if prompt_yes_no "Install lossless-claw? (openclaw plugins install @martian-engineering/lossless-claw)" "y"; then
        echo ""
        if [ "$HAS_GUM" = "true" ]; then
            if gum spin --spinner dot --title "Installing lossless-claw..." -- openclaw plugins install @martian-engineering/lossless-claw 2>/dev/null; then
                log_success "lossless-claw installed"
            else
                log_error "lossless-claw installation failed"
                return 1
            fi
        else
            log_info "Installing lossless-claw (this may take a moment)..."
            if openclaw plugins install @martian-engineering/lossless-claw 2>&1 | tail -5; then
                log_success "lossless-claw installed"
            else
                log_error "lossless-claw installation failed"
                return 1
            fi
        fi

        # Verify extension directory exists
        if [ -d "$OPENCLAW_HOME/extensions/lossless-claw" ]; then
            log_success "Verified: lossless-claw extension present"
        else
            log_error "lossless-claw directory not found after install"
            return 1
        fi

        # Verify lcm.db exists (may be created on first run, so just check)
        if [ -f "$OPENCLAW_HOME/lcm.db" ]; then
            log_success "Verified: lcm.db exists"
        else
            log_info "lcm.db not yet created — will be initialized on first use"
        fi

        return 0
    else
        log_info "Skipped lossless-claw installation"
        return 1
    fi
}
```

- [ ] **4b.** Update the context engine auto-resolution block (around line 381). Replace the existing block:

```bash
    # Resolve context engine "auto"
    if [ "$WIZARD_CONTEXT_ENGINE" = "auto" ]; then
        if [ -f "$OPENCLAW_HOME/lcm.db" ]; then
            WIZARD_CONTEXT_ENGINE_RESOLVED="lossless-claw"
        else
            WIZARD_CONTEXT_ENGINE_RESOLVED="file-based"
        fi
    else
        WIZARD_CONTEXT_ENGINE_RESOLVED="$WIZARD_CONTEXT_ENGINE"
    fi
```

With the following expanded block that handles detection and install:

```bash
    # Resolve context engine — detect and offer install if needed
    if [ "$WIZARD_CONTEXT_ENGINE" = "lossless-claw" ]; then
        echo -e "${BOLD}Dependency: lossless-claw${NC}"
        echo ""
        if check_and_install_lossless_claw; then
            WIZARD_CONTEXT_ENGINE_RESOLVED="lossless-claw"
        else
            echo ""
            log_warning "lossless-claw not available — falling back to file-based context engine"
            log_info "Install later: openclaw plugins install @martian-engineering/lossless-claw"
            WIZARD_CONTEXT_ENGINE_RESOLVED="file-based"
        fi
        echo ""
    elif [ "$WIZARD_CONTEXT_ENGINE" = "auto" ]; then
        if [ -d "$OPENCLAW_HOME/extensions/lossless-claw" ] && [ -f "$OPENCLAW_HOME/lcm.db" ]; then
            WIZARD_CONTEXT_ENGINE_RESOLVED="lossless-claw"
        elif [ -d "$OPENCLAW_HOME/extensions/lossless-claw" ]; then
            WIZARD_CONTEXT_ENGINE_RESOLVED="lossless-claw"
            log_info "lossless-claw extension found (lcm.db will be created on first use)"
        else
            WIZARD_CONTEXT_ENGINE_RESOLVED="file-based"
        fi
    else
        WIZARD_CONTEXT_ENGINE_RESOLVED="$WIZARD_CONTEXT_ENGINE"
    fi
```

**Test:**

```bash
grep -n "check_and_install_lossless_claw" /Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh
# Expected: function definition + call site (at least 2 matches)

grep -n "lossless-claw" /Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh
# Expected: multiple matches (context engine options, function, resolution logic)
```

**Commit:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && git add INSTALL.sh && git commit -m "feat: add lossless-claw detection and install for LCM context engine

When user selects lossless-claw engine, checks for the extension and offers
openclaw plugins install. Verifies lcm.db after install. Falls back to
file-based on failure.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Update env config and gateway config with mode

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh`

**What:** Add `LACP_MODE`, `LACP_CURATOR_URL`, `LACP_CURATOR_TOKEN`, and `LACP_MUTATIONS_ENABLED` to the generated env config. Update the gateway config entry to include the mode field.

- [ ] **5a.** In `generate_env_config()` (around line 667), add mode-related env vars to the generated `.openclaw-lacp.env` file. After the `# Feature Flags` section in the heredoc, add:

```bash
# Operating Mode
LACP_MODE=$WIZARD_MODE
LACP_MUTATIONS_ENABLED=$([ "$WIZARD_MODE" = "connected" ] && echo "false" || echo "true")
```

And conditionally add curator connection vars:

```bash
$(if [ "$WIZARD_MODE" = "connected" ] && [ -n "$WIZARD_CURATOR_URL" ]; then
    echo "LACP_CURATOR_URL=$WIZARD_CURATOR_URL"
    echo "LACP_CURATOR_TOKEN=$WIZARD_CURATOR_TOKEN"
fi)
```

The full addition to the heredoc (insert after the `CODE_GRAPH_ENABLED` line and before the `# Hooks` line):

```bash
# Operating Mode
LACP_MODE=$WIZARD_MODE
LACP_MUTATIONS_ENABLED=$([ "$WIZARD_MODE" = "connected" ] && echo "false" || echo "true")
$([ "$WIZARD_MODE" != "standalone" ] && [ -n "$WIZARD_CURATOR_URL" ] && echo "LACP_CURATOR_URL=$WIZARD_CURATOR_URL")
$([ "$WIZARD_MODE" = "connected" ] && [ -n "$WIZARD_CURATOR_TOKEN" ] && echo "LACP_CURATOR_TOKEN=$WIZARD_CURATOR_TOKEN")
```

- [ ] **5b.** In `update_gateway_config()`, update the jq command that creates the plugin entry (around line 802). Add the mode field to the config object. Update the jq call to include mode and mutations:

Replace the jq block with:

```bash
    # Compute mutations flag
    local mutations_enabled="true"
    if [ "$WIZARD_MODE" = "connected" ]; then
        mutations_enabled="false"
    fi

    # Add plugin entry with wizard values
    tmp=$(mktemp)
    jq --arg vault "$DETECTED_VAULT" \
       --arg kr "$OPENCLAW_HOME/data/knowledge" \
       --arg profile "$WIZARD_PROFILE" \
       --arg tier "$WIZARD_POLICY_TIER" \
       --argjson cg "$WIZARD_CODE_GRAPH" \
       --argjson prov "$WIZARD_PROVENANCE" \
       --argjson lf "$WIZARD_LOCAL_FIRST" \
       --argjson ce "$ce_json" \
       --arg mode "$WIZARD_MODE" \
       --argjson mutations "$mutations_enabled" \
       --arg curatorUrl "$WIZARD_CURATOR_URL" '
      .plugins.entries["openclaw-lacp-fusion"] = {
        "enabled": true,
        "config": {
          "profile": $profile,
          "obsidianVault": $vault,
          "knowledgeRoot": $kr,
          "localFirst": $lf,
          "provenanceEnabled": $prov,
          "codeGraphEnabled": $cg,
          "policyTier": $tier,
          "contextEngine": $ce,
          "mode": $mode,
          "mutationsEnabled": $mutations,
          "curatorUrl": (if $curatorUrl == "" then null else $curatorUrl end)
        }
      }
    ' "$GATEWAY_CONFIG" > "$tmp" && mv "$tmp" "$GATEWAY_CONFIG"
    log_success "Plugin entry added to gateway config"
```

**Test:**

```bash
grep -n "LACP_MODE" /Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh
# Expected: matches in env config generation and gateway config

grep -n "LACP_MUTATIONS_ENABLED" /Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh
# Expected: at least 1 match in env config generation

grep -n "mutationsEnabled" /Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh
# Expected: 1 match in the gateway config jq block
```

**Commit:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && git add INSTALL.sh && git commit -m "feat: write mode, curator URL, and mutations flag to env and gateway config

Env config now includes LACP_MODE, LACP_MUTATIONS_ENABLED, and optionally
LACP_CURATOR_URL/TOKEN. Gateway config entry includes mode, mutationsEnabled,
and curatorUrl fields.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Add mode-specific validation in post-install health check

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh`

**What:** In `run_validation()`, add mode-specific checks. For Connected: verify ob is installed, optionally check curator URL reachability. For Curator: verify ob is installed, verify git is configured.

- [ ] **6a.** At the end of `run_validation()`, before the final pass/fail summary (the `echo ""` around line 974), add mode-specific validation:

```bash
    # Mode-specific validation
    if [ "$WIZARD_MODE" = "connected" ] || [ "$WIZARD_MODE" = "curator" ]; then
        echo ""
        log_info "Mode-specific checks ($WIZARD_MODE):"

        # ob must be available
        if command -v ob &>/dev/null; then
            ((pass++))
            log_success "obsidian-headless (ob) is installed"
        else
            ((fail++))
            log_error "obsidian-headless (ob) not found — $WIZARD_MODE mode requires it"
        fi
    fi

    if [ "$WIZARD_MODE" = "connected" ]; then
        # Optional: check curator URL reachability
        if [ -n "$WIZARD_CURATOR_URL" ]; then
            if curl -sf --max-time 5 "${WIZARD_CURATOR_URL}/health" &>/dev/null; then
                ((pass++))
                log_success "Curator reachable at $WIZARD_CURATOR_URL"
            else
                log_warning "Curator not reachable at $WIZARD_CURATOR_URL/health (may not be running yet)"
                # Not a hard failure — curator might start later
            fi
        fi
    fi

    if [ "$WIZARD_MODE" = "curator" ]; then
        # Git must be configured for backup
        if git config user.name &>/dev/null && git config user.email &>/dev/null; then
            ((pass++))
            log_success "Git user configured (required for curator backup)"
        else
            ((fail++))
            log_warning "Git user.name or user.email not configured — needed for curator git backup"
            log_info "  Fix: git config --global user.name 'Your Name' && git config --global user.email 'you@example.com'"
        fi
    fi
```

**Test:**

```bash
grep -n "Mode-specific checks" /Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh
# Expected: 1 match in run_validation()

grep -n "curator.*reachable\|Git user configured" /Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh
# Expected: 2 matches (one for connected check, one for curator check)
```

**Commit:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && git add INSTALL.sh && git commit -m "feat: add mode-specific validation checks in post-install health check

Connected mode verifies ob is installed and optionally checks curator URL
reachability. Curator mode verifies ob and git user configuration for
backup support.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Update summary and TOTAL_STEPS, then test end-to-end

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh`

**What:** Update the `print_summary()` function to display mode information and mode-specific next steps. Verify TOTAL_STEPS is still correct (it should remain 8 since no new steps were added to the main flow, only wizard prompts changed).

- [ ] **7a.** In `print_summary()`, add the mode to the Configuration section. After the `Profile` line (around line 996), add:

```bash
  ${GREEN}✓${NC} Mode:         $WIZARD_MODE
```

- [ ] **7b.** Add mode-specific next steps. Replace the static `Next steps` block with a conditional one:

```bash
${BOLD}Next steps:${NC}
  1. Restart OpenClaw:     openclaw gateway restart
  2. Init project memory:  openclaw-memory-init ~/my-project agent-name webchat
  3. Validate setup:       openclaw-lacp-validate
  4. Test context query:   openclaw-brain-graph query "test"
$(if [ "$WIZARD_MODE" = "connected" ]; then
echo "
  ${BOLD}Connected mode:${NC}
  5. Complete vault join:  openclaw-lacp-connect join --token <token>
  6. Start sync daemon:    ob sync --continuous
  7. Verify sync:          openclaw-lacp-connect status"
fi)
$(if [ "$WIZARD_MODE" = "curator" ]; then
echo "
  ${BOLD}Curator mode:${NC}
  5. Configure connectors: edit $PLUGIN_PATH/config/connectors.json
  6. Set up git backup:    cd \$LACP_OBSIDIAN_VAULT && git init && git remote add origin <url>
  7. Generate invites:     openclaw-lacp-connect invite --email user@company.com
  8. Start curator daemon: openclaw-lacp-curator start"
fi)
```

- [ ] **7c.** Run the full installer in a dry-run to verify syntax. The installer uses `set -euo pipefail`, so any syntax errors will be caught:

**Test:**

```bash
# Syntax check — bash will parse without executing
bash -n /Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh
# Expected: no output (clean parse)

# Verify all new functions exist
grep -c "^check_and_install_" /Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh
# Expected: 3 (obsidian_headless, gitnexus, lossless_claw)

# Verify mode variable is used in config generation
grep -c "WIZARD_MODE" /Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh
# Expected: 10+ matches across declaration, prompt, config gen, validation, summary

# Verify all three modes appear in the choice prompt
grep "standalone.*connected.*curator" /Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh
# Expected: no match (they are on separate lines), but each should appear:
grep -c "standalone\|connected\|curator" /Users/andrew/clawd/openclaw-lacp-fusion-repo/INSTALL.sh
# Expected: 20+ matches
```

**Commit:**

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo && git add INSTALL.sh && git commit -m "feat: update summary with mode display and mode-specific next steps

Shows operating mode in post-install summary. Connected mode shows join
and sync steps. Curator mode shows connector config, git backup, and
invite generation steps.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Summary of all changes to INSTALL.sh

| Section | Change |
|---|---|
| **Dependency installers** (new section, ~line 207) | Three new functions: `check_and_install_obsidian_headless()`, `check_and_install_gitnexus()`, `check_and_install_lossless_claw()` |
| **run_wizard()** — mode selection | New section 4 (Operating Mode) with `prompt_choice` for standalone/connected/curator. Connected collects curator URL + token. |
| **run_wizard()** — ob dependency gate | After mode selection, blocks connected/curator if ob is missing (with install offer and fallback) |
| **run_wizard()** — advanced: code graph | Replaced one-liner with GitNexus detection and install flow |
| **run_wizard()** — context engine resolution | Expanded auto-detection to include lossless-claw install offer |
| **run_wizard()** — summary | Added mode + curator URL to confirmation display |
| **generate_env_config()** | Added `LACP_MODE`, `LACP_MUTATIONS_ENABLED`, `LACP_CURATOR_URL`, `LACP_CURATOR_TOKEN` |
| **update_gateway_config()** | Added `mode`, `mutationsEnabled`, `curatorUrl` to plugin entry |
| **run_validation()** | Added mode-specific checks (ob, curator reachability, git config) |
| **print_summary()** | Added mode to config display + mode-specific next steps |

## Error handling matrix

| Dependency | Install fails | User declines | Result |
|---|---|---|---|
| obsidian-headless | Fall back to standalone mode | Fall back to standalone mode | `WIZARD_MODE=standalone` |
| GitNexus | Disable code graph | Skip code graph | `WIZARD_CODE_GRAPH=false` |
| lossless-claw | Fall back to file-based | Fall back to file-based | `WIZARD_CONTEXT_ENGINE_RESOLVED=file-based` |
