#!/bin/bash
# Setup script for Claude platform integration
# Installs dependencies and configures the Claude plugin

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "==> Setting up Claude platform integration..."

# Check for required tools
check_dependency() {
    if ! command -v "$1" &> /dev/null; then
        echo "ERROR: '$1' is required but not installed."
        exit 1
    fi
}

check_dependency "node"
check_dependency "npm"

# Verify Node version >= 18
NODE_VERSION=$(node -e "process.stdout.write(process.versions.node.split('.')[0])")
if [ "$NODE_VERSION" -lt 18 ]; then
    echo "ERROR: Node.js 18+ is required. Found version $NODE_VERSION."
    exit 1
fi

echo "==> Node.js version: $(node --version)"

# Install MCP server dependencies if package.json exists
if [ -f "$SCRIPT_DIR/package.json" ]; then
    echo "==> Installing npm dependencies..."
    cd "$SCRIPT_DIR"
    # Use --prefer-offline to speed up repeated installs if cache is warm
    # Using --no-fund and --no-audit to reduce noise in personal setup
    npm install --prefer-offline --no-fund --no-audit
fi

# Validate plugin.json
if [ -f "$SCRIPT_DIR/.claude-plugin/plugin.json" ]; then
    echo "==> Validating plugin.json..."
    node -e "JSON.parse(require('fs').readFileSync('$SCRIPT_DIR/.claude-plugin/plugin.json', 'utf8')); console.log('plugin.json is valid.');"
fi

# Validate .mcp.json
if [ -f "$SCRIPT_DIR/.mcp.json" ]; then
    echo "==> Validating .mcp.json..."
    node -e "JSON.parse(require('fs').readFileSync('$SCRIPT_DIR/.mcp.json', 'utf8')); console.log('.mcp.json is valid.');"
fi

# Check for required environment variables
ENV_FILE="$PROJECT_ROOT/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "==> No .env file found. Creating from template..."
    cat > "$ENV_FILE" << 'EOF'
# All My AI Needs — Environment Configuration
# Copy this file and fill in your values

# Anthropic API Key (required for Claude)
ANTHROPIC_API_KEY=

# Optional: custom MCP server port
MCP_SERVER_PORT=3000
EOF
    echo "    Created $ENV_FILE — please fill in your API keys."
else
    echo "==> Found existing .env file."
    # Warn if ANTHROPIC_API_KEY appears to be unset in the existing .env
    if grep -qE '^ANTHROPIC_API_KEY=$' "$ENV_FILE"; then
        echo "    WARNING: ANTHROPIC_API_KEY is not set in .env — Claude won't work without it."
    fi
fi

echo ""
echo "==> Claude platform setup complete."
echo "    Next steps:"
echo "    1. Add your ANTHROPIC_API_KEY to .env"
echo "    2. Review platforms/claude/CLAUDE.md for usage instructions"
echo "    3. Run 'claude' in this directory to start a session"
