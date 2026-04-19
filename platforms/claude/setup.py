#!/usr/bin/env python3
"""
Setup script for the Claude platform integration.
Handles installation of dependencies, configuration validation,
and MCP server registration.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


PLATFORM_DIR = Path(__file__).parent
MCP_CONFIG = PLATFORM_DIR / ".mcp.json"
PLUGIN_CONFIG = PLATFORM_DIR / ".claude-plugin" / "plugin.json"


def check_python_version():
    """Ensure Python 3.9+ is available."""
    if sys.version_info < (3, 9):
        print(f"[ERROR] Python 3.9+ required. Found: {sys.version}")
        sys.exit(1)
    print(f"[OK] Python {sys.version.split()[0]}")


def check_node_version():
    """Ensure Node.js 18+ is available for MCP servers."""
    try:
        result = subprocess.run(
            ["node", "--version"], capture_output=True, text=True, check=True
        )
        version_str = result.stdout.strip().lstrip("v")
        major = int(version_str.split(".")[0])
        if major < 18:
            print(f"[WARN] Node.js 18+ recommended. Found: {result.stdout.strip()}")
        else:
            print(f"[OK] Node.js {result.stdout.strip()}")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("[WARN] Node.js not found — some MCP servers may not work.")


def validate_mcp_config():
    """Load and validate the .mcp.json configuration file."""
    if not MCP_CONFIG.exists():
        print(f"[ERROR] MCP config not found: {MCP_CONFIG}")
        sys.exit(1)

    with open(MCP_CONFIG) as f:
        config = json.load(f)

    servers = config.get("mcpServers", {})
    print(f"[OK] MCP config loaded — {len(servers)} server(s) defined")

    for name, server in servers.items():
        if "command" not in server:
            print(f"[WARN] Server '{name}' missing 'command' field")
        else:
            print(f"  - {name}: {server['command']}")

    return config


def resolve_env_vars(config: dict) -> list[str]:
    """Return a list of required environment variables from the MCP config."""
    required = []
    servers = config.get("mcpServers", {})
    for name, server in servers.items():
        env = server.get("env", {})
        for key, value in env.items():
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                var_name = value[2:-1]
                required.append((name, key, var_name))
    return required


def check_env_vars(config: dict):
    """Warn about missing environment variables required by MCP servers."""
    required = resolve_env_vars(config)
    missing = []
    for server_name, key, var_name in required:
        if not os.environ.get(var_name):
            missing.append((server_name, key, var_name))

    if missing:
        print("\n[WARN] Missing environment variables:")
        for server_name, key, var_name in missing:
            print(f"  - [{server_name}] {key} expects ${var_name}")
        print("  Set these in your shell profile or a .env file before using Claude.")
    else:
        print("[OK] All required environment variables are set")


def validate_plugin_json():
    """Validate the Claude plugin manifest."""
    if not PLUGIN_CONFIG.exists():
        print(f"[WARN] Plugin config not found: {PLUGIN_CONFIG}")
        return

    with open(PLUGIN_CONFIG) as f:
        plugin = json.load(f)

    name = plugin.get("name", "<unnamed>")
    version = plugin.get("version", "<no version>")
    print(f"[OK] Plugin manifest: {name} v{version}")


def main():
    print("=== all-my-ai-needs: Claude Platform Setup ===")
    print()

    check_python_version()
    check_node_version()
    validate_plugin_json()
    config = validate_mcp_config()
    check_env_vars(config)

    print()
    print("Setup complete. Run platforms/claude/setup.sh for full shell-based install.")


if __name__ == "__main__":
    main()
