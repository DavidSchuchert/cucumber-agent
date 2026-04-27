#!/bin/bash
# CucumberAgent Uninstaller
# Usage: ./installer/uninstall.sh

set -e

CONFIG_DIR="${HOME}/.cucumber"
INSTALL_DIR="${HOME}/.cucumber-agent"

echo ""
echo "🥒 CucumberAgent Uninstaller"
echo "==========================="
echo ""

# Check if installed
if ! command -v cucumber &> /dev/null && [ ! -d "$INSTALL_DIR" ]; then
    echo "CucumberAgent is not installed."
    exit 0
fi

echo "This will remove:"
echo "  - CucumberAgent package"
echo "  - Config at $CONFIG_DIR"
echo "  - Source at $INSTALL_DIR (if exists)"
echo ""

read -p "Continue? [y/N] " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo "→ Removing package..."
uv tool uninstall cucumber-agent 2>/dev/null || true

echo "→ Removing config..."
rm -rf "$CONFIG_DIR"

echo "→ Removing source..."
rm -rf "$INSTALL_DIR"

echo ""
echo "✅ CucumberAgent uninstalled!"
echo ""
