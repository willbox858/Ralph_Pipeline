#!/usr/bin/env python3
"""
PreToolUse hook - Enforces orchestrator delegation pattern.

Prevents orchestrator from directly modifying SOURCE files.
Orchestrator CAN modify spec.json and config files.
When an agent is spawned, all modifications are allowed.

Marker files:
- .orchestrator-lock: Indicates orchestrator mode active
- .agent-active: Created when agent spawns, allows all modifications
"""

import json
import os
import sys
from pathlib import Path


FILE_MODIFICATION_TOOLS = {
    "write", "edit", "multiedit", "create",
    "str_replace_editor", "str_replace",
    "file_write", "file_create", "file_edit", "update",
}

AGENT_SPAWN_TOOLS = {
    "task", "spawn", "agent", "dispatch", "todowrite",
}

# Files orchestrator CAN modify
ALLOWED_FILES = {
    "spec.json", "state.json", "errors.json", 
    "notes.md", "decisions.jsonl", "claude.md",
}

ALLOWED_PATTERNS = [
    "/specs/", "/.claude/", "/templates/",
]


def get_project_root() -> Path:
    cwd = Path(os.getcwd())
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".claude").is_dir():
            return parent
    return cwd


def is_orchestrator_mode(root: Path) -> bool:
    return (root / ".orchestrator-lock").exists() and not (root / ".agent-active").exists()


def activate_agent_mode(root: Path):
    (root / ".agent-active").write_text("Agent active\n", encoding='utf-8')


def is_allowed_file(file_path: str) -> bool:
    if not file_path:
        return False
    
    path_lower = file_path.lower()
    filename = Path(file_path).name.lower()
    
    if filename in ALLOWED_FILES:
        return True
    
    for pattern in ALLOWED_PATTERNS:
        if pattern in path_lower:
            return True
    
    return False


def normalize(name: str) -> str:
    return name.lower().replace("_", "").replace("-", "")


def main():
    data = json.load(sys.stdin)
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    
    root = get_project_root()
    norm_tool = normalize(tool_name)
    
    # Agent spawn - enable agent mode
    if norm_tool in {normalize(t) for t in AGENT_SPAWN_TOOLS}:
        activate_agent_mode(root)
        print(json.dumps({"decision": "allow"}))
        return
    
    # File modification - check restrictions
    if norm_tool in {normalize(t) for t in FILE_MODIFICATION_TOOLS}:
        if is_orchestrator_mode(root):
            file_path = tool_input.get("file_path") or tool_input.get("path") or ""
            
            if is_allowed_file(file_path):
                print(json.dumps({"decision": "allow"}))
                return
            
            print(json.dumps({
                "decision": "block",
                "reason": f"""ORCHESTRATOR DELEGATION REQUIRED

You are the orchestrator. Direct source file modifications are not allowed.

File: {file_path}

Instead, run ralph-recursive.py to spawn implementation agents:
  python3 .claude/scripts/ralph-recursive.py --spec ./spec.json

Note: You CAN directly modify spec.json and .claude/ config files.
"""
            }))
            return
    
    print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
