#!/bin/bash
# CucumberAgent Installer
# Usage: curl -LsSf https://get.cucumber.sh/install.sh | sh
# Or locally: bash installer/install.sh

set -e

INSTALL_DIR="${HOME}/.cucumber-agent"
CURRENT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IS_INTERACTIVE="false"

# Check if we have a TTY
if [ -t 0 ]; then
    IS_INTERACTIVE="true"
fi

echo ""
echo "🥒 CucumberAgent Installer"
echo "=========================="
echo ""

# Step 1: Install uv
if ! command -v uv &> /dev/null; then
    echo "→ Installing uv (Python package manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="${HOME}/.local/bin:${PATH}"
fi

echo "✓ uv ready"

# Step 2: Setup source directory
if [ -d "$CURRENT_DIR/src" ] && [ -f "$CURRENT_DIR/pyproject.toml" ]; then
    echo "→ Installing from local source..."
    SOURCE_DIR="$CURRENT_DIR"
elif [ -d "$INSTALL_DIR/src" ] && [ -f "$INSTALL_DIR/pyproject.toml" ]; then
    SOURCE_DIR="$INSTALL_DIR"
elif [ -d "/Users/davidwork/cucumber-agent/src" ]; then
    SOURCE_DIR="/Users/davidwork/cucumber-agent"
else
    echo "ERROR: Could not find CucumberAgent source."
    exit 1
fi

cd "$SOURCE_DIR"

# Step 3: Install package as a tool
echo "→ Installing package..."
uv sync
uv tool install -e .

echo ""
echo "✅ CucumberAgent installed!"
echo ""
echo "→ Adding to PATH..."

# Add uv tool directory to PATH
UV_TOOL_DIR="${HOME}/.local/share/uv/tools"
if [ -d "$UV_TOOL_DIR/cucumber-agent" ]; then
    export PATH="${UV_TOOL_DIR}/cucumber-agent/bin:${PATH}"
    echo "✓ PATH updated"
fi

# Step 4: Setup config
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
            BASE_URL="https://api.minimax.io/anthropic"
            API_KEY="$MINIMAX_API_KEY"
        elif [ -n "$OPENROUTER_API_KEY" ]; then
            PROVIDER="openrouter"
            MODEL="openai/gpt-4o-mini"
            BASE_URL="https://openrouter.ai/api/v1"
            API_KEY="$OPENROUTER_API_KEY"
        else
            echo "⚠️  No API key found in environment."
            echo "   Set MINIMAX_API_KEY or OPENROUTER_API_KEY before running 'cucumber run'"
            echo ""

            # Create minimal config
            cat > "$CONFIG_FILE" << 'EOF'
agent:
  provider: minimax
  model: "MiniMax-M2.7"
  temperature: 0.7
  system_prompt: "You are CucumberAgent, a helpful AI assistant."

providers:
  minimax:
    api_key: null
    base_url: "https://api.minimax.io/anthropic"
    model: "MiniMax-M2.7"
EOF
            echo "   Created config at $CONFIG_FILE"
            echo "   Edit it to add your API key, then run 'cucumber run'"
        fi

        # Write config if we have all values
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
            echo "   Created config with API key from environment"
        fi
    fi
else
    echo "Config already exists at $CONFIG_FILE"
fi

echo ""
echo "=========================================="
echo ""
echo "  Run 'cucumber run' to start chatting!"
echo ""