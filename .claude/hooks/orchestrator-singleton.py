#!/usr/bin/env python3
"""
PreToolUse hook - Prevents multiple orchestrator instances.

Checks for .orchestrator.pid lock file and validates the process is running.
Blocks Bash commands that would start a second orchestrator.
"""

import json
import os
import sys
import re
from pathlib import Path


def get_project_root() -> Path:
    """Find project root by looking for .claude directory."""
    cwd = Path(os.getcwd())
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".claude").is_dir():
            return parent
    return cwd


def is_process_running(pid: int) -> bool:
    """Check if a process with given PID is running."""
    try:
        if sys.platform == "win32":
            import subprocess
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True
            )
            return str(pid) in result.stdout
        else:
            # Unix: send signal 0 to check if process exists
            os.kill(pid, 0)
            return True
    except (OSError, subprocess.SubprocessError):
        return False


def is_orchestrator_running(root: Path) -> tuple[bool, int | None]:
    """Check if orchestrator is running by examining PID file."""
    pid_file = root / ".orchestrator.pid"

    if not pid_file.exists():
        return False, None

    try:
        content = pid_file.read_text().strip()
        pid = int(content.split()[0])  # First line is PID

        if is_process_running(pid):
            return True, pid
        else:
            # Stale PID file - process died without cleanup
            pid_file.unlink()
            return False, None
    except (ValueError, IndexError, OSError):
        # Corrupt PID file
        try:
            pid_file.unlink()
        except OSError:
            pass
        return False, None


def is_orchestrator_command(command: str) -> bool:
    """Check if command would start the orchestrator."""
    patterns = [
        r"orchestrator\.py",
        r"orchestrator\s+--spec",
        r"python.*orchestrator",
    ]
    command_lower = command.lower()
    return any(re.search(p, command_lower) for p in patterns)


def main():
    data = json.load(sys.stdin)
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Only check Bash commands
    if tool_name.lower() != "bash":
        print(json.dumps({"decision": "allow"}))
        return

    command = tool_input.get("command", "")

    # Only check orchestrator-related commands
    if not is_orchestrator_command(command):
        print(json.dumps({"decision": "allow"}))
        return

    # Check if orchestrator is already running
    root = get_project_root()
    running, pid = is_orchestrator_running(root)

    if running:
        print(json.dumps({
            "decision": "block",
            "reason": f"""ORCHESTRATOR ALREADY RUNNING

An orchestrator instance is already running (PID: {pid}).

Running multiple orchestrators on the same database causes:
- Race conditions on spec updates
- Message delivery failures between agents
- Data corruption

Wait for the current orchestrator to complete, or stop it first:
  - Kill the process: taskkill /F /PID {pid}  (Windows)
  - Or: kill {pid}  (Unix)
  - Then delete: .orchestrator.pid

To check status: /pipeline-status
"""
        }))
        return

    print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
