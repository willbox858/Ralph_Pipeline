#!/usr/bin/env python3
"""
Initialize orchestrator mode.
Creates .orchestrator-lock to prevent direct source file modifications.

Usage:
    python3 init-orchestrator.py
"""

import os
from datetime import datetime, timezone
from pathlib import Path


def get_project_root() -> Path:
    """Find project root."""
    cwd = Path(os.getcwd())
    
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".claude").is_dir():
            return parent
        if (parent / "CLAUDE.md").exists():
            return parent
    
    return cwd


def main():
    project_root = get_project_root()
    lock_file = project_root / ".orchestrator-lock"
    agent_file = project_root / ".agent-active"
    
    # Create orchestrator lock
    timestamp = datetime.now(timezone.utc).isoformat()
    session_id = os.environ.get("CLAUDE_SESSION_ID", "unknown")
    
    lock_file.write_text(f"Orchestrator session: {timestamp}\nSession ID: {session_id}\n", encoding='utf-8')
    
    # Clean up stale agent marker
    if agent_file.exists():
        agent_file.unlink()
    
    print("* Orchestrator mode activated")
    print("  - Source file modifications will be blocked")
    print("  - Spec/config files can be edited directly")
    print("  - Use agents for implementation tasks")


if __name__ == "__main__":
    main()
