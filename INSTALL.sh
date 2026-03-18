#!/bin/bash
set -euo pipefail

# OpenClaw LACP Fusion Plugin Installer
# Version: 2.0.0
# Installs to ~/.openclaw/extensions/openclaw-lacp-fusion/
# Registers in ~/.openclaw/openclaw.json gateway config

PLUGIN_NAME="openclaw-lacp-fusion"
PLUGIN_VERSION="2.1.0"
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
PLUGIN_PATH="$OPENCLAW_HOME/extensions/$PLUGIN_NAME"
GATEWAY_CONFIG="$OPENCLAW_HOME/openclaw.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}i${NC}  $1"; }
log_success() { echo -e "${GREEN}✓${NC}  $1"; }
log_warning() { echo -e "${YELLOW}!${NC}  $1"; }
log_error()   { echo -e "${RED}✗${NC}  $1"; }
log_step()    { echo -e "\n${BOLD}[$1/$TOTAL_STEPS] $2${NC}"; }

TOTAL_STEPS=8

# ─── Detect environment ──────────────────────────────────────────────────────

detect_environment() {
    local os
    os="$(uname -s)"
    case "$os" in
        Darwin) DETECTED_OS="macos" ;;
        Linux)
            if grep -qi microsoft /proc/version 2>/dev/null; then
                DETECTED_OS="wsl"
            else
                DETECTED_OS="linux"
            fi
            ;;
        *) DETECTED_OS="unknown" ;;
    esac

    # Detect default Obsidian vault path
    if [ -d "$HOME/obsidian/vault" ]; then
        DETECTED_VAULT="$HOME/obsidian/vault"
    elif [ -d "/Volumes/Cortex" ]; then
        DETECTED_VAULT="/Volumes/Cortex"
    elif [ -d "$HOME/Documents/Obsidian" ]; then
        DETECTED_VAULT="$HOME/Documents/Obsidian"
    else
        DETECTED_VAULT="$HOME/obsidian/vault"
    fi

    log_info "Detected OS: $DETECTED_OS"
    log_info "Detected vault: $DETECTED_VAULT"
}

# ─── Step 1: Prerequisites ───────────────────────────────────────────────────

check_prerequisites() {
    log_step 1 "Checking prerequisites"
    local fail=0

    # OpenClaw home
    if [ ! -d "$OPENCLAW_HOME" ]; then
        log_error "OpenClaw not found at $OPENCLAW_HOME"
        echo "  Set OPENCLAW_HOME=/path/to/.openclaw and try again"
        exit 1
    fi
    log_success "OpenClaw found at $OPENCLAW_HOME"

    # Gateway config
    if [ ! -f "$GATEWAY_CONFIG" ]; then
        log_error "Gateway config not found at $GATEWAY_CONFIG"
        echo "  Run 'openclaw configure' first to generate the config"
        exit 1
    fi
    log_success "Gateway config found"

    # Bash version
    if [ "${BASH_VERSINFO[0]}" -lt 5 ]; then
        log_error "Bash 5.0+ required (you have ${BASH_VERSION})"
        fail=1
    else
        log_success "Bash ${BASH_VERSION}"
    fi

    # Python 3.9+
    if ! command -v python3 &>/dev/null; then
        log_error "Python 3.9+ required"
        fail=1
    else
        local py_version
        py_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        log_success "Python $py_version"
    fi

    # git
    if ! command -v git &>/dev/null; then
        log_error "git required"
        fail=1
    else
        log_success "git found"
    fi

    # jq (needed for gateway config editing)
    if ! command -v jq &>/dev/null; then
        log_warning "jq not found — gateway config will not be auto-updated"
        log_info "  Install jq: brew install jq (macOS) or apt install jq (Linux)"
        HAS_JQ=false
    else
        log_success "jq found"
        HAS_JQ=true
    fi

    if [ "$fail" -ne 0 ]; then
        log_error "Prerequisites check failed"
        exit 1
    fi
}

# ─── Step 2: Create plugin directory ─────────────────────────────────────────

setup_plugin_directory() {
    log_step 2 "Installing plugin to $PLUGIN_PATH"

    mkdir -p "$PLUGIN_PATH"

    # Copy manifest
    cp "$SCRIPT_DIR/openclaw.plugin.json" "$PLUGIN_PATH/"
    cp "$SCRIPT_DIR/plugin.json" "$PLUGIN_PATH/"

    # Copy plugin source tree
    if [ -d "$SCRIPT_DIR/plugin" ]; then
        # Hooks
        if [ -d "$SCRIPT_DIR/plugin/hooks" ]; then
            mkdir -p "$PLUGIN_PATH/hooks"
            cp -r "$SCRIPT_DIR/plugin/hooks/handlers" "$PLUGIN_PATH/hooks/"
            cp -r "$SCRIPT_DIR/plugin/hooks/profiles" "$PLUGIN_PATH/hooks/"
            cp -r "$SCRIPT_DIR/plugin/hooks/rules" "$PLUGIN_PATH/hooks/"
            cp "$SCRIPT_DIR/plugin/hooks/plugin.json" "$PLUGIN_PATH/hooks/"
            [ -d "$SCRIPT_DIR/plugin/hooks/tests" ] && cp -r "$SCRIPT_DIR/plugin/hooks/tests" "$PLUGIN_PATH/hooks/"
            log_success "Hooks installed (4 handlers, 3 profiles)"
        fi

        # Policy
        if [ -d "$SCRIPT_DIR/plugin/policy" ]; then
            mkdir -p "$PLUGIN_PATH/policy"
            cp -r "$SCRIPT_DIR/plugin/policy"/* "$PLUGIN_PATH/policy/"
            log_success "Policy engine installed"
        fi

        # Bin scripts
        if [ -d "$SCRIPT_DIR/plugin/bin" ]; then
            mkdir -p "$PLUGIN_PATH/bin"
            cp "$SCRIPT_DIR/plugin/bin"/openclaw-* "$PLUGIN_PATH/bin/" 2>/dev/null || true
            chmod +x "$PLUGIN_PATH/bin"/* 2>/dev/null || true
            local bin_count
            bin_count=$(ls -1 "$PLUGIN_PATH/bin"/ 2>/dev/null | wc -l | tr -d ' ')
            log_success "Bin scripts installed ($bin_count executables)"
        fi

        # Config
        if [ -d "$SCRIPT_DIR/plugin/config" ]; then
            mkdir -p "$PLUGIN_PATH/config"
            cp -r "$SCRIPT_DIR/plugin/config"/* "$PLUGIN_PATH/config/" 2>/dev/null || true
            log_success "Config files installed"
        fi

        # V2 LCM
        if [ -d "$SCRIPT_DIR/plugin/v2-lcm" ]; then
            mkdir -p "$PLUGIN_PATH/v2-lcm"
            cp -r "$SCRIPT_DIR/plugin/v2-lcm"/* "$PLUGIN_PATH/v2-lcm/"
            log_success "V2 lifecycle manager installed"
        fi
    fi

    # Copy docs
    if [ -d "$SCRIPT_DIR/docs" ]; then
        mkdir -p "$PLUGIN_PATH/docs"
        cp -r "$SCRIPT_DIR/docs"/* "$PLUGIN_PATH/docs/"
        log_success "Documentation installed"
    fi

    log_success "Plugin files installed"
}

# ─── Step 3: Create required directories ─────────────────────────────────────

create_data_directories() {
    log_step 3 "Creating data directories"

    local dirs=(
        "$OPENCLAW_HOME/data/knowledge"
        "$OPENCLAW_HOME/data/automation"
        "$OPENCLAW_HOME/data/approval-cache"
        "$OPENCLAW_HOME/data/project-sessions"
        "$OPENCLAW_HOME/provenance"
        "$OPENCLAW_HOME/agent-ids"
        "$PLUGIN_PATH/logs"
    )

    for dir in "${dirs[@]}"; do
        mkdir -p "$dir"
    done

    log_success "Knowledge directory: $OPENCLAW_HOME/data/knowledge/"
    log_success "Automation directory: $OPENCLAW_HOME/data/automation/"
    log_success "Provenance directory: $OPENCLAW_HOME/provenance/"
    log_success "Agent IDs directory: $OPENCLAW_HOME/agent-ids/"
}

# ─── Step 4: Generate env config ─────────────────────────────────────────────

generate_env_config() {
    log_step 4 "Generating environment config"

    local env_file="$PLUGIN_PATH/config/.openclaw-lacp.env"

    if [ -f "$env_file" ]; then
        log_warning "Config already exists at $env_file (preserving)"
        return
    fi

    cat > "$env_file" << ENVEOF
# ============================================================================
# OpenClaw LACP Fusion — Environment Configuration
# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# OS: $DETECTED_OS
# ============================================================================

# Layer 2: Knowledge Graph
LACP_OBSIDIAN_VAULT=$DETECTED_VAULT
LACP_KNOWLEDGE_ROOT=$OPENCLAW_HOME/data/knowledge
LACP_AUTOMATION_ROOT=$OPENCLAW_HOME/data/automation

# Layer 5: Provenance
PROVENANCE_ROOT=$OPENCLAW_HOME/provenance
AGENT_ID_STORE=$OPENCLAW_HOME/agent-ids

# Feature Flags
LACP_LOCAL_FIRST=true
LACP_WITH_GITNEXUS=false

# Hooks
OPENCLAW_HOOKS_PROFILE=balanced

# To customize further, see the full template at:
# $PLUGIN_PATH/config/.openclaw-lacp.env.template
ENVEOF

    log_success "Config generated at $env_file"
}

# ─── Step 5: Update gateway config ──────────────────────────────────────────

update_gateway_config() {
    log_step 5 "Updating gateway config"

    if [ "$HAS_JQ" != "true" ]; then
        log_warning "Skipping gateway config update (jq not installed)"
        log_info "  Add manually to $GATEWAY_CONFIG:"
        echo '  "plugins.allow": add "openclaw-lacp-fusion"'
        echo '  "plugins.entries.openclaw-lacp-fusion": { "enabled": true, "config": { ... } }'
        return
    fi

    # Backup gateway config
    cp "$GATEWAY_CONFIG" "$GATEWAY_CONFIG.bak.$(date +%s)"
    log_info "Gateway config backed up"

    # Check if plugin already registered
    if jq -e '.plugins.entries["openclaw-lacp-fusion"]' "$GATEWAY_CONFIG" &>/dev/null; then
        log_warning "Plugin already registered in gateway config"
        return
    fi

    # Add to plugins.allow if not present
    local tmp
    tmp=$(mktemp)

    jq --arg name "$PLUGIN_NAME" '
      .plugins.allow = (
        if (.plugins.allow | index($name)) then .plugins.allow
        else .plugins.allow + [$name]
        end
      )
    ' "$GATEWAY_CONFIG" > "$tmp" && mv "$tmp" "$GATEWAY_CONFIG"
    log_success "Added to plugins.allow"

    # Add plugin entry
    tmp=$(mktemp)
    jq --arg vault "$DETECTED_VAULT" --arg kr "$OPENCLAW_HOME/data/knowledge" '
      .plugins.entries["openclaw-lacp-fusion"] = {
        "enabled": true,
        "config": {
          "profile": "balanced",
          "obsidianVault": $vault,
          "knowledgeRoot": $kr,
          "localFirst": true,
          "provenanceEnabled": true,
          "codeGraphEnabled": false,
          "policyTier": "review"
        }
      }
    ' "$GATEWAY_CONFIG" > "$tmp" && mv "$tmp" "$GATEWAY_CONFIG"
    log_success "Plugin entry added to gateway config"

    # Add install record
    tmp=$(mktemp)
    jq --arg ver "$PLUGIN_VERSION" --arg path "$PLUGIN_PATH" --arg now "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" '
      .plugins.installs["openclaw-lacp-fusion"] = {
        "source": "local",
        "spec": "openclaw-lacp-fusion",
        "installPath": $path,
        "version": $ver,
        "resolvedVersion": $ver,
        "installedAt": $now
      }
    ' "$GATEWAY_CONFIG" > "$tmp" && mv "$tmp" "$GATEWAY_CONFIG"
    log_success "Install record added to gateway config"
}

# ─── Step 6: Initialize Obsidian vault ───────────────────────────────────────

init_obsidian_vault() {
    log_step 6 "Checking Obsidian vault"

    if [ -d "$DETECTED_VAULT" ]; then
        log_success "Obsidian vault exists at $DETECTED_VAULT"
    else
        log_info "Creating Obsidian vault directory at $DETECTED_VAULT"
        mkdir -p "$DETECTED_VAULT"
        log_success "Obsidian vault directory created"
    fi
}

# ─── Step 7: Run validation ─────────────────────────────────────────────────

run_validation() {
    log_step 7 "Validating installation"

    local pass=0
    local fail=0

    # Check plugin manifest
    if [ -f "$PLUGIN_PATH/openclaw.plugin.json" ]; then
        ((pass++))
    else
        log_error "Missing openclaw.plugin.json"
        ((fail++))
    fi

    # Check hooks handlers
    for handler in session-start pretool-guard stop-quality-gate write-validate; do
        if [ -f "$PLUGIN_PATH/hooks/handlers/${handler}.py" ]; then
            ((pass++))
        else
            log_warning "Missing hook handler: ${handler}.py"
            ((fail++))
        fi
    done

    # Check bin scripts exist
    local bin_count
    bin_count=$(ls -1 "$PLUGIN_PATH/bin"/openclaw-* 2>/dev/null | wc -l | tr -d ' ')
    if [ "$bin_count" -gt 0 ]; then
        ((pass++))
        log_success "$bin_count bin scripts installed"
    else
        log_warning "No bin scripts found"
        ((fail++))
    fi

    # Check gateway registration
    if [ "$HAS_JQ" = "true" ]; then
        if jq -e '.plugins.entries["openclaw-lacp-fusion"].enabled' "$GATEWAY_CONFIG" &>/dev/null; then
            ((pass++))
            log_success "Plugin registered in gateway config"
        else
            log_warning "Plugin not registered in gateway config"
            ((fail++))
        fi
    fi

    # Check data directories
    for dir in "$OPENCLAW_HOME/data/knowledge" "$OPENCLAW_HOME/provenance"; do
        if [ -d "$dir" ]; then
            ((pass++))
        else
            ((fail++))
        fi
    done

    echo ""
    if [ "$fail" -eq 0 ]; then
        log_success "Validation passed ($pass checks)"
    else
        log_warning "Validation: $pass passed, $fail warnings"
    fi
}

# ─── Step 8: Summary ────────────────────────────────────────────────────────

print_summary() {
    log_step 8 "Installation summary"

    cat << EOF

${GREEN}✓ openclaw-lacp-fusion v${PLUGIN_VERSION} installed${NC}

${BOLD}What was configured:${NC}
  ${GREEN}✓${NC} Plugin installed to $PLUGIN_PATH
  ${GREEN}✓${NC} Gateway config updated ($GATEWAY_CONFIG)
  ${GREEN}✓${NC} Knowledge directories created
  ${GREEN}✓${NC} Obsidian vault at $DETECTED_VAULT
  ${GREEN}✓${NC} Safety profile: balanced

${BOLD}Next steps:${NC}
  1. Restart OpenClaw:     openclaw gateway restart
  2. Init project memory:  $PLUGIN_PATH/bin/openclaw-memory-init ~/my-project agent-name webchat
  3. Validate setup:       $PLUGIN_PATH/bin/openclaw-lacp-validate
  4. Test context query:   $PLUGIN_PATH/bin/openclaw-brain-graph query "test"

${BOLD}Locations:${NC}
  Config:  $PLUGIN_PATH/config/.openclaw-lacp.env
  Gateway: $GATEWAY_CONFIG
  Logs:    $PLUGIN_PATH/logs/
  Docs:    $PLUGIN_PATH/docs/

${BOLD}Profiles:${NC}
  minimal-stop   — quality gate only (lightweight)
  balanced       — session context + quality gate (default)
  hardened-exec  — all 4 hooks enabled (maximum safety)

  Change profile:
    jq '.plugins.entries["openclaw-lacp-fusion"].config.profile = "hardened-exec"' \\
      $GATEWAY_CONFIG > /tmp/oc.json && mv /tmp/oc.json $GATEWAY_CONFIG

${BOLD}Lossless-Claw Integration (optional):${NC}
  To use the native LCM context engine instead of file-based:
  1. Ensure ~/.openclaw/lcm.db exists (created by lossless-claw)
  2. Add to your openclaw.json plugin config:
     "contextEngine": "lossless-claw"
  3. Test: openclaw-lacp-context inject --project my-project --backend lcm
  4. See docs/LOSSLESS-CLAW-INTEGRATION.md for full guide

EOF
}

# ─── Main ────────────────────────────────────────────────────────────────────

main() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║  OpenClaw LACP Fusion Installer v${PLUGIN_VERSION}                          ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    echo ""

    detect_environment
    check_prerequisites
    setup_plugin_directory
    create_data_directories
    generate_env_config
    update_gateway_config
    init_obsidian_vault
    run_validation
    print_summary

    log_success "Installation complete!"
    exit 0
}

main "$@"
