#!/usr/bin/env python3
"""Verify Claude platform MCP configuration and connectivity."""

import json
import os
import subprocess
import sys
from pathlib import Path


def load_mcp_config(config_path: Path) -> dict:
    """Load and parse the MCP configuration file."""
    if not config_path.exists():
        print(f"[ERROR] MCP config not found: {config_path}")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


def verify_node_packages(servers: dict) -> list[str]:
    """Check that required npm packages are installed for npx-based servers."""
    issues = []
    for name, config in servers.items():
        cmd = config.get("command", "")
        args = config.get("args", [])
        if cmd == "npx" and args:
            package = args[0] if not args[0].startswith("-") else (args[1] if len(args) > 1 else None)
            if package:
                result = subprocess.run(
                    ["npm", "list", "-g", package],
                    capture_output=True, text=True
                )
                if result.returncode != 0:
                    # npx will auto-install, just warn
                    print(f"  [WARN] {name}: package '{package}' not globally installed (npx will fetch)")
    return issues


def verify_env_vars(servers: dict) -> list[str]:
    """Check that all required environment variables are set."""
    missing = []
    for name, config in servers.items():
        env = config.get("env", {})
        for var, value in env.items():
            # Detect unresolved placeholders like ${VAR_NAME}
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                env_key = value[2:-1]
                if not os.environ.get(env_key):
                    missing.append(f"{name}: {var} ({env_key} not set)")
            elif isinstance(value, str) and value.startswith("$"):
                env_key = value[1:]
                if not os.environ.get(env_key):
                    missing.append(f"{name}: {var} ({env_key} not set)")
    return missing


def verify_local_commands(servers: dict) -> list[str]:
    """Verify that local command paths exist."""
    issues = []
    for name, config in servers.items():
        cmd = config.get("command", "")
        if cmd not in ("npx", "node", "python", "python3", "uvx") and cmd:
            path = Path(cmd)
            if path.is_absolute() and not path.exists():
                issues.append(f"{name}: command not found at '{cmd}'")
    return issues


def main():
    script_dir = Path(__file__).parent
    config_path = script_dir / ".mcp.json"

    print("=== Claude MCP Configuration Verifier ===")
    print(f"Config: {config_path}\n")

    config = load_mcp_config(config_path)
    servers = config.get("mcpServers", {})

    if not servers:
        print("[WARN] No MCP servers defined in config.")
        sys.exit(0)

    print(f"Found {len(servers)} server(s): {', '.join(servers.keys())}\n")

    # Verify environment variables
    print("[1/3] Checking environment variables...")
    missing_vars = verify_env_vars(servers)
    if missing_vars:
        print("  Missing:")
        for m in missing_vars:
            print(f"    - {m}")
    else:
        print("  All environment variables resolved.")

    # Verify node packages
    print("\n[2/3] Checking npm packages...")
    verify_node_packages(servers)

    # Verify local commands
    print("\n[3/3] Checking local command paths...")
    cmd_issues = verify_local_commands(servers)
    if cmd_issues:
        for issue in cmd_issues:
            print(f"  [ERROR] {issue}")
    else:
        print("  All command paths look valid.")

    print("\n=== Verification complete ===")
    if missing_vars or cmd_issues:
        print("[WARN] Some issues found. Review above before using Claude.")
        sys.exit(1)
    else:
        print("[OK] Configuration looks good.")


if __name__ == "__main__":
    main()
