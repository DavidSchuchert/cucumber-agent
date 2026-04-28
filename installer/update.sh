#!/bin/bash
# CucumberAgent Updater
# Usage: curl -LsSf https://raw.githubusercontent.com/DavidSchuchert/cucumber-agent/main/installer/update.sh | sh

set -e

INSTALL_DIR="${HOME}/.cucumber-agent"

echo ""
echo "🥒 CucumberAgent Updater"
echo "=========================="
echo ""

if [ ! -d "$INSTALL_DIR" ]; then
    echo "❌ Error: CucumberAgent is not installed at $INSTALL_DIR"
    echo "   Please run the installer first."
    exit 1
fi

cd "$INSTALL_DIR"

echo "→ Checking for updates..."
git fetch origin main

LOCAL_HASH=$(git rev-parse HEAD)
REMOTE_HASH=$(git rev-parse origin/main)

if [ "$LOCAL_HASH" = "$REMOTE_HASH" ]; then
    echo "✅ CucumberAgent is already up to date (Version: ${LOCAL_HASH:0:7})."
    echo ""
    exit 0
fi

echo "→ New version found! Updating from ${LOCAL_HASH:0:7} to ${REMOTE_HASH:0:7}..."
git reset --hard origin/main

echo "→ Syncing dependencies and tools..."
if command -v uv &> /dev/null; then
    uv sync
    uv tool install -e . --force
else
    echo "⚠️  uv not found. Trying to install it first..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="${HOME}/.local/bin:${PATH}"
    uv sync
    uv tool install -e . --force
fi

echo ""
echo "✅ CucumberAgent successfully updated to the latest version!"
echo ""
echo "   Run 'cucumber run' to start chatting!"
echo "=========================================="
echo ""
