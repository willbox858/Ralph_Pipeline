#!/usr/bin/env python3
"""
Ralph Pipeline Upgrade Script

Upgrades a repo using an older version of Ralph Pipeline to the new architecture:
- Creates SQLite database
- Migrates existing specs to database
- Installs agent configs
- Sets up MCP server configuration
- Updates settings

Usage:
    python upgrade.py                  # Run in current directory
    python upgrade.py --check          # Check what needs upgrading (no changes)
    python upgrade.py --target /path   # Upgrade a specific repo
    python upgrade.py --force          # Skip confirmations

Prerequisites:
    - Run setup.py first to ensure dependencies are installed
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


# =============================================================================
# VERSION DETECTION
# =============================================================================

class RalphVersion:
    """Detected Ralph Pipeline version/state."""

    def __init__(self, root: Path):
        self.root = root
        self.claude_dir = root / ".claude"
        self.ralph_dir = root / ".ralph"
        self.specs_dir = root / "Specs" / "Active"

        # Detect what exists
        self.has_claude_dir = self.claude_dir.exists()
        self.has_ralph_dir = self.ralph_dir.exists()
        self.has_database = (self.ralph_dir / "ralph.db").exists() if self.ralph_dir.exists() else False
        self.has_mcp_config = (root / ".mcp.json").exists()
        self.has_agent_configs = (self.claude_dir / "agents" / "configs").exists() if self.claude_dir.exists() else False
        self.has_hooks_lib = (self.claude_dir / "lib" / "hooks.py").exists() if self.claude_dir.exists() else False
        self.has_orchestrator = (self.claude_dir / "scripts" / "orchestrator.py").exists() if self.claude_dir.exists() else False
        self.has_specs = self.specs_dir.exists() and any(self.specs_dir.rglob("spec.json"))

        # Check settings
        self.has_mcp_enabled = False
        settings_path = self.claude_dir / "settings.json"
        if settings_path.exists():
            try:
                settings = json.loads(settings_path.read_text())
                self.has_mcp_enabled = settings.get("enableAllProjectMcpServers", False)
            except (json.JSONDecodeError, IOError):
                pass

    def detect_version(self) -> str:
        """Detect which version of Ralph this is."""
        if not self.has_claude_dir:
            return "none"

        if not self.has_orchestrator:
            return "none"

        # v4 features: database, hooks, MCP
        if self.has_database and self.has_hooks_lib and self.has_mcp_config:
            return "v4"

        # Has orchestrator but not v4 features
        if self.has_orchestrator:
            return "v3"

        return "unknown"

    def get_missing_v4_features(self) -> list[str]:
        """List v4 features that are missing."""
        missing = []

        if not self.has_ralph_dir:
            missing.append("ralph_dir")
        if not self.has_database:
            missing.append("database")
        if not self.has_mcp_config:
            missing.append("mcp_config")
        if not self.has_agent_configs:
            missing.append("agent_configs")
        if not self.has_hooks_lib:
            missing.append("hooks_lib")
        if not self.has_mcp_enabled:
            missing.append("mcp_enabled")

        return missing

    def summary(self) -> str:
        """Get a summary of the detected state."""
        version = self.detect_version()
        yes, no = "[OK]", "[  ]"
        lines = [
            f"Detected version: {version}",
            f"Root: {self.root}",
            f"",
            f"Components:",
            f"  .claude/ directory:      {yes if self.has_claude_dir else no}",
            f"  .ralph/ directory:       {yes if self.has_ralph_dir else no}",
            f"  Database (ralph.db):     {yes if self.has_database else no}",
            f"  MCP config (.mcp.json):  {yes if self.has_mcp_config else no}",
            f"  Agent configs:           {yes if self.has_agent_configs else no}",
            f"  Hooks library:           {yes if self.has_hooks_lib else no}",
            f"  MCP enabled in settings: {yes if self.has_mcp_enabled else no}",
            f"  Existing specs:          {yes if self.has_specs else no}",
        ]
        return "\n".join(lines)


# =============================================================================
# UPGRADE STEPS
# =============================================================================

def create_ralph_directory(root: Path, dry_run: bool = False) -> bool:
    """Create .ralph/ directory structure."""
    ralph_dir = root / ".ralph"

    if ralph_dir.exists():
        print("  .ralph/ already exists")
        return True

    if dry_run:
        print("  Would create .ralph/")
        return True

    ralph_dir.mkdir(parents=True, exist_ok=True)
    print("  Created .ralph/")
    return True


def create_database(root: Path, dry_run: bool = False) -> bool:
    """Initialize the SQLite database."""
    db_path = root / ".ralph" / "ralph.db"

    if db_path.exists():
        print("  Database already exists")
        return True

    if dry_run:
        print("  Would create database")
        return True

    # Import and initialize database
    sys.path.insert(0, str(root / ".claude" / "lib"))
    try:
        from ralph_db import RalphDB

        # Create database - __init__ calls _init_schema() which creates tables
        RalphDB(db_path)

        print("  Created database")
        return True
    except ImportError as e:
        print(f"  ERROR: Could not import ralph_db: {e}")
        return False
    except Exception as e:
        print(f"  ERROR: Failed to create database: {e}")
        return False


def migrate_specs(root: Path, dry_run: bool = False) -> bool:
    """Migrate existing specs to the database."""
    specs_dir = root / "Specs" / "Active"

    if not specs_dir.exists():
        print("  No specs to migrate")
        return True

    spec_files = list(specs_dir.rglob("spec.json"))
    if not spec_files:
        print("  No spec files found")
        return True

    print(f"  Found {len(spec_files)} spec(s) to migrate")

    if dry_run:
        print("  Would migrate specs (use migrate-specs-to-db.py for details)")
        return True

    # Run the migration script
    migrate_script = root / ".claude" / "scripts" / "migrate-specs-to-db.py"
    if not migrate_script.exists():
        print("  ERROR: Migration script not found")
        return False

    try:
        result = subprocess.run(
            [sys.executable, str(migrate_script)],
            cwd=str(root),
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            print(f"  Migration output:\n{result.stdout}")
            if result.stderr:
                print(f"  Errors:\n{result.stderr}")
            return False

        print("  Specs migrated successfully")
        return True
    except Exception as e:
        print(f"  ERROR: Migration failed: {e}")
        return False


def install_agent_configs(root: Path, source: Path, dry_run: bool = False) -> bool:
    """Copy agent config files."""
    target_dir = root / ".claude" / "agents" / "configs"
    source_dir = source / ".claude" / "agents" / "configs"

    if not source_dir.exists():
        print("  ERROR: Source agent configs not found")
        return False

    if target_dir.exists():
        existing = list(target_dir.glob("*.json"))
        if existing:
            print(f"  Agent configs already exist ({len(existing)} files)")
            return True

    if dry_run:
        configs = list(source_dir.glob("*.json"))
        print(f"  Would copy {len(configs)} agent config(s)")
        return True

    target_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for config_file in source_dir.glob("*.json"):
        target_file = target_dir / config_file.name
        shutil.copy2(config_file, target_file)
        count += 1

    print(f"  Copied {count} agent config(s)")
    return True


def install_lib_files(root: Path, source: Path, dry_run: bool = False) -> bool:
    """Copy library files (hooks.py, message_hooks.py, ralph_db.py)."""
    target_dir = root / ".claude" / "lib"
    source_dir = source / ".claude" / "lib"

    files_to_copy = ["hooks.py", "message_hooks.py", "ralph_db.py"]

    if not source_dir.exists():
        print("  ERROR: Source lib directory not found")
        return False

    if dry_run:
        missing = [f for f in files_to_copy if not (target_dir / f).exists()]
        if missing:
            print(f"  Would copy: {', '.join(missing)}")
        else:
            print("  All lib files already exist")
        return True

    target_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    for filename in files_to_copy:
        source_file = source_dir / filename
        target_file = target_dir / filename

        if not source_file.exists():
            print(f"  WARNING: {filename} not found in source")
            continue

        if target_file.exists():
            # Check if they're different
            if source_file.read_bytes() == target_file.read_bytes():
                continue

        shutil.copy2(source_file, target_file)
        copied.append(filename)

    if copied:
        print(f"  Copied: {', '.join(copied)}")
    else:
        print("  All lib files up to date")

    return True


def install_schema_files(root: Path, source: Path, dry_run: bool = False) -> bool:
    """Copy schema files."""
    target_dir = root / ".claude" / "schema"
    source_dir = source / ".claude" / "schema"

    if not source_dir.exists():
        print("  No schema files to copy")
        return True

    if dry_run:
        schemas = list(source_dir.glob("*.json"))
        print(f"  Would copy {len(schemas)} schema file(s)")
        return True

    target_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for schema_file in source_dir.glob("*.json"):
        target_file = target_dir / schema_file.name
        if not target_file.exists() or schema_file.read_bytes() != target_file.read_bytes():
            shutil.copy2(schema_file, target_file)
            count += 1

    print(f"  Copied {count} schema file(s)")
    return True


def install_mcp_server(root: Path, source: Path, dry_run: bool = False) -> bool:
    """Copy MCP server script."""
    target_file = root / ".claude" / "scripts" / "status-mcp-server.py"
    source_file = source / ".claude" / "scripts" / "status-mcp-server.py"

    if not source_file.exists():
        print("  ERROR: Source MCP server not found")
        return False

    if target_file.exists():
        if source_file.read_bytes() == target_file.read_bytes():
            print("  MCP server already installed")
            return True

    if dry_run:
        print("  Would copy status-mcp-server.py")
        return True

    target_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, target_file)
    print("  Copied status-mcp-server.py")
    return True


def configure_mcp(root: Path, dry_run: bool = False) -> bool:
    """Create/update .mcp.json configuration."""
    mcp_path = root / ".mcp.json"

    mcp_config = {
        "mcpServers": {
            "ralph-status": {
                "type": "stdio",
                "command": "python",
                "args": [".claude/scripts/status-mcp-server.py"],
                "env": {}
            }
        }
    }

    if mcp_path.exists():
        try:
            existing = json.loads(mcp_path.read_text())
            if "ralph-status" in existing.get("mcpServers", {}):
                print("  MCP config already has ralph-status")
                return True

            # Merge in ralph-status
            if "mcpServers" not in existing:
                existing["mcpServers"] = {}
            existing["mcpServers"]["ralph-status"] = mcp_config["mcpServers"]["ralph-status"]
            mcp_config = existing
        except (json.JSONDecodeError, IOError):
            pass

    if dry_run:
        print("  Would create/update .mcp.json")
        return True

    mcp_path.write_text(json.dumps(mcp_config, indent=2) + "\n")
    print("  Created/updated .mcp.json")
    return True


def enable_mcp_in_settings(root: Path, dry_run: bool = False) -> bool:
    """Enable MCP servers in .claude/settings.json."""
    settings_path = root / ".claude" / "settings.json"

    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, IOError):
            pass

    if settings.get("enableAllProjectMcpServers", False):
        print("  MCP already enabled in settings")
        return True

    if dry_run:
        print("  Would enable MCP in settings.json")
        return True

    settings["enableAllProjectMcpServers"] = True
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    print("  Enabled MCP in settings.json")
    return True


def update_orchestrator(root: Path, source: Path, dry_run: bool = False) -> bool:
    """Update orchestrator.py to latest version."""
    target_file = root / ".claude" / "scripts" / "orchestrator.py"
    source_file = source / ".claude" / "scripts" / "orchestrator.py"

    if not source_file.exists():
        print("  ERROR: Source orchestrator not found")
        return False

    if not target_file.exists():
        print("  WARNING: Target orchestrator not found - copying fresh")
    elif source_file.read_bytes() == target_file.read_bytes():
        print("  Orchestrator already up to date")
        return True

    if dry_run:
        print("  Would update orchestrator.py")
        return True

    # Backup existing
    if target_file.exists():
        backup = target_file.with_suffix(".py.bak")
        shutil.copy2(target_file, backup)
        print(f"  Backed up existing orchestrator to {backup.name}")

    shutil.copy2(source_file, target_file)
    print("  Updated orchestrator.py")
    return True


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Upgrade Ralph Pipeline to v4",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check what needs upgrading (no changes)"
    )
    parser.add_argument(
        "--target",
        type=str,
        default=".",
        help="Target repo to upgrade (default: current directory)"
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Source Ralph Pipeline repo (default: this script's repo)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmations"
    )
    parser.add_argument(
        "--skip-specs",
        action="store_true",
        help="Skip spec migration"
    )

    args = parser.parse_args()

    # Determine paths
    target_root = Path(args.target).resolve()

    if args.source:
        source_root = Path(args.source).resolve()
    else:
        # Use the directory containing this script
        source_root = Path(__file__).parent.resolve()

    dry_run = args.check

    print("=" * 60)
    print("RALPH PIPELINE UPGRADE")
    print("=" * 60)
    print(f"Target: {target_root}")
    print(f"Source: {source_root}")
    if dry_run:
        print("Mode: CHECK ONLY (no changes)")
    print("=" * 60)
    print()

    # Detect current state
    version = RalphVersion(target_root)
    print(version.summary())
    print()

    current_version = version.detect_version()

    if current_version == "none":
        print("ERROR: This doesn't appear to be a Ralph Pipeline repo.")
        print("       Expected .claude/scripts/orchestrator.py to exist.")
        sys.exit(1)

    if current_version == "v4":
        missing = version.get_missing_v4_features()
        if not missing:
            print("Already on v4 with all features. Nothing to upgrade.")
            sys.exit(0)
        print(f"On v4 but missing: {', '.join(missing)}")
    else:
        print(f"Upgrading from {current_version} to v4")

    print()

    # Confirm unless forced
    if not dry_run and not args.force:
        confirm = input("Proceed with upgrade? [y/N]: ")
        if confirm.lower() not in ("y", "yes"):
            print("Aborted.")
            sys.exit(0)
        print()

    # Run upgrade steps
    print("-" * 60)
    print("UPGRADE STEPS")
    print("-" * 60)

    steps = [
        ("Creating .ralph/ directory", lambda: create_ralph_directory(target_root, dry_run)),
        ("Installing lib files", lambda: install_lib_files(target_root, source_root, dry_run)),
        ("Creating database", lambda: create_database(target_root, dry_run)),
        ("Installing agent configs", lambda: install_agent_configs(target_root, source_root, dry_run)),
        ("Installing schema files", lambda: install_schema_files(target_root, source_root, dry_run)),
        ("Installing MCP server", lambda: install_mcp_server(target_root, source_root, dry_run)),
        ("Configuring MCP", lambda: configure_mcp(target_root, dry_run)),
        ("Enabling MCP in settings", lambda: enable_mcp_in_settings(target_root, dry_run)),
        ("Updating orchestrator", lambda: update_orchestrator(target_root, source_root, dry_run)),
    ]

    if not args.skip_specs:
        steps.append(
            ("Migrating specs", lambda: migrate_specs(target_root, dry_run))
        )

    success = True
    for step_name, step_fn in steps:
        print(f"\n[{step_name}]")
        if not step_fn():
            success = False
            print(f"  FAILED: {step_name}")
            if not args.force:
                print("\nUpgrade halted. Use --force to continue past errors.")
                sys.exit(1)

    # Summary
    print()
    print("=" * 60)
    if dry_run:
        print("CHECK COMPLETE")
        print("Run without --check to perform the upgrade.")
    elif success:
        print("UPGRADE COMPLETE")
        print()
        print("Next steps:")
        print("  1. Restart Claude Code to load MCP server")
        print("  2. Run: python setup.py --check")
        print("  3. Test with: /pipeline-status")
    else:
        print("UPGRADE COMPLETED WITH ERRORS")
        print("Check the output above for details.")
    print("=" * 60)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
