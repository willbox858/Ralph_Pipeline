"""
SDK-native hook callbacks for the Ralph pipeline.

These are async callbacks that can be passed directly to ClaudeAgentOptions,
as an alternative to the CLI-based hooks in runner.py.

Usage:
    from ralph.hooks.sdk_hooks import create_ralph_hooks

    options = ClaudeAgentOptions(
        hooks=create_ralph_hooks(context),
        ...
    )
"""

from typing import Dict, Any, Optional, List, Callable, Awaitable
from pathlib import Path
import json

from claude_agent_sdk import HookMatcher

from .scope import is_path_allowed, is_tool_allowed


# Type alias for hook callbacks
HookCallback = Callable[[Dict[str, Any], Optional[str], Dict[str, Any]], Awaitable[Dict[str, Any]]]


async def pre_tool_use_hook(
    input_data: Dict[str, Any],
    tool_use_id: Optional[str],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    PreToolUse hook - runs before each tool use.

    Enforces scope restrictions and tool allowlists.
    """
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    hook_event_name = input_data.get("hook_event_name", "PreToolUse")

    # Get restrictions from context
    allowed_paths = context.get("allowed_paths", [])
    forbidden_paths = context.get("forbidden_paths", [])
    allowed_tools = context.get("allowed_tools", [])

    # Check tool restrictions
    tool_allowed, tool_reason = is_tool_allowed(tool_name, allowed_tools)
    if not tool_allowed:
        return {
            "hookSpecificOutput": {
                "hookEventName": hook_event_name,
                "permissionDecision": "deny",
                "permissionDecisionReason": f"TOOL BLOCKED: {tool_reason}",
            }
        }

    # Check path restrictions for file operations
    file_tools = ["Write", "Edit", "str_replace_editor", "create_file", "MultiEdit"]
    if tool_name in file_tools:
        file_path = tool_input.get("file_path") or tool_input.get("path") or ""
        if file_path:
            path_allowed, path_reason = is_path_allowed(
                file_path, allowed_paths, forbidden_paths
            )
            if not path_allowed:
                return {
                    "hookSpecificOutput": {
                        "hookEventName": hook_event_name,
                        "permissionDecision": "deny",
                        "permissionDecisionReason": f"SCOPE VIOLATION: {path_reason}",
                    }
                }

    # Allow by default
    return {}


async def post_tool_use_hook(
    input_data: Dict[str, Any],
    tool_use_id: Optional[str],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    PostToolUse hook - runs after each tool use.

    Tracks artifacts and logs tool usage.
    """
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Track file artifacts
    artifact_tracker = context.get("artifact_tracker")
    if artifact_tracker is not None:
        file_tools = ["Write", "Edit", "str_replace_editor", "create_file", "MultiEdit"]
        if tool_name in file_tools:
            file_path = tool_input.get("file_path") or tool_input.get("path") or ""
            if file_path and file_path not in artifact_tracker:
                artifact_tracker.append(file_path)

    # PostToolUse hooks don't block
    return {}


async def stop_hook(
    input_data: Dict[str, Any],
    tool_use_id: Optional[str],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Stop hook - runs when agent completes.

    Captures final state.
    """
    # Stop hooks don't block, just acknowledge
    return {}


async def post_tool_use_failure_hook(
    input_data: Dict[str, Any],
    tool_use_id: Optional[str],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    PostToolUseFailure hook - runs when tool execution fails.

    Logs the failure for audit purposes. The agent will see the error
    and can describe the issue in its own words via MCP messaging.
    """
    tool_name = input_data.get("tool_name", "")
    error = input_data.get("error", "")
    is_interrupt = input_data.get("is_interrupt", False)

    # Log failure for audit trail (if state_dir provided)
    state_dir = context.get("state_dir")
    if state_dir:
        _log_tool_failure(state_dir, tool_name, error, is_interrupt)

    # Return empty - agent sees the error and can handle it
    return {}


def _log_tool_failure(
    state_dir: Path,
    tool_name: str,
    error: str,
    is_interrupt: bool,
) -> None:
    """Log tool failure to audit trail."""
    from datetime import datetime, timezone

    audit_file = Path(state_dir) / "audit.jsonl"

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "tool_failure",
        "tool_name": tool_name,
        "error": error[:500],  # Truncate long errors
        "is_interrupt": is_interrupt,
    }

    try:
        with open(audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Don't fail the hook if logging fails


def create_ralph_hooks(
    allowed_paths: Optional[List[str]] = None,
    forbidden_paths: Optional[List[str]] = None,
    allowed_tools: Optional[List[str]] = None,
    artifact_tracker: Optional[List[str]] = None,
    state_dir: Optional[Path] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Create hook configuration for ClaudeAgentOptions.

    Args:
        allowed_paths: Paths the agent can write to
        forbidden_paths: Paths the agent cannot access
        allowed_tools: Tools the agent can use
        artifact_tracker: Mutable list to track created files
        state_dir: Directory for audit logging (optional)

    Returns:
        Hook configuration dict for ClaudeAgentOptions

    Usage:
        options = ClaudeAgentOptions(
            hooks=create_ralph_hooks(
                allowed_paths=["src/"],
                allowed_tools=["Read", "Write", "Edit"],
            ),
            ...
        )
    """
    # Create context that will be passed to hooks
    context = {
        "allowed_paths": allowed_paths or [],
        "forbidden_paths": forbidden_paths or [],
        "allowed_tools": allowed_tools or [],
        "artifact_tracker": artifact_tracker if artifact_tracker is not None else [],
        "state_dir": state_dir,
    }

    # Create bound callbacks with context
    async def bound_pre_tool_use(input_data, tool_use_id, _ctx):
        return await pre_tool_use_hook(input_data, tool_use_id, context)

    async def bound_post_tool_use(input_data, tool_use_id, _ctx):
        return await post_tool_use_hook(input_data, tool_use_id, context)

    async def bound_post_tool_use_failure(input_data, tool_use_id, _ctx):
        return await post_tool_use_failure_hook(input_data, tool_use_id, context)

    async def bound_stop(input_data, tool_use_id, _ctx):
        return await stop_hook(input_data, tool_use_id, context)

    # Return SDK-compatible hook configuration
    # Using HookMatcher objects with proper timeout settings
    return {
        "PreToolUse": [
            HookMatcher(matcher=None, hooks=[bound_pre_tool_use], timeout=60.0),
        ],
        "PostToolUse": [
            HookMatcher(matcher=None, hooks=[bound_post_tool_use], timeout=60.0),
        ],
        "PostToolUseFailure": [
            HookMatcher(matcher=None, hooks=[bound_post_tool_use_failure], timeout=60.0),
        ],
        "Stop": [
            HookMatcher(hooks=[bound_stop]),
        ],
    }
