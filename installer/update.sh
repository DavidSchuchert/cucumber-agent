#!/bin/sh
# CucumberAgent Updater
# Usage: curl -LsSf https://raw.githubusercontent.com/DavidSchuchert/cucumber-agent/main/installer/update.sh | sh

set -eu

INSTALL_DIR="${CUCUMBER_INSTALL_DIR:-$HOME/.cucumber-agent}"
CONFIG_DIR="${CUCUMBER_CONFIG_DIR:-$HOME/.cucumber}"
SKILLS_DIR="$CONFIG_DIR/skills"

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

short_hash() {
    printf '%s' "$1" | cut -c 1-7
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
    printf '\033[1;32m🥒 CucumberAgent Updater\033[0m\n'
    printf '\033[1;32m=========================\033[0m\n\n'
}

ensure_uv() {
    if ! command_exists uv; then
        say "→ Installing uv (Python package manager)..."
        command_exists curl || die "curl is required to install uv."
        curl -LsSf https://astral.sh/uv/install.sh | sh
    fi
    export PATH="$HOME/.local/bin:$PATH"
    command_exists uv || die "uv is not available on PATH after installation."
}

sync_default_skills() {
    if [ ! -d "$INSTALL_DIR/default-skills" ]; then
        return
    fi

    say "→ Syncing default skills..."
    mkdir -p "$SKILLS_DIR"

    found=false
    for skill in "$INSTALL_DIR"/default-skills/*.yaml; do
        [ -f "$skill" ] || continue
        found=true
        cp "$skill" "$SKILLS_DIR/"
    done

    if [ "$found" = true ]; then
        say "✓ Skills synced to $SKILLS_DIR"
    else
        warn "No default skill YAML files found."
    fi
}

print_banner

command_exists git || die "git is required for updates."

if [ ! -d "$INSTALL_DIR" ]; then
    die "CucumberAgent is not installed at $INSTALL_DIR. Run the installer first."
fi

if [ ! -d "$INSTALL_DIR/.git" ]; then
    die "$INSTALL_DIR is not a git checkout. Reinstall or set CUCUMBER_INSTALL_DIR."
fi

cd "$INSTALL_DIR"

if ! git diff --quiet || ! git diff --cached --quiet; then
    git status --short
    die "Local changes detected. Commit or stash them before updating. No files were changed."
fi

say "→ Checking for updates..."
git fetch origin main

local_hash="$(git rev-parse HEAD)"
remote_hash="$(git rev-parse origin/main)"

if [ "$local_hash" = "$remote_hash" ]; then
    say "✅ CucumberAgent is already up to date (Version: $(short_hash "$local_hash"))."
else
    say "→ Updating from $(short_hash "$local_hash") to $(short_hash "$remote_hash")..."
    git merge --ff-only origin/main
fi

ensure_uv

say "→ Syncing dependencies and command-line tool..."
uv sync
uv tool install -e . --force

sync_default_skills

printf '\n'
say "✅ CucumberAgent update complete!"
say "   Run 'cucumber run' to start chatting."
say "=========================================="
printf '\n'
