"""
Ralph Hook Enforcement Module

This module provides hook callbacks for the Claude Agent SDK that enforce
tool restrictions based on agent configurations.

Usage with Agent SDK:
    from hooks import create_enforcement_hooks

    hooks = create_enforcement_hooks(agent_config)
    options = ClaudeAgentOptions(
        hooks=hooks,
        ...
    )
"""

import json
import re
from pathlib import Path
from typing import Optional


def load_agent_config(agent_name: str) -> dict:
    """Load agent configuration from JSON file."""
    config_dir = Path(__file__).parent.parent / "agents" / "configs"
    config_path = config_dir / f"{agent_name}.json"

    if not config_path.exists():
        raise FileNotFoundError(f"Agent config not found: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def is_path_allowed(file_path: str, config: dict) -> tuple[bool, str]:
    """
    Check if a file path is allowed for this agent.

    Supports:
    - Path prefixes (e.g., "src/", "Specs/")
    - Bare filenames (e.g., "research.json") - matches anywhere in path
    - Case-insensitive matching on Windows

    Returns:
        (allowed, reason)
    """
    import platform

    # Normalize path
    file_path = file_path.replace('\\', '/')

    # Case-insensitive on Windows
    if platform.system() == 'Windows':
        file_path_check = file_path.lower()
        normalize = lambda p: p.replace('\\', '/').lower()
    else:
        file_path_check = file_path
        normalize = lambda p: p.replace('\\', '/')

    # Check forbidden paths first (deny takes precedence)
    forbidden_paths = config.get('forbidden_paths', [])
    for forbidden in forbidden_paths:
        forbidden_norm = normalize(forbidden)
        if file_path_check.startswith(forbidden_norm) or forbidden_norm in file_path_check:
            return False, f"Path '{file_path}' matches forbidden pattern '{forbidden}'"

    # Check allowed paths (if specified, path must match one)
    allowed_paths = config.get('allowed_paths', [])
    if allowed_paths:
        for allowed in allowed_paths:
            allowed_norm = normalize(allowed)
            # Check if it's a prefix (contains /)
            if '/' in allowed:
                if file_path_check.startswith(allowed_norm):
                    return True, "Path matches allowed prefix"
            else:
                # Bare filename - check if path ends with it or contains it as a filename
                if file_path_check.endswith('/' + allowed_norm) or file_path_check == allowed_norm:
                    return True, "Path matches allowed filename"
                # Also check if filename appears as a component
                if '/' + allowed_norm in file_path_check or file_path_check.endswith(allowed_norm):
                    return True, "Path matches allowed filename pattern"
        return False, f"Path '{file_path}' not in allowed paths: {allowed_paths}"

    # No path restrictions specified
    return True, "No path restrictions"


def format_allowed_tools(config: dict) -> str:
    """Format allowed tools list for error messages."""
    allowed = config.get('allowed_tools', [])
    if not allowed:
        return "No tools configured"
    return ', '.join(allowed)


def format_allowed_paths(config: dict) -> str:
    """Format allowed paths list for error messages."""
    allowed = config.get('allowed_paths', [])
    if not allowed:
        return "any path"
    return ', '.join(allowed)


def create_tool_enforcement_hook(config: dict):
    """
    Create a PreToolUse hook that enforces tool restrictions.

    This hook:
    1. Blocks forbidden tools
    2. Validates allowed tools
    3. Checks path restrictions for Edit/Write

    Error messages include what tools/paths ARE allowed to help recovery.
    """
    async def enforce_tools(input_data: dict, tool_use_id: Optional[str], context) -> dict:
        if input_data.get('hook_event_name') != 'PreToolUse':
            return {}

        tool_name = input_data.get('tool_name', '')
        tool_input = input_data.get('tool_input', {})
        agent_name = config.get('name', 'unknown')
        allowed_tools_str = format_allowed_tools(config)

        # Check forbidden tools
        forbidden_tools = config.get('forbidden_tools', [])
        if tool_name in forbidden_tools:
            return {
                'hookSpecificOutput': {
                    'hookEventName': input_data['hook_event_name'],
                    'permissionDecision': 'deny',
                    'permissionDecisionReason': (
                        f"BLOCKED: Tool '{tool_name}' is forbidden for {agent_name} agent. "
                        f"Available tools: [{allowed_tools_str}]"
                    )
                }
            }

        # Check allowed tools
        allowed_tools = config.get('allowed_tools', [])
        # Don't block MCP tools (they're handled separately)
        if allowed_tools and not tool_name.startswith('mcp__'):
            if tool_name not in allowed_tools:
                return {
                    'hookSpecificOutput': {
                        'hookEventName': input_data['hook_event_name'],
                        'permissionDecision': 'deny',
                        'permissionDecisionReason': (
                            f"BLOCKED: Tool '{tool_name}' is not available for {agent_name} agent. "
                            f"Available tools: [{allowed_tools_str}]"
                        )
                    }
                }

        # Check path restrictions for file operations
        if tool_name in ['Edit', 'Write', 'NotebookEdit']:
            file_path = tool_input.get('file_path', '')
            if file_path:
                allowed, reason = is_path_allowed(file_path, config)
                if not allowed:
                    allowed_paths_str = format_allowed_paths(config)
                    return {
                        'hookSpecificOutput': {
                            'hookEventName': input_data['hook_event_name'],
                            'permissionDecision': 'deny',
                            'permissionDecisionReason': (
                                f"BLOCKED: {reason} "
                                f"Allowed paths for {agent_name}: [{allowed_paths_str}]"
                            )
                        }
                    }

        # Tool is allowed
        return {}

    return enforce_tools


def create_mode_enforcement_hook(config: dict):
    """
    Create a hook that enforces mode restrictions.

    Modes:
    - read_only: No Edit, Write, NotebookEdit
    - read_write: Limited Edit/Write based on allowed_paths
    - implement: Full Edit/Write within allowed_paths
    - verify: Read-only plus test execution
    """
    async def enforce_mode(input_data: dict, tool_use_id: Optional[str], context) -> dict:
        if input_data.get('hook_event_name') != 'PreToolUse':
            return {}

        mode = config.get('mode', 'read_only')
        tool_name = input_data.get('tool_name', '')
        agent_name = config.get('name', 'unknown')
        allowed_tools_str = format_allowed_tools(config)

        # Read-only mode blocks all write operations
        if mode == 'read_only':
            write_tools = ['Edit', 'Write', 'NotebookEdit']
            if tool_name in write_tools:
                return {
                    'hookSpecificOutput': {
                        'hookEventName': input_data['hook_event_name'],
                        'permissionDecision': 'deny',
                        'permissionDecisionReason': (
                            f"BLOCKED: {agent_name} agent is in READ_ONLY mode - cannot use '{tool_name}'. "
                            f"This agent can only read/explore, not modify files. "
                            f"Available tools: [{allowed_tools_str}]"
                        )
                    }
                }

        return {}

    return enforce_mode


def create_audit_hook(config: dict, log_func=None):
    """
    Create a PostToolUse hook that logs all tool calls for auditing.
    """
    async def audit_tool_call(input_data: dict, tool_use_id: Optional[str], context) -> dict:
        if input_data.get('hook_event_name') != 'PostToolUse':
            return {}

        tool_name = input_data.get('tool_name', '')
        tool_input = input_data.get('tool_input', {})
        agent_name = config.get('name', 'unknown')

        # Log the call
        if log_func:
            log_func(f"[AUDIT] {agent_name}: {tool_name}({json.dumps(tool_input)[:100]}...)")

        return {}

    return audit_tool_call


def create_enforcement_hooks(config: dict, log_func=None) -> dict:
    """
    Create all enforcement hooks for an agent configuration.

    Returns a hooks dict suitable for ClaudeAgentOptions.

    Usage:
        config = load_agent_config('researcher')
        hooks = create_enforcement_hooks(config)
        options = ClaudeAgentOptions(hooks=hooks, ...)
    """
    try:
        from claude_agent_sdk import HookMatcher
    except ImportError:
        # Return empty hooks if SDK not available
        return {}

    tool_hook = create_tool_enforcement_hook(config)
    mode_hook = create_mode_enforcement_hook(config)
    audit_hook = create_audit_hook(config, log_func)

    return {
        'PreToolUse': [
            # Mode enforcement runs first (strictest)
            HookMatcher(hooks=[mode_hook]),
            # Then tool enforcement
            HookMatcher(hooks=[tool_hook]),
        ],
        'PostToolUse': [
            # Audit all tool calls
            HookMatcher(hooks=[audit_hook]),
        ]
    }


# ============================================================================
# User-Facing Claude Hooks
# ============================================================================

# Tools the user-facing Claude can use
USER_FACING_ALLOWED_TOOLS = [
    'Read',
    'Grep',
    'Glob',
    'Task',
    'AskUserQuestion',
    'Skill',
]

# Tools the user-facing Claude can use for spec files only
USER_FACING_SPEC_TOOLS = ['Edit', 'Write']

# Paths the user-facing Claude can edit
USER_FACING_ALLOWED_PATHS = ['Specs/']

# Paths the user-facing Claude cannot edit
USER_FACING_FORBIDDEN_PATHS = [
    'src/',
    'Assets/Scripts/',
    '.claude/',
    '.git/',
    'node_modules/',
]


async def user_facing_tool_hook(input_data: dict, tool_use_id: Optional[str], context) -> dict:
    """
    Hook for user-facing Claude that restricts tools to orchestration only.

    User-facing Claude can:
    - Read, Grep, Glob (exploration)
    - Task (spawn agents)
    - AskUserQuestion (interact with user)
    - Skill (run slash commands)
    - Edit/Write ONLY in Specs/ directory
    - Bash ONLY for orchestrator.py, check-pipeline-status.py
    """
    if input_data.get('hook_event_name') != 'PreToolUse':
        return {}

    tool_name = input_data.get('tool_name', '')
    tool_input = input_data.get('tool_input', {})

    # Format available tools for error messages
    all_allowed = USER_FACING_ALLOWED_TOOLS + USER_FACING_SPEC_TOOLS + ['Bash (limited)']
    allowed_str = ', '.join(all_allowed)

    # Always allow these tools
    if tool_name in USER_FACING_ALLOWED_TOOLS:
        return {}

    # Edit/Write only for Specs/
    if tool_name in USER_FACING_SPEC_TOOLS:
        file_path = tool_input.get('file_path', '').replace('\\', '/')

        # Check forbidden first
        for forbidden in USER_FACING_FORBIDDEN_PATHS:
            if forbidden in file_path:
                return {
                    'hookSpecificOutput': {
                        'hookEventName': input_data['hook_event_name'],
                        'permissionDecision': 'deny',
                        'permissionDecisionReason': (
                            f"BLOCKED: User-facing Claude cannot edit files in '{forbidden}'. "
                            f"Delegate implementation to agents using /ralph. "
                            f"You can only edit files in: [{', '.join(USER_FACING_ALLOWED_PATHS)}]"
                        )
                    }
                }

        # Check allowed
        allowed = any(file_path.startswith(p) or p in file_path for p in USER_FACING_ALLOWED_PATHS)
        if not allowed:
            return {
                'hookSpecificOutput': {
                    'hookEventName': input_data['hook_event_name'],
                    'permissionDecision': 'deny',
                    'permissionDecisionReason': (
                        f"BLOCKED: User-facing Claude can only edit spec files. "
                        f"Allowed paths: [{', '.join(USER_FACING_ALLOWED_PATHS)}]. "
                        f"For source code changes, delegate to agents using /ralph."
                    )
                }
            }

        return {}

    # Bash only for specific scripts
    if tool_name == 'Bash':
        command = tool_input.get('command', '')

        # Allowed bash patterns
        allowed_patterns = [
            r'python.*orchestrator\.py',
            r'python.*check-pipeline-status\.py',
            r'python.*check-status\.py',
            r'git\s+(status|log|diff|branch)',
            r'ls\s',
            r'dir\s',
            r'cd\s',
            r'pwd',
        ]

        for pattern in allowed_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return {}

        return {
            'hookSpecificOutput': {
                'hookEventName': input_data['hook_event_name'],
                'permissionDecision': 'deny',
                'permissionDecisionReason': (
                    f"BLOCKED: User-facing Claude has limited Bash access. "
                    f"Allowed commands: orchestrator.py, check-pipeline-status.py, git status/log/diff/branch, ls, pwd. "
                    f"For other shell operations, delegate to agents."
                )
            }
        }

    # Block everything else
    return {
        'hookSpecificOutput': {
            'hookEventName': input_data['hook_event_name'],
            'permissionDecision': 'deny',
            'permissionDecisionReason': (
                f"BLOCKED: Tool '{tool_name}' is not available for user-facing Claude. "
                f"Available tools: [{allowed_str}]. "
                f"For implementation tasks, delegate to agents using /ralph."
            )
        }
    }


def create_user_facing_hooks() -> dict:
    """
    Create hooks for user-facing Claude.

    These hooks enforce that user-facing Claude:
    1. Cannot write source code directly
    2. Can only edit specs
    3. Can only run orchestrator scripts
    """
    try:
        from claude_agent_sdk import HookMatcher
    except ImportError:
        return {}

    return {
        'PreToolUse': [
            HookMatcher(hooks=[user_facing_tool_hook])
        ]
    }
