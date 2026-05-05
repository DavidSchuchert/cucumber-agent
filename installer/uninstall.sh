#!/bin/sh
# CucumberAgent Uninstaller
# Usage: ./installer/uninstall.sh

set -eu

CONFIG_DIR="${CUCUMBER_CONFIG_DIR:-$HOME/.cucumber}"
INSTALL_DIR="${CUCUMBER_INSTALL_DIR:-$HOME/.cucumber-agent}"

say() {
    printf '%s\n' "$1"
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

say ""
say "🥒 CucumberAgent Uninstaller"
say "==========================="
say ""

if ! command_exists cucumber && [ ! -d "$INSTALL_DIR" ]; then
    say "CucumberAgent is not installed."
    exit 0
fi

say "This will remove:"
say "  - CucumberAgent package"
say "  - Config at $CONFIG_DIR"
say "  - Source at $INSTALL_DIR (if exists)"
say ""

printf 'Continue? [y/N] '
read -r reply

case "$reply" in
    y|Y|yes|YES)
        ;;
    *)
        say "Cancelled."
        exit 0
        ;;
esac

say "→ Removing package..."
if command_exists uv; then
    uv tool uninstall cucumber-agent 2>/dev/null || true
else
    say "uv not found; skipping uv tool uninstall."
fi

say "→ Removing config..."
rm -rf "$CONFIG_DIR"

say "→ Removing source..."
rm -rf "$INSTALL_DIR"

say ""
say "✅ CucumberAgent uninstalled!"
say ""
