"""Configuration loader that merges default and project-level configs.

This module provides the core configuration loading and merging functionality
for the Ralph pipeline. It allows projects to customize their tool/MCP
configuration via a ralph.config.json file without modifying the Ralph submodule.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field

from .defaults import FORBIDDEN_TOOLS


@dataclass
class MergedConfig:
    """Merged configuration from defaults and project overrides."""
    tech_stack: str
    tools: List[str]
    mcp_servers: Dict[str, Dict[str, Any]]
    role_tools: Dict[str, List[str]]  # role -> allowed tools
    role_max_turns: Dict[str, int] = field(default_factory=dict)  # role -> max_turns
    build_command: str = ""
    test_command: str = ""
    lint_command: str = ""
    source_patterns: List[str] = field(default_factory=list)
    test_patterns: List[str] = field(default_factory=list)

    def get_tools_for_role(self, role: str) -> List[str]:
        """
        Get the list of allowed tools for a specific role.

        Args:
            role: The role name (e.g., 'implementer', 'verifier')

        Returns:
            List of tool names allowed for the role, filtered to exclude
            forbidden tools.
        """
        role_lower = role.lower()
        allowed = self.role_tools.get(role_lower, [])

        # Filter out forbidden tools
        return [t for t in allowed if t not in FORBIDDEN_TOOLS]

    def get_max_turns_for_role(self, role: str) -> int:
        """
        Get the max_turns limit for a specific role.

        Args:
            role: The role name (e.g., 'implementer', 'verifier')

        Returns:
            Max turns for the role, defaults to 50 if not configured.
        """
        role_lower = role.lower()
        return self.role_max_turns.get(role_lower, 50)

    def get_mcp_tools_for_role(self, role: str) -> List[str]:
        """
        Get MCP tools available for a role based on configured servers.

        Args:
            role: The role name

        Returns:
            List of MCP tool names from all configured servers.
        """
        mcp_tools = []
        for server_config in self.mcp_servers.values():
            mcp_tools.extend(server_config.get("tools", []))
        return mcp_tools


def load_project_config(project_root: Path) -> Optional[Dict[str, Any]]:
    """
    Load ralph.config.json from project root if it exists.

    Args:
        project_root: Path to the project root directory

    Returns:
        Dict containing the parsed config, or None if no config file exists.
    """
    config_path = project_root / "ralph.config.json"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    return None


def _deep_copy_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Create a deep copy of a dict containing dicts, lists, and primitives."""
    result = {}
    for k, v in d.items():
        if isinstance(v, dict):
            result[k] = _deep_copy_dict(v)
        elif isinstance(v, list):
            result[k] = v.copy()
        else:
            result[k] = v
    return result


def merge_configs(
    defaults: Dict[str, Any],
    project: Optional[Dict[str, Any]]
) -> MergedConfig:
    """
    Merge default and project configs.

    Merge rules:
    - mcp_servers: project values APPEND to defaults (by server name)
    - role_overrides.additional_tools: APPEND to role's default tools
    - role_overrides.remove_tools: REMOVE from role's default tools
    - Other fields: project values OVERRIDE defaults

    Args:
        defaults: Default configuration from get_defaults()
        project: Project configuration from ralph.config.json, or None

    Returns:
        MergedConfig with all values properly merged.
    """
    # Start with copies of defaults
    tech_stack = defaults.get("tech_stack", "python")
    tools = defaults.get("tools", []).copy()
    mcp_servers = _deep_copy_dict(defaults.get("mcp_servers", {}))
    role_tools = {k: list(v) for k, v in defaults.get("role_tools", {}).items()}
    role_max_turns = dict(defaults.get("role_max_turns", {}))
    build_command = defaults.get("build_command", "")
    test_command = defaults.get("test_command", "")
    lint_command = defaults.get("lint_command", "")
    source_patterns = defaults.get("source_patterns", []).copy()
    test_patterns = defaults.get("test_patterns", []).copy()

    if project is None:
        return MergedConfig(
            tech_stack=tech_stack,
            tools=tools,
            mcp_servers=mcp_servers,
            role_tools=role_tools,
            role_max_turns=role_max_turns,
            build_command=build_command,
            test_command=test_command,
            lint_command=lint_command,
            source_patterns=source_patterns,
            test_patterns=test_patterns,
        )

    # Override tech_stack if specified
    if "tech_stack" in project:
        tech_stack = project["tech_stack"]

    # Override commands if specified
    if "build_command" in project:
        build_command = project["build_command"]
    if "test_command" in project:
        test_command = project["test_command"]
    if "lint_command" in project:
        lint_command = project["lint_command"]

    # Override patterns if specified
    if "source_patterns" in project:
        source_patterns = project["source_patterns"].copy()
    if "test_patterns" in project:
        test_patterns = project["test_patterns"].copy()

    # APPEND MCP servers from project config
    project_mcp = project.get("mcp_servers", {})
    for server_name, server_config in project_mcp.items():
        if server_name in mcp_servers:
            # Server exists in defaults - merge tools list, override other fields
            existing = mcp_servers[server_name]
            merged_server = _deep_copy_dict(server_config)

            # Merge tools list (append project tools to default tools)
            default_tools = set(existing.get("tools", []))
            project_tools = server_config.get("tools", [])
            merged_tools = list(default_tools | set(project_tools))
            if merged_tools:
                merged_server["tools"] = merged_tools

            mcp_servers[server_name] = merged_server
        else:
            # New server from project config
            mcp_servers[server_name] = _deep_copy_dict(server_config)

    # Process role overrides
    role_overrides = project.get("role_overrides", {})
    for role_name, overrides in role_overrides.items():
        role_lower = role_name.lower()

        # Get current tools for role (or empty list if new role)
        current_tools = set(role_tools.get(role_lower, []))

        # APPEND additional_tools
        additional = overrides.get("additional_tools", [])
        current_tools.update(additional)

        # REMOVE remove_tools
        remove = overrides.get("remove_tools", [])
        current_tools -= set(remove)

        # Update role_tools
        role_tools[role_lower] = list(current_tools)

        # OVERRIDE max_turns if specified
        if "max_turns" in overrides:
            role_max_turns[role_lower] = overrides["max_turns"]

    # Override tools list if explicitly specified
    if "tools" in project:
        tools = project["tools"].copy()

    return MergedConfig(
        tech_stack=tech_stack,
        tools=tools,
        mcp_servers=mcp_servers,
        role_tools=role_tools,
        role_max_turns=role_max_turns,
        build_command=build_command,
        test_command=test_command,
        lint_command=lint_command,
        source_patterns=source_patterns,
        test_patterns=test_patterns,
    )


def get_merged_config(project_root: Path, tech_stack: str) -> MergedConfig:
    """
    Get fully merged configuration for a project.

    This is the main entry point for getting configuration. It loads defaults
    for the specified tech stack, then merges any project-level overrides
    from ralph.config.json.

    Args:
        project_root: Path to the project root directory
        tech_stack: The tech stack name (e.g., 'python', 'unity')

    Returns:
        MergedConfig with all configuration values.
    """
    from .defaults import get_defaults

    defaults = get_defaults(tech_stack)
    project = load_project_config(project_root)
    return merge_configs(defaults, project)


def validate_config(config: Dict[str, Any]) -> List[str]:
    """
    Validate a project configuration.

    Args:
        config: The configuration dict to validate

    Returns:
        List of validation error messages (empty if valid).
    """
    errors = []

    # Check for unknown top-level keys
    known_keys = {
        "name", "tech_stack", "mcp_servers", "role_overrides",
        "tools", "build_command", "test_command", "lint_command",
        "source_patterns", "test_patterns", "specs_dir", "source_dir",
        "max_iterations",
    }
    for key in config.keys():
        if key not in known_keys:
            errors.append(f"Unknown configuration key: '{key}'")

    # Validate mcp_servers structure
    mcp_servers = config.get("mcp_servers", {})
    if not isinstance(mcp_servers, dict):
        errors.append("'mcp_servers' must be an object/dict")
    else:
        for server_name, server_config in mcp_servers.items():
            if not isinstance(server_config, dict):
                errors.append(f"MCP server '{server_name}' config must be an object")
                continue

            # Check required fields
            if "command" not in server_config and "type" not in server_config:
                errors.append(
                    f"MCP server '{server_name}' must have 'command' or 'type'"
                )

    # Validate role_overrides structure
    role_overrides = config.get("role_overrides", {})
    if not isinstance(role_overrides, dict):
        errors.append("'role_overrides' must be an object/dict")
    else:
        for role_name, overrides in role_overrides.items():
            if not isinstance(overrides, dict):
                errors.append(f"Role override for '{role_name}' must be an object")
                continue

            # Check for valid override keys
            valid_override_keys = {"additional_tools", "remove_tools", "max_turns"}
            for key in overrides.keys():
                if key not in valid_override_keys:
                    errors.append(
                        f"Unknown key '{key}' in role_overrides.{role_name}. "
                        f"Valid keys: {valid_override_keys}"
                    )

            # Validate tool lists
            for list_key in ["additional_tools", "remove_tools"]:
                if list_key in overrides:
                    if not isinstance(overrides[list_key], list):
                        errors.append(
                            f"role_overrides.{role_name}.{list_key} must be a list"
                        )

            # Validate max_turns
            if "max_turns" in overrides:
                max_turns_val = overrides["max_turns"]
                if not isinstance(max_turns_val, int) or max_turns_val <= 0:
                    errors.append(
                        f"role_overrides.{role_name}.max_turns must be a positive integer"
                    )

    return errors
