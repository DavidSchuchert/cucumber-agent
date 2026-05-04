#!/bin/bash
# CucumberAgent Updater
# Usage: curl -LsSf https://raw.githubusercontent.com/DavidSchuchert/cucumber-agent/main/installer/update.sh | sh

set -e

# Detect installation directory:
# 1. Use the directory where this script is located (go up one level from installer/)
# 2. Fallback to default ~/.cucumber-agent
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
if [ -d "$SCRIPT_DIR/../.git" ]; then
    INSTALL_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"
else
    INSTALL_DIR="${HOME}/.cucumber-agent"
fi

echo ""
echo -e "\033[1;32m           _____\033[0m"
echo -e "\033[1;32m         /       \\\033[0m"
echo -e "\033[1;32m        |  \033[1;37m(O)(O)\033[1;32m |\033[0m"
echo -e "\033[1;32m        |    \033[1;37m<\033[1;32m    |\033[0m"
echo -e "\033[1;32m        |  \033[1;37m'---'\033[1;32m  |\033[0m"
echo -e "\033[1;32m        |         |\033[0m"
echo -e "\033[1;32m        |         |\033[0m"
echo -e "\033[1;32m        |         |\033[0m"
echo -e "\033[1;32m         \_______/\033[0m"
echo ""
echo -e "\033[1;32m🥒 CucumberAgent Updater\033[0m"
echo -e "\033[1;32m==========================\033[0m"
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

# Sync new default skills
SKILLS_DIR="${HOME}/.cucumber/skills"
if [ -d "${INSTALL_DIR}/default-skills" ]; then
    echo "→ Syncing default skills..."
    mkdir -p "$SKILLS_DIR"
    cp "${INSTALL_DIR}/default-skills/"*.yaml "$SKILLS_DIR/"
    echo "✓ Skills synced to ${SKILLS_DIR}/"
fi

echo ""
echo "✅ CucumberAgent successfully updated to the latest version!"
echo ""
echo "   Run 'cucumber run' to start chatting!"
echo "=========================================="
echo ""
