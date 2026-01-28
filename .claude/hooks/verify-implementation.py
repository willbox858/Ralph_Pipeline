#!/usr/bin/env python3
"""
SubagentStop hook - Cleans up agent mode and verifies implementation.
"""

import json
import os
import sys
from pathlib import Path


def get_project_root() -> Path:
    cwd = Path(os.getcwd())
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".claude").is_dir():
            return parent
    return cwd


def clear_agent_mode():
    """Remove .agent-active marker."""
    root = get_project_root()
    agent_file = root / ".agent-active"
    if agent_file.exists():
        agent_file.unlink()


def main():
    data = json.load(sys.stdin)
    
    # Always clear agent mode when subagent stops
    clear_agent_mode()
    
    # Don't block, just clean up
    sys.exit(0)


if __name__ == "__main__":
    main()
