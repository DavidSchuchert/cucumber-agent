#!/bin/sh
# CucumberAgent Installer
# Usage: curl -LsSf https://raw.githubusercontent.com/DavidSchuchert/cucumber-agent/main/installer/install.sh | sh

set -eu

REPO="DavidSchuchert/cucumber-agent"
INSTALL_DIR="${CUCUMBER_INSTALL_DIR:-$HOME/.cucumber-agent}"
CONFIG_DIR="${CUCUMBER_CONFIG_DIR:-$HOME/.cucumber}"
CONFIG_FILE="$CONFIG_DIR/config.yaml"
SKILLS_DIR="$CONFIG_DIR/skills"

is_interactive=false
[ -t 0 ] && is_interactive=true

say() {
    printf '%s\n' "$1"
}

warn() {
    printf '⚠️  %s\n' "$1"
}

die() {
    printf '❌ %s\n' "$1" >&2
    exit 1
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

print_banner() {
    printf '\n'
    printf '\033[1;32m           _____\033[0m\n'
    printf '\033[1;32m         /       \\\033[0m\n'
    printf '\033[1;32m        |  \033[1;37m(O)(O)\033[1;32m |\033[0m\n'
    printf '\033[1;32m        |    \033[1;37m<\033[1;32m    |\033[0m\n'
    printf '\033[1;32m        |  \033[1;37m'\''---'\''  |\033[0m\n'
    printf '\033[1;32m        |         |\033[0m\n'
    printf '\033[1;32m        |         |\033[0m\n'
    printf '\033[1;32m        |         |\033[0m\n'
    printf '\033[1;32m         \\_______/\033[0m\n'
    printf '\n'
    printf '\033[1;32m🥒 CucumberAgent Installer\033[0m\n'
    printf '\033[1;32m==========================\033[0m\n\n'
}

ensure_prerequisites() {
    command_exists git || die "git is required. Install git and run the installer again."
    command_exists curl || die "curl is required. Install curl and run the installer again."
}

ensure_uv() {
    if ! command_exists uv; then
        say "→ Installing uv (Python package manager)..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
    fi

    export PATH="$HOME/.local/bin:$PATH"
    command_exists uv || die "uv was installed but is not on PATH. Add $HOME/.local/bin to PATH and retry."

    for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
        if [ -f "$rc" ] && ! grep -q '\.local/bin' "$rc"; then
            printf '%s\n' 'export PATH="$HOME/.local/bin:$PATH"' >> "$rc"
            say "✓ Added ~/.local/bin to PATH in $(basename "$rc")"
        fi
    done

    say "✓ uv ready"
}

checkout_source() {
    if [ ! -d "$INSTALL_DIR" ]; then
        say "→ Downloading CucumberAgent from GitHub..."
        git clone "https://github.com/$REPO.git" "$INSTALL_DIR"
        return
    fi

    if [ ! -d "$INSTALL_DIR/.git" ]; then
        die "$INSTALL_DIR exists but is not a git checkout. Move it aside or set CUCUMBER_INSTALL_DIR."
    fi

    say "→ Updating existing installation safely..."
    cd "$INSTALL_DIR"
    git fetch origin main

    if ! git diff --quiet || ! git diff --cached --quiet; then
        warn "Existing checkout has local changes. Leaving source as-is."
        warn "Run 'git status' in $INSTALL_DIR, commit/stash your changes, then run 'cucumber update'."
        return
    fi

    git merge --ff-only origin/main
}

sync_default_skills() {
    if [ ! -d "$INSTALL_DIR/default-skills" ]; then
        return
    fi

    say "→ Installing default skills..."
    mkdir -p "$SKILLS_DIR"

    found=false
    for skill in "$INSTALL_DIR"/default-skills/*.yaml; do
        [ -f "$skill" ] || continue
        found=true
        cp "$skill" "$SKILLS_DIR/"
    done

    if [ "$found" = true ]; then
        say "✓ Default skills synced to $SKILLS_DIR"
    else
        warn "No default skill YAML files found."
    fi
}

write_personality_defaults() {
    personality_dir="$CONFIG_DIR/personality"
    user_dir="$CONFIG_DIR/user"
    mkdir -p "$personality_dir" "$user_dir"

    if [ ! -f "$personality_dir/personality.md" ]; then
        cat > "$personality_dir/personality.md" <<'EOF'
# Personality
name: Cucumber
emoji: 🥒
tone: friendly
language: en
greeting: Hi! I'm Cucumber. How can I help you today?
strengths: coding, web research, answering questions, problem-solving
interests: AI, technology, programming, open source
EOF
    fi

    if [ ! -f "$user_dir/user.md" ]; then
        cat > "$user_dir/user.md" <<'EOF'
# User
name:
bio:
github:
portfolio:
EOF
    fi
}

write_default_config() {
    mkdir -p "$CONFIG_DIR"
    write_personality_defaults

    provider="minimax"
    model="MiniMax-M2.7"
    base_url="https://api.minimax.io/v1"
    api_key=""

    if [ -n "${MINIMAX_API_KEY:-}" ]; then
        api_key="$MINIMAX_API_KEY"
    elif [ -n "${OPENROUTER_API_KEY:-}" ]; then
        provider="openrouter"
        model="openai/gpt-4o-mini"
        base_url="https://openrouter.ai/api/v1"
        api_key="$OPENROUTER_API_KEY"
    elif [ -n "${DEEPSEEK_API_KEY:-}" ]; then
        provider="deepseek"
        model="deepseek-chat"
        base_url="https://api.deepseek.com"
        api_key="$DEEPSEEK_API_KEY"
    else
        warn "No API key found in environment."
        warn "Set MINIMAX_API_KEY, OPENROUTER_API_KEY, or DEEPSEEK_API_KEY, then run 'cucumber init'."
    fi

    if [ -n "$api_key" ]; then
        api_key_yaml="\"$api_key\""
    else
        api_key_yaml="null"
    fi

    cat > "$CONFIG_FILE" <<EOF
agent:
  provider: $provider
  model: "$model"
  temperature: 0.7
  max_tokens: null
  system_prompt: "You are CucumberAgent, a helpful AI assistant."
providers:
  $provider:
    api_key: $api_key_yaml
    base_url: "$base_url"
    model: "$model"
preferences:
  can_search_web: true
  can_code: true
  can_remember: true
  smart_retry: true
context:
  max_tokens: 8000
  remember_last: 10
memory:
  enabled: true
EOF
    chmod 600 "$CONFIG_FILE" 2>/dev/null || true
    say "✓ Config created at $CONFIG_FILE"
}

run_setup_if_needed() {
    if [ -f "$CONFIG_FILE" ]; then
        say "✓ Config exists at $CONFIG_FILE"
        write_personality_defaults
        return
    fi

    if [ "$is_interactive" = true ]; then
        say "→ Running setup wizard..."
        cd "$INSTALL_DIR"
        uv run python installer/init.py
    else
        say "→ Creating default config..."
        write_default_config
    fi
}

print_done() {
    printf '\n'
    say "✅ CucumberAgent installed!"
    printf '\n'
    say "=========================================="
    say "  🚀  CucumberAgent is ready!"
    printf '\n'
    say "  Run 'cucumber run' to start chatting."
    say "  Run 'cucumber init' to reconfigure."
    say "  Run 'cucumber update' to update safely."
    say "=========================================="
    printf '\n'
}

print_banner
ensure_prerequisites
ensure_uv
checkout_source

cd "$INSTALL_DIR"
say "→ Installing package..."
uv sync
uv tool install -e . --force

sync_default_skills
run_setup_if_needed
print_done
