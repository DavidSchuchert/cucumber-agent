#!/bin/bash
# CucumberAgent Installer
# Usage: curl -LsSf https://raw.githubusercontent.com/DavidSchuchert/cucumber-agent/main/installer/install.sh | sh

set -e

REPO="DavidSchuchert/cucumber-agent"
INSTALL_DIR="${HOME}/.cucumber-agent"
IS_INTERACTIVE="false"

# Check if we have a TTY
if [ -t 0 ]; then
    IS_INTERACTIVE="true"
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
echo -e "\033[1;32m🥒 CucumberAgent Installer\033[0m"
echo -e "\033[1;32m==========================\033[0m"
echo ""

# Step 1: Install uv
if ! command -v uv &> /dev/null; then
    echo "→ Installing uv (Python package manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="${HOME}/.local/bin:${PATH}"
fi

echo "✓ uv ready"

# Step 2: Clone or update source from GitHub
if [ ! -d "$INSTALL_DIR" ]; then
    echo "→ Downloading CucumberAgent from GitHub..."
    git clone "https://github.com/${REPO}.git" "$INSTALL_DIR"
else
    echo "→ Updating existing installation..."
    cd "$INSTALL_DIR"
    git pull || true
fi

cd "$INSTALL_DIR"

# Step 3: Install package as a tool
echo "→ Installing package..."
uv sync
uv tool install -e .

echo ""
echo "✅ CucumberAgent installed!"
echo ""

# Step 4: Setup config if needed
CONFIG_DIR="${HOME}/.cucumber"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"

if [ ! -f "$CONFIG_FILE" ]; then
    if [ "$IS_INTERACTIVE" = "true" ]; then
        echo "→ Running setup wizard..."
        uv run python installer/init.py
    else
        echo "→ Creating default config..."
        mkdir -p "$CONFIG_DIR"

        # Check for API keys in environment
        if [ -n "$MINIMAX_API_KEY" ]; then
            PROVIDER="minimax"
            MODEL="MiniMax-M2.7"
            BASE_URL="https://api.minimax.io/v1"
            API_KEY="$MINIMAX_API_KEY"
        elif [ -n "$OPENROUTER_API_KEY" ]; then
            PROVIDER="openrouter"
            MODEL="openai/gpt-4o-mini"
            BASE_URL="https://openrouter.ai/api/v1"
            API_KEY="$OPENROUTER_API_KEY"
        else
            echo "⚠️  No API key found in environment."
            echo "   Set MINIMAX_API_KEY or OPENROUTER_API_KEY"
            echo "   Then run 'cucumber init' to configure."

            cat > "$CONFIG_FILE" << 'EOF'
agent:
  provider: minimax
  model: "MiniMax-M2.7"
  temperature: 0.7
  system_prompt: "You are CucumberAgent, a helpful AI assistant."
providers:
  minimax:
    api_key: null
    base_url: "https://api.minimax.io/v1"
    model: "MiniMax-M2.7"
EOF
            echo "   Created empty config at $CONFIG_FILE"
        fi

        if [ -n "$API_KEY" ]; then
            cat > "$CONFIG_FILE" << EOF
agent:
  provider: $PROVIDER
  model: "$MODEL"
  temperature: 0.7
  system_prompt: "You are CucumberAgent, a helpful AI assistant."
providers:
  $PROVIDER:
    api_key: "$API_KEY"
    base_url: "$BASE_URL"
    model: "$MODEL"
EOF
            echo "   Config created with API key from environment"
        fi
    fi
else
    echo "✓ Config exists at $CONFIG_FILE"
fi

echo ""
echo "=========================================="
echo "  🚀  CucumberAgent is ready!"
echo ""
echo "  Run 'cucumber run' to start chatting!"
echo "  Run 'cucumber --help' for options."
echo "=========================================="
echo ""
