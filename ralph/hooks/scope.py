"""
Scope enforcement for the Ralph pipeline.

Determines whether an agent is allowed to access a given path.
"""

from typing import List, Tuple, Optional
from pathlib import Path
import os
import json
import fnmatch


def normalize_path(path: str) -> str:
    """Normalize a path for comparison."""
    # Convert backslashes to forward slashes
    path = path.replace("\\", "/")
    # Remove leading ./
    if path.startswith("./"):
        path = path[2:]
    # Remove trailing slash for files
    if path.endswith("/") and not path.endswith("//"):
        path = path[:-1]
    return path


def is_path_allowed(
    file_path: str,
    allowed_paths: List[str],
    forbidden_paths: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """
    Check if a file path is allowed.
    
    Args:
        file_path: The path being accessed
        allowed_paths: List of allowed path prefixes or patterns
        forbidden_paths: List of forbidden path prefixes or patterns
        
    Returns:
        (allowed: bool, reason: str)
    """
    file_path = normalize_path(file_path)
    
    # Check forbidden paths first (deny takes precedence)
    if forbidden_paths:
        for forbidden in forbidden_paths:
            forbidden = normalize_path(forbidden)
            
            # Check prefix match
            if file_path.startswith(forbidden):
                return False, f"Path matches forbidden prefix: {forbidden}"
            
            # Check glob pattern match
            if fnmatch.fnmatch(file_path, forbidden):
                return False, f"Path matches forbidden pattern: {forbidden}"
    
    # If no allowed paths specified, everything is allowed
    if not allowed_paths:
        return True, "No path restrictions"
    
    # Check if path matches any allowed path
    for allowed in allowed_paths:
        allowed = normalize_path(allowed)
        
        # Check prefix match (directories end with /)
        if allowed.endswith("/"):
            if file_path.startswith(allowed[:-1]):
                return True, f"Path matches allowed prefix: {allowed}"
        
        # Check exact match
        if file_path == allowed:
            return True, f"Path matches exactly: {allowed}"
        
        # Check glob pattern match
        if fnmatch.fnmatch(file_path, allowed):
            return True, f"Path matches allowed pattern: {allowed}"
        
        # Check if path is under allowed directory
        if file_path.startswith(allowed + "/"):
            return True, f"Path is under allowed directory: {allowed}"
    
    return False, f"Path not in allowed list: {allowed_paths}"


def is_tool_allowed(
    tool_name: str,
    allowed_tools: List[str],
    forbidden_tools: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """
    Check if a tool is allowed.
    
    Args:
        tool_name: The tool being used
        allowed_tools: List of allowed tool names
        forbidden_tools: List of forbidden tool names
        
    Returns:
        (allowed: bool, reason: str)
    """
    # Check forbidden first
    if forbidden_tools and tool_name in forbidden_tools:
        return False, f"Tool is forbidden: {tool_name}"
    
    # If no allowed list, everything is allowed
    if not allowed_tools:
        return True, "No tool restrictions"
    
    # Check if tool is in allowed list
    if tool_name in allowed_tools:
        return True, f"Tool is allowed: {tool_name}"
    
    # Allow MCP tools that start with allowed prefixes
    if tool_name.startswith("mcp__ralph_"):
        return True, "Ralph MCP tools are always allowed"
    
    return False, f"Tool not in allowed list: {allowed_tools}"


def get_agent_context_from_env() -> Optional[dict]:
    """
    Load agent context from environment.
    
    Hooks use this to get the context set by the orchestrator.
    """
    # Try context file first
    context_file = os.environ.get("RALPH_CONTEXT_FILE")
    if context_file and Path(context_file).exists():
        try:
            return json.loads(Path(context_file).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            pass
    
    # Try inline JSON
    context_json = os.environ.get("RALPH_AGENT_CONTEXT")
    if context_json:
        try:
            return json.loads(context_json)
        except json.JSONDecodeError:
            pass
    
    return None


def get_allowed_paths_from_env() -> List[str]:
    """Get allowed paths from environment."""
    context = get_agent_context_from_env()
    if context:
        return context.get("allowed_paths", [])
    return []


def get_allowed_tools_from_env() -> List[str]:
    """Get allowed tools from environment."""
    context = get_agent_context_from_env()
    if context:
        return context.get("allowed_tools", [])
    return []
