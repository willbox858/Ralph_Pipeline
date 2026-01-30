"""
Hook Runner for the Ralph pipeline.

Provides the main entry points for Claude Code hooks:
- PreToolUse: Scope enforcement, message injection
- PostToolUse: Artifact tracking, audit logging
- Stop: Phase completion handling

These are invoked by Claude Code via .claude/hooks.json configuration.
"""

import json
import sys
import os
from typing import Dict, Any, Optional, List
from pathlib import Path
from datetime import datetime, timezone

from .scope import (
    is_path_allowed,
    is_tool_allowed,
    get_agent_context_from_env,
)


def read_hook_input() -> Dict[str, Any]:
    """Read hook input from stdin."""
    try:
        return json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        return {}


def write_hook_output(output: Dict[str, Any]) -> None:
    """Write hook output to stdout."""
    print(json.dumps(output))


def get_state_dir() -> Path:
    """Get the state directory for persistence."""
    project_root = os.environ.get("RALPH_PROJECT_ROOT", ".")
    state_dir = Path(project_root) / ".ralph" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def load_pending_messages(spec_id: str) -> List[Dict]:
    """Load pending messages for a spec from state."""
    state_dir = get_state_dir()
    inbox_file = state_dir / f"inbox_{spec_id}.json"
    
    if inbox_file.exists():
        try:
            data = json.loads(inbox_file.read_text(encoding="utf-8"))
            return data.get("messages", [])
        except (json.JSONDecodeError, IOError):
            pass
    
    return []


def clear_pending_messages(spec_id: str) -> None:
    """Clear pending messages after delivery."""
    state_dir = get_state_dir()
    inbox_file = state_dir / f"inbox_{spec_id}.json"
    
    if inbox_file.exists():
        inbox_file.unlink()


def track_artifact(spec_id: str, file_path: str) -> None:
    """Track an artifact created by the agent."""
    state_dir = get_state_dir()
    artifacts_file = state_dir / f"artifacts_{spec_id}.json"
    
    artifacts = []
    if artifacts_file.exists():
        try:
            artifacts = json.loads(artifacts_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            pass
    
    if file_path not in artifacts:
        artifacts.append(file_path)
        artifacts_file.write_text(json.dumps(artifacts), encoding="utf-8")


def log_tool_use(
    spec_id: str,
    tool_name: str,
    tool_input: Dict,
    tool_output: Optional[Dict] = None,
) -> None:
    """Log tool use for audit trail."""
    state_dir = get_state_dir()
    audit_file = state_dir / "audit.jsonl"
    
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "spec_id": spec_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_output": tool_output,
    }
    
    with open(audit_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# =============================================================================
# HOOK IMPLEMENTATIONS
# =============================================================================

def run_pre_tool_use() -> None:
    """
    PreToolUse hook - runs before each tool use.
    
    Responsibilities:
    1. Enforce scope (block writes outside allowed paths)
    2. Block forbidden tools
    3. Inject pending messages into context
    """
    input_data = read_hook_input()
    
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    
    # Get context
    context = get_agent_context_from_env()
    if not context:
        # No context = no restrictions (shouldn't happen in normal operation)
        write_hook_output({"decision": "allow"})
        return
    
    spec_id = context.get("spec_id", "unknown")
    allowed_paths = context.get("allowed_paths", [])
    forbidden_paths = context.get("forbidden_paths", [])
    allowed_tools = context.get("allowed_tools", [])
    
    # Check tool restrictions
    tool_allowed, tool_reason = is_tool_allowed(tool_name, allowed_tools)
    if not tool_allowed:
        write_hook_output({
            "decision": "block",
            "reason": f"TOOL BLOCKED: {tool_reason}",
        })
        return
    
    # Check path restrictions for file operations
    file_tools = ["Write", "Edit", "str_replace_editor", "create_file", "MultiEdit"]
    if tool_name in file_tools:
        file_path = tool_input.get("file_path") or tool_input.get("path") or ""
        
        if file_path:
            path_allowed, path_reason = is_path_allowed(
                file_path, allowed_paths, forbidden_paths
            )
            
            if not path_allowed:
                write_hook_output({
                    "decision": "block",
                    "reason": f"SCOPE VIOLATION: {path_reason}\nAllowed paths: {allowed_paths}",
                })
                return
    
    # Check for pending messages to inject
    pending = load_pending_messages(spec_id)
    if pending:
        # Clear messages so they're not re-delivered
        clear_pending_messages(spec_id)
        
        write_hook_output({
            "decision": "allow",
            "note": f"You have {len(pending)} pending message(s):\n" + 
                   "\n".join(f"- {m.get('type')}: {json.dumps(m.get('payload', {}))}" for m in pending),
        })
        return
    
    # Allow by default
    write_hook_output({"decision": "allow"})


def run_post_tool_use() -> None:
    """
    PostToolUse hook - runs after each tool use.
    
    Responsibilities:
    1. Track file artifacts
    2. Log tool usage for audit
    3. Validate written files (e.g., spec schema)
    """
    input_data = read_hook_input()
    
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    tool_output = input_data.get("tool_output", {})
    
    # Get context
    context = get_agent_context_from_env()
    spec_id = context.get("spec_id", "unknown") if context else "unknown"
    
    # Log for audit
    log_tool_use(spec_id, tool_name, tool_input, tool_output)
    
    # Track file artifacts
    file_tools = ["Write", "Edit", "str_replace_editor", "create_file", "MultiEdit"]
    if tool_name in file_tools:
        file_path = tool_input.get("file_path") or tool_input.get("path") or ""
        if file_path:
            track_artifact(spec_id, file_path)
    
    # Continue (post hooks don't block)
    write_hook_output({"decision": "continue"})


def run_on_stop() -> None:
    """
    Stop hook - runs when agent completes.
    
    Responsibilities:
    1. Capture final state
    2. Write completion marker
    3. Record artifacts created
    """
    input_data = read_hook_input()
    
    stop_reason = input_data.get("stop_reason", "unknown")
    
    # Get context
    context = get_agent_context_from_env()
    spec_id = context.get("spec_id", "unknown") if context else "unknown"
    
    # Write completion marker
    state_dir = get_state_dir()
    completion_file = state_dir / f"complete_{spec_id}.json"
    
    completion_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "spec_id": spec_id,
        "stop_reason": stop_reason,
        "success": stop_reason in ["end_turn", "tool_use"],
    }
    
    completion_file.write_text(json.dumps(completion_data), encoding="utf-8")
    
    write_hook_output({"acknowledged": True})


# =============================================================================
# CLI ENTRY POINTS
# =============================================================================

def main():
    """Main entry point for hook scripts."""
    if len(sys.argv) < 2:
        print("Usage: python -m ralph.hooks.runner <hook_type>", file=sys.stderr)
        sys.exit(1)
    
    hook_type = sys.argv[1]
    
    if hook_type == "pre_tool_use":
        run_pre_tool_use()
    elif hook_type == "post_tool_use":
        run_post_tool_use()
    elif hook_type == "on_stop":
        run_on_stop()
    else:
        print(f"Unknown hook type: {hook_type}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
