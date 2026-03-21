#!/bin/bash
set -euo pipefail

# OpenClaw LACP Fusion Plugin Installer
# Version: 2.2.0
# Interactive CLI wizard for configuring and installing the plugin
# Installs to ~/.openclaw/extensions/openclaw-lacp-fusion/

# Require Bash 4.0+ (for associative arrays)
if [ "${BASH_VERSINFO[0]}" -lt 4 ]; then
    echo "Error: Bash 4.0+ required (you have ${BASH_VERSION})."
    echo "  macOS: Install via Homebrew: brew install bash"
    echo "  Then run: /opt/homebrew/bin/bash INSTALL.sh"
    exit 1
fi

# Cleanup trap — print recovery info on failure
_install_cleanup() {
    local exit_code=$?
    if [ "$exit_code" -ne 0 ]; then
        echo ""
        echo -e "\033[0;31mInstallation failed (exit code $exit_code).\033[0m"
        echo ""
        echo "To recover:"
        echo "  1. Re-run INSTALL.sh (it's safe to run again)"
        echo "  2. If gateway config is broken: restore from backup:"
        echo "     cp ~/.openclaw/openclaw.json.bak.* ~/.openclaw/openclaw.json"
        echo "  3. To remove partial install:"
        echo "     rm -rf ~/.openclaw/extensions/openclaw-lacp-fusion"
        echo ""
    fi
}
trap _install_cleanup EXIT

PLUGIN_NAME="openclaw-lacp-fusion"
PLUGIN_VERSION="2.2.0"
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
PLUGIN_PATH="$OPENCLAW_HOME/extensions/$PLUGIN_NAME"
GATEWAY_CONFIG="$OPENCLAW_HOME/openclaw.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
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

    # Scan for Obsidian vaults (directories containing .obsidian/)
    DETECTED_VAULTS=()
    local search_roots=()

    case "$DETECTED_OS" in
        macos)
            search_roots=("$HOME/Documents" "$HOME/Library/Mobile Documents" "$HOME/Desktop" "$HOME")
            # Also check mounted volumes (external drives, NAS, etc.)
            for vol in /Volumes/*/; do
                [ -d "$vol" ] && search_roots+=("${vol%/}")
            done
            ;;
        *)
            search_roots=("$HOME/Documents" "$HOME/Desktop" "$HOME")
            ;;
    esac

    for root in "${search_roots[@]}"; do
        if [ -d "$root" ]; then
            while IFS= read -r vault_dir; do
                # vault_dir is the .obsidian folder; parent is the vault
                local vault="${vault_dir%/.obsidian}"
                DETECTED_VAULTS+=("$vault")
            done < <(find "$root" -maxdepth 4 -name ".obsidian" -type d 2>/dev/null)
        fi
    done

    # Deduplicate (in case overlapping search roots)
    if [ "${#DETECTED_VAULTS[@]}" -gt 0 ]; then
        local -A seen=()
        local unique_vaults=()
        for v in "${DETECTED_VAULTS[@]}"; do
            if [ -z "${seen[$v]+x}" ]; then
                seen[$v]=1
                unique_vaults+=("$v")
            fi
        done
        DETECTED_VAULTS=("${unique_vaults[@]}")
    fi
}

# ─── Interactive wizard ──────────────────────────────────────────────────────

# Detect gum for interactive prompts (falls back to read-based prompts)
HAS_GUM=false
if command -v gum &>/dev/null; then
    HAS_GUM=true
fi

prompt_value() {
    local prompt="$1"
    local default="$2"

    if [ "$HAS_GUM" = "true" ]; then
        echo -e "  ${CYAN}?${NC} ${prompt}"
        gum input --placeholder "$default" --value "$default" --width 60
    else
        local result
        echo -en "  ${CYAN}?${NC} ${prompt} ${DIM}[${default}]${NC}: "
        read -r result
        echo "${result:-$default}"
    fi
}

prompt_choice() {
    local prompt="$1"
    shift
    local options=("$@")
    local default="${options[0]}"

    if [ "$HAS_GUM" = "true" ]; then
        echo -e "  ${CYAN}?${NC} ${prompt}"
        gum choose --cursor="> " --cursor.foreground="212" "${options[@]}"
    else
        echo -e "  ${CYAN}?${NC} ${prompt}"
        for i in "${!options[@]}"; do
            local num=$((i + 1))
            if [ "$i" -eq 0 ]; then
                echo -e "    ${GREEN}${num})${NC} ${BOLD}${options[$i]}${NC} ${DIM}(default)${NC}"
            else
                echo -e "    ${num}) ${options[$i]}"
            fi
        done
        echo -en "    Choice [1-${#options[@]}]: "
        read -r choice
        if [ -z "$choice" ] || [ "$choice" -lt 1 ] 2>/dev/null || [ "$choice" -gt "${#options[@]}" ] 2>/dev/null; then
            echo "$default"
        else
            echo "${options[$((choice - 1))]}"
        fi
    fi
}

prompt_yes_no() {
    local prompt="$1"
    local default="${2:-y}"

    if [ "$HAS_GUM" = "true" ]; then
        if [ "$default" = "y" ]; then
            gum confirm "$prompt" --default=yes
        else
            gum confirm "$prompt" --default=no
        fi
    else
        if [ "$default" = "y" ]; then
            echo -en "  ${CYAN}?${NC} ${prompt} ${DIM}[Y/n]${NC}: "
        else
            echo -en "  ${CYAN}?${NC} ${prompt} ${DIM}[y/N]${NC}: "
        fi
        read -r answer
        answer="${answer:-$default}"
        case "$answer" in
            [yY]|[yY][eE][sS]) return 0 ;;
            *) return 1 ;;
        esac
    fi
}

prompt_browse_directory() {
    if [ "$HAS_GUM" = "true" ]; then
        echo -e "  ${DIM}Navigate with arrow keys, Enter to select${NC}"
        gum file --directory --height 12 "${1:-$HOME}"
    else
        local result
        echo -en "  ${CYAN}?${NC} Enter directory path: "
        read -r result
        echo "$result"
    fi
}

run_wizard() {
    echo ""
    echo -e "${BOLD}Configuration Wizard${NC}"
    echo -e "${DIM}Press Enter to accept defaults shown in brackets.${NC}"
    echo ""

    # 1. Obsidian vault path
    echo -e "${BOLD}Obsidian Vault${NC}"
    echo -e "  ${DIM}Your Obsidian vault stores knowledge graph data (Layer 2).${NC}"
    echo -e "  ${DIM}If you don't use Obsidian, a directory will be created for you.${NC}"
    echo ""

    if [ "${#DETECTED_VAULTS[@]}" -gt 0 ]; then
        echo -e "  ${GREEN}Found ${#DETECTED_VAULTS[@]} Obsidian vault(s):${NC}"
        echo ""

        local vault_choices=()
        for v in "${DETECTED_VAULTS[@]}"; do
            vault_choices+=("$v")
        done
        vault_choices+=("Browse for a different folder")
        vault_choices+=("Type a custom path")
        vault_choices+=("Skip — I don't use Obsidian")

        local vault_pick
        vault_pick=$(prompt_choice "Select your vault" "${vault_choices[@]}")

        case "$vault_pick" in
            "Browse for a different folder")
                WIZARD_VAULT=$(prompt_browse_directory "$HOME")
                ;;
            "Type a custom path")
                WIZARD_VAULT=$(prompt_value "Vault path" "$HOME/my-vault")
                ;;
            "Skip — I don't use Obsidian")
                WIZARD_VAULT="$OPENCLAW_HOME/data/knowledge"
                log_info "No vault selected — using default knowledge directory"
                ;;
            *)
                WIZARD_VAULT="$vault_pick"
                ;;
        esac
    else
        echo -e "  ${YELLOW}No Obsidian vaults detected.${NC}"
        echo ""
        local vault_pick
        vault_pick=$(prompt_choice "How would you like to set your vault?" \
            "Browse for folder" \
            "Type a custom path" \
            "Skip — I don't use Obsidian")

        case "$vault_pick" in
            "Browse for folder")
                WIZARD_VAULT=$(prompt_browse_directory "$HOME")
                ;;
            "Type a custom path")
                WIZARD_VAULT=$(prompt_value "Vault path" "$HOME/my-vault")
                ;;
            "Skip — I don't use Obsidian")
                WIZARD_VAULT="$OPENCLAW_HOME/data/knowledge"
                log_info "No vault selected — using default knowledge directory"
                ;;
        esac
    fi
    echo -e "  ${GREEN}✓${NC} Vault: $WIZARD_VAULT"
    echo ""

    # 2. Context engine
    echo -e "${BOLD}Context Engine${NC}"
    echo -e "  ${DIM}Controls how LACP stores and retrieves context facts.${NC}"
    echo ""
    local ce_choice
    ce_choice=$(prompt_choice "Context engine" \
        "auto          — auto-detect (lossless-claw if available, else file-based)" \
        "file-based    — JSON files on disk (no extra dependencies)" \
        "lossless-claw — native LCM database (~/.openclaw/lcm.db required)")
    WIZARD_CONTEXT_ENGINE="${ce_choice%%[[:space:]]*}"
    echo -e "  ${GREEN}✓${NC} Context engine: $WIZARD_CONTEXT_ENGINE"
    echo ""

    # 3. Safety profile
    echo -e "${BOLD}Safety Profile${NC}"
    echo -e "  ${DIM}Controls which execution hooks are active and how they behave.${NC}"
    echo ""
    local profile_choice
    profile_choice=$(prompt_choice "Profile" \
        "autonomous    — all hooks, warn-only (agents keep working, escalate when needed)" \
        "balanced      — session context + quality gate (recommended for interactive use)" \
        "context-only  — just git context injection, no safety gates" \
        "guard-rail    — safety gates only, no context injection" \
        "minimal-stop  — quality gate only (lightweight)" \
        "hardened-exec — all 4 hooks, blocks dangerous ops" \
        "full-audit    — all hooks, strict mode, verbose logging")
    WIZARD_PROFILE="${profile_choice%%[[:space:]]*}"
    echo -e "  ${GREEN}✓${NC} Safety profile: $WIZARD_PROFILE"
    echo ""

    # 4. Advanced config (optional)
    WIZARD_ADVANCED=false
    if prompt_yes_no "Configure advanced options?" "n"; then
        WIZARD_ADVANCED=true
        echo ""
        echo -e "${BOLD}Advanced Configuration${NC}"

        local tier_choice
        tier_choice=$(prompt_choice "Default policy tier" \
            "review   — require review before execution" \
            "safe     — auto-approve safe operations" \
            "critical — all operations require approval")
        WIZARD_POLICY_TIER="${tier_choice%%[[:space:]]*}"

        WIZARD_CODE_GRAPH=$(prompt_yes_no "Enable code intelligence (AST analysis)?" "n" && echo "true" || echo "false")
        WIZARD_PROVENANCE=$(prompt_yes_no "Enable provenance tracking?" "y" && echo "true" || echo "false")
        WIZARD_LOCAL_FIRST=$(prompt_yes_no "Local-first mode (no external sync)?" "y" && echo "true" || echo "false")

        # Guard configuration
        echo ""
        echo -e "${BOLD}Guard Configuration${NC}"
        echo -e "  ${DIM}Controls how the pretool guard handles dangerous commands.${NC}"
        echo ""

        local guard_level_choice
        guard_level_choice=$(prompt_choice "Default guard block level" \
            "block — block dangerous commands (ask user first)" \
            "warn  — warn but allow execution (log to guard-blocks.jsonl)" \
            "log   — silently log matches (no interruption)")
        WIZARD_GUARD_LEVEL="${guard_level_choice%%[[:space:]]*}"
        echo -e "  ${GREEN}✓${NC} Guard block level: $WIZARD_GUARD_LEVEL"
        echo ""

        if prompt_yes_no "Review and toggle individual guard rules?" "n"; then
            echo ""
            echo -e "  ${DIM}16 rules are enabled by default. Disable any you don't need:${NC}"
            echo ""

            # Key rules users might want to toggle
            local -a toggle_rules=(
                "npm-publish:Package registry publishing (npm/yarn/pnpm/cargo publish)"
                "git-reset-hard:git reset --hard (destructive)"
                "git-clean-force:git clean -f (destructive)"
                "chmod-777:chmod 777 (overly permissive)"
                "docker-privileged:docker run --privileged"
                "curl-pipe-interpreter:curl/wget piped to interpreter"
                "env-files:.env file access"
                "pem-key-files:PEM/key file access"
            )

            WIZARD_DISABLED_RULES=()
            for rule_entry in "${toggle_rules[@]}"; do
                local rule_id="${rule_entry%%:*}"
                local rule_desc="${rule_entry#*:}"
                if ! prompt_yes_no "Enable: ${rule_desc}?" "y"; then
                    WIZARD_DISABLED_RULES+=("$rule_id")
                    echo -e "    ${YELLOW}!${NC} ${rule_id} disabled"
                fi
            done

            if [ "${#WIZARD_DISABLED_RULES[@]}" -eq 0 ]; then
                echo -e "  ${GREEN}✓${NC} All rules enabled"
            else
                echo -e "  ${GREEN}✓${NC} ${#WIZARD_DISABLED_RULES[@]} rule(s) disabled"
            fi
        else
            WIZARD_DISABLED_RULES=()
        fi
    else
        WIZARD_POLICY_TIER="review"
        WIZARD_CODE_GRAPH="false"
        WIZARD_PROVENANCE="true"
        WIZARD_LOCAL_FIRST="true"
        WIZARD_GUARD_LEVEL="block"
        WIZARD_DISABLED_RULES=()
    fi

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

    # 5. Confirmation
    echo ""
    echo -e "${BOLD}Installation Summary${NC}"
    echo -e "  ┌─────────────────────────────────────────────────────────────┐"
    echo -e "  │  Plugin:          openclaw-lacp-fusion v${PLUGIN_VERSION}               │"
    echo -e "  │  Install path:    ${DIM}${PLUGIN_PATH}${NC}  │"
    echo -e "  │  Obsidian vault:  ${DIM}${WIZARD_VAULT}${NC}"
    echo -e "  │  Context engine:  ${WIZARD_CONTEXT_ENGINE_RESOLVED}"
    echo -e "  │  Safety profile:  ${WIZARD_PROFILE}"
    echo -e "  │  Policy tier:     ${WIZARD_POLICY_TIER}"
    echo -e "  │  Code graph:      ${WIZARD_CODE_GRAPH}"
    echo -e "  │  Provenance:      ${WIZARD_PROVENANCE}"
    echo -e "  │  Local-first:     ${WIZARD_LOCAL_FIRST}"
    echo -e "  └─────────────────────────────────────────────────────────────┘"
    echo ""

    if ! prompt_yes_no "Proceed with installation?" "y"; then
        echo ""
        log_info "Installation cancelled."
        exit 0
    fi

    # Export wizard values for use by installation steps
    DETECTED_VAULT="$WIZARD_VAULT"
}

# ─── Step 1: Prerequisites ───────────────────────────────────────────────────

check_prerequisites() {
    log_step 1 "Checking prerequisites"
    local fail=0

    # OpenClaw home
    if [ ! -d "$OPENCLAW_HOME" ]; then
        log_warning "OpenClaw directory not found at $OPENCLAW_HOME — will be created"
        mkdir -p "$OPENCLAW_HOME"
    fi
    log_success "OpenClaw home: $OPENCLAW_HOME"

    # Gateway config (create minimal if missing)
    if [ ! -f "$GATEWAY_CONFIG" ]; then
        log_warning "Gateway config not found — creating minimal config"
        echo '{"plugins":{"allow":[],"entries":{},"installs":{}}}' > "$GATEWAY_CONFIG"
    fi
    log_success "Gateway config: $GATEWAY_CONFIG"

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

    # Generate package.json (required by gateway for plugin resolution)
    cat > "$PLUGIN_PATH/package.json" << PKGJSON
{
  "name": "$PLUGIN_NAME",
  "version": "$PLUGIN_VERSION",
  "description": "LACP integration for OpenClaw — hooks, policy gates, gated execution, memory scaffolding, and evidence verification.",
  "license": "MIT",
  "type": "module",
  "main": "index.ts",
  "openclaw": {
    "extensions": [
      "./index.ts"
    ]
  }
}
PKGJSON
    log_success "package.json generated"

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
            local profile_count
            profile_count=$(ls -1 "$PLUGIN_PATH/hooks/profiles"/*.json 2>/dev/null | wc -l | tr -d ' ')
            log_success "Hooks installed (4 handlers, $profile_count profiles)"
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

    # Copy index.ts entry point (gateway requires this)
    if [ -f "$SCRIPT_DIR/plugin/index.ts" ]; then
        cp "$SCRIPT_DIR/plugin/index.ts" "$PLUGIN_PATH/index.ts"
        log_success "Gateway entry point (index.ts) installed"
    else
        log_warning "index.ts not found in distribution — gateway may fail to load plugin"
    fi

    # Symlink OpenClaw SDK (index.ts imports from openclaw/plugin-sdk)
    _link_openclaw_sdk

    log_success "Plugin files installed"
}

# ─── SDK Symlink Helper ──────────────────────────────────────────────────────

_link_openclaw_sdk() {
    # index.ts imports openclaw/plugin-sdk which must be resolvable via node_modules
    local target_dir="$PLUGIN_PATH/node_modules"
    mkdir -p "$target_dir"

    # Already linked?
    if [ -d "$target_dir/openclaw" ] || [ -L "$target_dir/openclaw" ]; then
        log_success "OpenClaw SDK already linked"
        return
    fi

    local sdk_path=""

    # 1. Check other installed plugins
    for ext_dir in "$OPENCLAW_HOME/extensions"/*/; do
        local candidate="$ext_dir/node_modules/openclaw"
        if [ -d "$candidate" ] && [ "$(basename "$ext_dir")" != "$PLUGIN_NAME" ]; then
            sdk_path="$candidate"
            break
        fi
    done

    # 2. Check global openclaw install via which
    if [ -z "$sdk_path" ]; then
        local openclaw_bin
        openclaw_bin=$(which openclaw 2>/dev/null || true)
        if [ -n "$openclaw_bin" ]; then
            # Resolve symlinks to find actual install
            local real_bin
            real_bin=$(readlink -f "$openclaw_bin" 2>/dev/null || realpath "$openclaw_bin" 2>/dev/null || echo "$openclaw_bin")
            local global_dir
            global_dir=$(dirname "$(dirname "$real_bin")")/lib/node_modules/openclaw
            if [ -d "$global_dir" ]; then
                sdk_path="$global_dir"
            fi
        fi
    fi

    # 3. Check common nvm/node paths
    if [ -z "$sdk_path" ]; then
        for candidate in \
            "$HOME/.nvm/versions/node"/*/lib/node_modules/openclaw \
            /usr/local/lib/node_modules/openclaw \
            /usr/lib/node_modules/openclaw; do
            if [ -d "$candidate" ]; then
                sdk_path="$candidate"
                break
            fi
        done
    fi

    if [ -n "$sdk_path" ]; then
        ln -s "$sdk_path" "$target_dir/openclaw"
        log_success "OpenClaw SDK linked from $sdk_path"
    else
        log_warning "Could not find OpenClaw SDK — index.ts may fail to load"
        log_info "  Fix manually: ln -s \$(find ~/.openclaw/extensions -path '*/node_modules/openclaw' -maxdepth 3 | head -1) $target_dir/openclaw"
    fi
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

    # Map context engine to env value
    local context_engine_env=""
    if [ "$WIZARD_CONTEXT_ENGINE_RESOLVED" = "lossless-claw" ]; then
        context_engine_env="LACP_CONTEXT_ENGINE=lossless-claw"
    else
        context_engine_env="LACP_CONTEXT_ENGINE=file-based"
    fi

    cat > "$env_file" << ENVEOF
# ============================================================================
# OpenClaw LACP Fusion — Environment Configuration
# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# OS: $DETECTED_OS | Installer: v${PLUGIN_VERSION} (wizard)
# ============================================================================

# Layer 2: Knowledge Graph
LACP_OBSIDIAN_VAULT=$DETECTED_VAULT
LACP_KNOWLEDGE_ROOT=$OPENCLAW_HOME/data/knowledge
LACP_AUTOMATION_ROOT=$OPENCLAW_HOME/data/automation

# Context Engine
$context_engine_env

# Layer 5: Provenance
PROVENANCE_ROOT=$OPENCLAW_HOME/provenance
AGENT_ID_STORE=$OPENCLAW_HOME/agent-ids

# Feature Flags
LACP_LOCAL_FIRST=$WIZARD_LOCAL_FIRST
LACP_WITH_GITNEXUS=false
CODE_GRAPH_ENABLED=$WIZARD_CODE_GRAPH

# Hooks
OPENCLAW_HOOKS_PROFILE=$WIZARD_PROFILE

# To customize further, see the full template at:
# $PLUGIN_PATH/config/.openclaw-lacp.env.template
ENVEOF

    log_success "Config generated at $env_file"

    # Generate guard-rules.json with wizard settings
    local guard_config="$PLUGIN_PATH/config/guard-rules.json"
    if [ -f "$guard_config" ]; then
        log_warning "Guard config already exists at $guard_config (preserving)"
    elif [ -f "$SCRIPT_DIR/plugin/config/guard-rules.json" ]; then
        cp "$SCRIPT_DIR/plugin/config/guard-rules.json" "$guard_config"

        # Apply wizard guard level
        if [ "$HAS_JQ" = "true" ] && [ -n "$WIZARD_GUARD_LEVEL" ]; then
            local tmp
            tmp=$(mktemp)
            jq --arg level "$WIZARD_GUARD_LEVEL" '.defaults.block_level = $level' "$guard_config" > "$tmp" && mv "$tmp" "$guard_config"
            log_success "Guard default block level set to: $WIZARD_GUARD_LEVEL"
        fi

        # Apply disabled rules from wizard
        if [ "$HAS_JQ" = "true" ] && [ "${#WIZARD_DISABLED_RULES[@]}" -gt 0 ]; then
            for rule_id in "${WIZARD_DISABLED_RULES[@]}"; do
                local tmp
                tmp=$(mktemp)
                jq --arg rid "$rule_id" '
                    .rules = [.rules[] | if .id == $rid then .enabled = false else . end]
                ' "$guard_config" > "$tmp" && mv "$tmp" "$guard_config"
            done
            log_success "${#WIZARD_DISABLED_RULES[@]} guard rule(s) disabled per wizard selection"
        fi

        log_success "Guard config generated at $guard_config"
    else
        log_warning "Guard config template not found — will use factory defaults at runtime"
    fi
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

    # Resolve context engine for JSON (null for file-based)
    local ce_json="null"
    if [ "$WIZARD_CONTEXT_ENGINE_RESOLVED" = "lossless-claw" ]; then
        ce_json='"lossless-claw"'
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

    # Add plugin entry with wizard values
    tmp=$(mktemp)
    jq --arg vault "$DETECTED_VAULT" \
       --arg kr "$OPENCLAW_HOME/data/knowledge" \
       --arg profile "$WIZARD_PROFILE" \
       --arg tier "$WIZARD_POLICY_TIER" \
       --argjson cg "$WIZARD_CODE_GRAPH" \
       --argjson prov "$WIZARD_PROVENANCE" \
       --argjson lf "$WIZARD_LOCAL_FIRST" \
       --argjson ce "$ce_json" '
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
          "contextEngine": $ce
        }
      }
    ' "$GATEWAY_CONFIG" > "$tmp" && mv "$tmp" "$GATEWAY_CONFIG"
    log_success "Plugin entry added to gateway config"

    # Add install record
    tmp=$(mktemp)
    jq --arg ver "$PLUGIN_VERSION" --arg path "$PLUGIN_PATH" --arg now "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" '
      .plugins.installs["openclaw-lacp-fusion"] = {
        "source": "path",
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
        log_success "openclaw.plugin.json present"
        # Verify kind and name fields
        if [ "$HAS_JQ" = "true" ]; then
            if jq -e '.kind' "$PLUGIN_PATH/openclaw.plugin.json" &>/dev/null && \
               jq -e '.name' "$PLUGIN_PATH/openclaw.plugin.json" &>/dev/null; then
                ((pass++))
                log_success "Manifest has required 'kind' and 'name' fields"
            else
                log_warning "Manifest missing 'kind' or 'name' field — gateway may reject"
                ((fail++))
            fi
        fi
    else
        log_error "Missing openclaw.plugin.json"
        ((fail++))
    fi

    # Check package.json with required fields
    if [ -f "$PLUGIN_PATH/package.json" ]; then
        ((pass++))
        log_success "package.json present"
        if [ "$HAS_JQ" = "true" ]; then
            local pkg_ok=true
            jq -e '.type == "module"' "$PLUGIN_PATH/package.json" &>/dev/null || pkg_ok=false
            jq -e '.main == "index.ts"' "$PLUGIN_PATH/package.json" &>/dev/null || pkg_ok=false
            jq -e '.openclaw.extensions' "$PLUGIN_PATH/package.json" &>/dev/null || pkg_ok=false
            if [ "$pkg_ok" = "true" ]; then
                ((pass++))
                log_success "package.json has required fields (type, main, openclaw.extensions)"
            else
                log_warning "package.json missing required fields — gateway may not discover plugin"
                ((fail++))
            fi
        fi
    else
        log_error "Missing package.json"
        ((fail++))
    fi

    # Check index.ts entry point
    if [ -f "$PLUGIN_PATH/index.ts" ]; then
        ((pass++))
        log_success "index.ts entry point present"
    else
        log_error "Missing index.ts — gateway cannot load plugin"
        ((fail++))
    fi

    # Check OpenClaw SDK symlink
    if [ -d "$PLUGIN_PATH/node_modules/openclaw" ] || [ -L "$PLUGIN_PATH/node_modules/openclaw" ]; then
        ((pass++))
        log_success "OpenClaw SDK linked in node_modules"
    else
        log_warning "OpenClaw SDK not found in node_modules — index.ts imports will fail"
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

    # Check guard config
    if [ -f "$PLUGIN_PATH/config/guard-rules.json" ]; then
        ((pass++))
        log_success "Guard config present"
    else
        log_warning "Guard config missing — will use factory defaults"
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

        # Verify gateway config is valid JSON
        if jq '.' "$GATEWAY_CONFIG" &>/dev/null; then
            ((pass++))
            log_success "Gateway config is valid JSON"
        else
            log_error "Gateway config has JSON syntax errors"
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
    log_step 8 "Installation complete"

    cat << EOF

${GREEN}✓ openclaw-lacp-fusion v${PLUGIN_VERSION} installed${NC}

${BOLD}Configuration:${NC}
  ${GREEN}✓${NC} Plugin:       $PLUGIN_PATH
  ${GREEN}✓${NC} Vault:        $DETECTED_VAULT
  ${GREEN}✓${NC} Engine:       $WIZARD_CONTEXT_ENGINE_RESOLVED
  ${GREEN}✓${NC} Profile:      $WIZARD_PROFILE
  ${GREEN}✓${NC} Policy tier:  $WIZARD_POLICY_TIER

${BOLD}Next steps:${NC}
  1. Restart OpenClaw:     openclaw gateway restart
  2. Init project memory:  openclaw-memory-init ~/my-project agent-name webchat
  3. Validate setup:       openclaw-lacp-validate
  4. Test context query:   openclaw-brain-graph query "test"

${BOLD}Locations:${NC}
  Config:  $PLUGIN_PATH/config/.openclaw-lacp.env
  Gateway: $GATEWAY_CONFIG
  Logs:    $PLUGIN_PATH/logs/
  Docs:    $PLUGIN_PATH/docs/

${BOLD}Profiles:${NC}
  minimal-stop   — quality gate only (lightweight)
  balanced       — session context + quality gate (default)
  hardened-exec  — all 4 hooks enabled (maximum safety)

EOF
}

# ─── Main ────────────────────────────────────────────────────────────────────

main() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║          OpenClaw LACP Fusion Installer v${PLUGIN_VERSION}                    ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    echo ""

    detect_environment
    log_info "Detected OS: $DETECTED_OS"

    # Run interactive wizard
    run_wizard

    echo ""
    log_info "Starting installation..."

    check_prerequisites
    setup_plugin_directory
    create_data_directories
    generate_env_config
    update_gateway_config
    init_obsidian_vault
    run_validation
    print_summary

    log_success "Done! Run 'openclaw gateway restart' to activate the plugin."
    exit 0
}

main "$@"
