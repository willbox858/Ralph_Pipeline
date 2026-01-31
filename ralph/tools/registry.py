"""
Tool Registry for the Ralph pipeline.

Manages available tools and MCP servers based on tech stack configuration.
This is the key to solving the "Unity tests don't work" problem - each
tech stack defines what tools are available.

The registry now integrates with the config system to support project-level
customization via ralph.config.json files.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any
from enum import Enum
import json
from pathlib import Path


class ToolCategory(str, Enum):
    """Categories of tools."""
    FILE_SYSTEM = "file_system"      # Read, Write, Edit
    SEARCH = "search"                # Grep, Glob, Find
    EXECUTION = "execution"          # Bash, Task
    MCP = "mcp"                      # External MCP servers
    COMMUNICATION = "communication"  # Ralph message tools


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server."""
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    tools: List[str] = field(default_factory=list)  # Tools this server provides
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "tools": self.tools,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "MCPServerConfig":
        return cls(
            name=data.get("name", ""),
            command=data.get("command", ""),
            args=data.get("args", []),
            env=data.get("env", {}),
            tools=data.get("tools", []),
        )
    
    def to_mcp_json(self) -> dict:
        """Convert to .mcp.json format."""
        config = {
            "type": "stdio",
            "command": self.command,
            "args": self.args,
        }
        if self.env:
            config["env"] = self.env
        return config


@dataclass
class ToolPreset:
    """
    A preset of tools for a specific tech stack.
    
    Each tech stack defines what MCP tools are needed, solving the
    problem of agents not having access to required tools (like Unity).
    """
    name: str
    description: str
    
    # MCP servers to enable
    mcp_servers: List[MCPServerConfig] = field(default_factory=list)
    
    # Built-in tools to enable (Claude Code tools)
    builtin_tools: List[str] = field(default_factory=list)
    
    # Verification commands
    build_command: str = ""
    test_command: str = ""
    lint_command: str = ""
    
    # File patterns
    source_patterns: List[str] = field(default_factory=list)
    test_patterns: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "mcp_servers": [s.to_dict() for s in self.mcp_servers],
            "builtin_tools": self.builtin_tools,
            "build_command": self.build_command,
            "test_command": self.test_command,
            "lint_command": self.lint_command,
            "source_patterns": self.source_patterns,
            "test_patterns": self.test_patterns,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ToolPreset":
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            mcp_servers=[MCPServerConfig.from_dict(s) for s in data.get("mcp_servers", [])],
            builtin_tools=data.get("builtin_tools", []),
            build_command=data.get("build_command", ""),
            test_command=data.get("test_command", ""),
            lint_command=data.get("lint_command", ""),
            source_patterns=data.get("source_patterns", []),
            test_patterns=data.get("test_patterns", []),
        )


# =============================================================================
# BUILT-IN PRESETS
# =============================================================================

PYTHON_PRESET = ToolPreset(
    name="python",
    description="Python projects with pytest",
    mcp_servers=[],
    builtin_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
    build_command="python -m py_compile {file}",
    test_command="pytest {test_dir} -v",
    lint_command="ruff check {source_dir}",
    source_patterns=["*.py"],
    test_patterns=["test_*.py", "*_test.py"],
)

CSHARP_PRESET = ToolPreset(
    name="csharp",
    description="C# / .NET projects",
    mcp_servers=[],
    builtin_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
    build_command="dotnet build",
    test_command="dotnet test",
    lint_command="dotnet format --verify-no-changes",
    source_patterns=["*.cs"],
    test_patterns=["*Tests.cs", "*Test.cs"],
)

TYPESCRIPT_PRESET = ToolPreset(
    name="typescript",
    description="TypeScript / Node.js projects",
    mcp_servers=[],
    builtin_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
    build_command="npm run build",
    test_command="npm test",
    lint_command="npm run lint",
    source_patterns=["*.ts", "*.tsx"],
    test_patterns=["*.test.ts", "*.spec.ts"],
)

UNITY_PRESET = ToolPreset(
    name="unity",
    description="Unity game projects (C#)",
    mcp_servers=[
        MCPServerConfig(
            name="unity",
            command="npx",
            args=["-y", "@anthropic/mcp-unity"],
            tools=[
                "mcp__unity__run_tests",
                "mcp__unity__get_logs",
                "mcp__unity__compile",
                "mcp__unity__open_scene",
                "mcp__unity__get_hierarchy",
                "mcp__unity__get_components",
                "mcp__unity__execute_menu_item",
            ],
            env={"UNITY_PROJECT_PATH": "."},
        )
    ],
    builtin_tools=["Read", "Write", "Edit", "Grep", "Glob"],
    build_command="",  # Unity compiles via MCP
    test_command="",   # Unity tests via MCP
    lint_command="",
    source_patterns=["*.cs"],
    test_patterns=["*Tests.cs"],
)

GODOT_PRESET = ToolPreset(
    name="godot",
    description="Godot game projects (GDScript/C#)",
    mcp_servers=[
        MCPServerConfig(
            name="godot",
            command="npx",
            args=["-y", "@anthropic/mcp-godot"],
            tools=[
                "mcp__godot__run_scene",
                "mcp__godot__get_nodes",
                "mcp__godot__run_tests",
                "mcp__godot__get_script",
            ],
        )
    ],
    builtin_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
    build_command="",
    test_command="",
    lint_command="",
    source_patterns=["*.gd", "*.cs"],
    test_patterns=["test_*.gd"],
)

RUST_PRESET = ToolPreset(
    name="rust",
    description="Rust projects with Cargo",
    mcp_servers=[],
    builtin_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
    build_command="cargo build",
    test_command="cargo test",
    lint_command="cargo clippy",
    source_patterns=["*.rs"],
    test_patterns=["*_test.rs"],
)

GO_PRESET = ToolPreset(
    name="go",
    description="Go projects",
    mcp_servers=[],
    builtin_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
    build_command="go build ./...",
    test_command="go test ./...",
    lint_command="golangci-lint run",
    source_patterns=["*.go"],
    test_patterns=["*_test.go"],
)

# All built-in presets
BUILTIN_PRESETS: Dict[str, ToolPreset] = {
    "python": PYTHON_PRESET,
    "csharp": CSHARP_PRESET,
    "c#": CSHARP_PRESET,  # Alias
    "typescript": TYPESCRIPT_PRESET,
    "ts": TYPESCRIPT_PRESET,  # Alias
    "unity": UNITY_PRESET,
    "godot": GODOT_PRESET,
    "rust": RUST_PRESET,
    "go": GO_PRESET,
    "golang": GO_PRESET,  # Alias
}


# =============================================================================
# ROLE-BASED TOOL RESTRICTIONS
# =============================================================================

# Tools available to each role
ROLE_TOOL_ALLOWLIST: Dict[str, Set[str]] = {
    # Architecture team - read-only
    "spec_writer": {"Read", "Grep", "Glob"},
    "proposer": {"Read", "Grep", "Glob"},
    "critic": {"Read", "Grep", "Glob"},

    # Implementation team - full access
    "implementer": {"Read", "Write", "Edit", "Bash", "Grep", "Glob"},
    "verifier": {"Read", "Bash", "Grep", "Glob"},  # Can run tests but not edit

    # Maintenance team
    "analyzer": {"Read", "Grep", "Glob"},
    "troubleshooter": {"Read", "Bash", "Grep", "Glob"},
    "editor": {"Read", "Write", "Edit", "Grep", "Glob"},
}

# Tools that are always forbidden
FORBIDDEN_TOOLS: Set[str] = {
    "Task",  # Don't let agents spawn sub-agents
}


# =============================================================================
# TOOL REGISTRY
# =============================================================================

class ToolRegistry:
    """
    Registry of available tools and presets.

    The orchestrator uses this to provision agents with the correct tools.
    Now supports project-level configuration via ralph.config.json.
    """

    def __init__(self, project_root: Optional[Path] = None):
        """
        Initialize the tool registry.

        Args:
            project_root: Optional path to project root for loading config.
                         If provided, ralph.config.json will be loaded.
        """
        self._presets: Dict[str, ToolPreset] = dict(BUILTIN_PRESETS)
        self._custom_mcp_servers: Dict[str, MCPServerConfig] = {}
        self._project_root: Optional[Path] = project_root
        self._merged_config_cache: Dict[str, Any] = {}
    
    def register_preset(self, preset: ToolPreset) -> None:
        """Register a custom tool preset."""
        self._presets[preset.name.lower()] = preset
    
    def register_mcp_server(self, server: MCPServerConfig) -> None:
        """Register a custom MCP server."""
        self._custom_mcp_servers[server.name] = server
    
    def get_preset(self, name: str) -> Optional[ToolPreset]:
        """Get a preset by name (case-insensitive)."""
        return self._presets.get(name.lower())
    
    def get_mcp_server(self, name: str) -> Optional[MCPServerConfig]:
        """Get an MCP server config by name."""
        # Check custom servers first
        if name in self._custom_mcp_servers:
            return self._custom_mcp_servers[name]
        
        # Check presets
        for preset in self._presets.values():
            for server in preset.mcp_servers:
                if server.name == name:
                    return server
        
        return None
    
    def list_presets(self) -> List[str]:
        """List all available preset names."""
        return list(self._presets.keys())

    def set_project_root(self, project_root: Path) -> None:
        """
        Set the project root for configuration loading.

        Args:
            project_root: Path to the project root directory
        """
        self._project_root = project_root
        self._merged_config_cache.clear()  # Clear cache when root changes

    def _get_merged_config(self, tech_stack: str) -> Any:
        """
        Get merged configuration with caching.

        Args:
            tech_stack: The tech stack name

        Returns:
            MergedConfig instance with all configuration merged
        """
        if tech_stack in self._merged_config_cache:
            return self._merged_config_cache[tech_stack]

        if self._project_root is not None:
            from ralph.config import get_merged_config
            config = get_merged_config(self._project_root, tech_stack)
            self._merged_config_cache[tech_stack] = config
            return config

        # No project root - return None to use legacy behavior
        return None

    def get_tools_for_role(
        self,
        role: str,
        tech_stack: str,
        additional_mcp: Optional[List[str]] = None,
        project_root: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Get tool configuration for an agent role.

        Args:
            role: Agent role (proposer, implementer, verifier, etc.)
            tech_stack: Tech stack name (python, csharp, unity, etc.)
            additional_mcp: Additional MCP server names to include
            project_root: Optional project root for config loading (overrides instance setting)

        Returns:
            Dict with allowed_tools, mcp_servers (as dict), and commands
        """
        # Set project root if provided
        if project_root is not None:
            self.set_project_root(project_root)

        # Try to get merged config from the new config system
        merged_config = self._get_merged_config(tech_stack)

        if merged_config is not None:
            # Use new config system
            return self._get_tools_for_role_from_config(
                role, merged_config, additional_mcp
            )

        # Fall back to legacy preset-based behavior
        return self._get_tools_for_role_legacy(role, tech_stack, additional_mcp)

    def _get_tools_for_role_from_config(
        self,
        role: str,
        merged_config: Any,  # MergedConfig
        additional_mcp: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Get tool configuration using the new merged config system.

        Args:
            role: Agent role
            merged_config: MergedConfig instance from config loader
            additional_mcp: Additional MCP server names

        Returns:
            Dict with tool configuration
        """
        # Get tools allowed for this role from merged config
        role_tools = merged_config.get_tools_for_role(role)

        # Start with MCP servers from merged config
        mcp_servers_dict = dict(merged_config.mcp_servers)

        # Add additional MCP servers if specified
        if additional_mcp:
            for name in additional_mcp:
                server = self.get_mcp_server(name)
                if server and server.name not in mcp_servers_dict:
                    mcp_servers_dict[server.name] = {
                        "type": "stdio",
                        "command": server.command,
                        "args": server.args,
                        "tools": server.tools,
                        **({"env": server.env} if server.env else {})
                    }

        # Add Ralph communication tools for all roles
        ralph_tools = [
            "mcp__ralph__get_spec",
            "mcp__ralph__get_sibling_status",
            "mcp__ralph__send_message",
            "mcp__ralph__report_error",
            "mcp__ralph__update_spec",
        ]

        # Add Ralph MCP server
        mcp_servers_dict["ralph"] = {
            "type": "stdio",
            "command": "python",
            "args": ["-m", "ralph.mcp_server"],
            "tools": ralph_tools,
        }

        return {
            "allowed_tools": role_tools,
            "mcp_servers": mcp_servers_dict,
            "ralph_tools": ralph_tools,
            "build_command": merged_config.build_command,
            "test_command": merged_config.test_command,
            "lint_command": merged_config.lint_command,
            "source_patterns": merged_config.source_patterns,
            "test_patterns": merged_config.test_patterns,
            "max_turns": merged_config.get_max_turns_for_role(role),
        }

    def _get_tools_for_role_legacy(
        self,
        role: str,
        tech_stack: str,
        additional_mcp: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Legacy implementation of get_tools_for_role using presets.

        This is used when no project root is configured.

        Args:
            role: Agent role
            tech_stack: Tech stack name
            additional_mcp: Additional MCP server names

        Returns:
            Dict with tool configuration
        """
        # Get preset (fall back to Python if unknown)
        preset = self.get_preset(tech_stack) or self.get_preset("python")

        # Get role allowlist
        role_allowed = ROLE_TOOL_ALLOWLIST.get(role.lower(), set())

        # Filter preset tools by role
        builtin_tools = [
            t for t in preset.builtin_tools
            if t in role_allowed and t not in FORBIDDEN_TOOLS
        ]

        # Start with preset MCP servers
        mcp_servers = list(preset.mcp_servers)

        # Add additional MCP servers
        if additional_mcp:
            for name in additional_mcp:
                server = self.get_mcp_server(name)
                if server and server not in mcp_servers:
                    mcp_servers.append(server)

        # Add Ralph communication tools for all roles
        ralph_tools = [
            "mcp__ralph__get_spec",
            "mcp__ralph__get_sibling_status",
            "mcp__ralph__send_message",
            "mcp__ralph__report_error",
            "mcp__ralph__update_spec",
        ]

        # Ralph MCP server config (will be included in agent invocations)
        ralph_server = MCPServerConfig(
            name="ralph",
            command="python",
            args=["-m", "ralph.mcp_server"],
            tools=ralph_tools,
        )

        # Import defaults for max_turns fallback in legacy mode
        from ralph.config.defaults import DEFAULT_ROLE_MAX_TURNS

        return {
            "allowed_tools": builtin_tools,
            "mcp_servers": {
                s.name: {
                    "type": "stdio",
                    "command": s.command,
                    "args": s.args,
                    "tools": s.tools,
                    **({"env": s.env} if s.env else {})
                }
                for s in [*mcp_servers, ralph_server]
            },
            "ralph_tools": ralph_tools,
            "build_command": preset.build_command,
            "test_command": preset.test_command,
            "lint_command": preset.lint_command,
            "source_patterns": preset.source_patterns,
            "test_patterns": preset.test_patterns,
            "max_turns": DEFAULT_ROLE_MAX_TURNS.get(role.lower(), 50),
        }
    
    def generate_mcp_json(
        self,
        tech_stack: str,
        additional_mcp: Optional[List[str]] = None,
        include_ralph: bool = True,
    ) -> Dict[str, any]:
        """
        Generate .mcp.json content for a project.
        
        Args:
            tech_stack: Tech stack name
            additional_mcp: Additional MCP servers
            include_ralph: Whether to include Ralph MCP server
            
        Returns:
            Dict suitable for writing to .mcp.json
        """
        preset = self.get_preset(tech_stack) or self.get_preset("python")
        
        mcp_json = {"mcpServers": {}}
        
        # Add preset servers
        for server in preset.mcp_servers:
            mcp_json["mcpServers"][server.name] = server.to_mcp_json()
        
        # Add additional servers
        if additional_mcp:
            for name in additional_mcp:
                server = self.get_mcp_server(name)
                if server:
                    mcp_json["mcpServers"][server.name] = server.to_mcp_json()
        
        # Add Ralph server
        if include_ralph:
            mcp_json["mcpServers"]["ralph"] = {
                "type": "stdio",
                "command": "python",
                "args": ["-m", "ralph.mcp_server"],
            }
        
        return mcp_json
    
    def load_project_config(self, config_path: Path) -> None:
        """
        Load custom presets and MCP servers from a project config file.
        
        Args:
            config_path: Path to ralph.config.json
        """
        if not config_path.exists():
            return
        
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        # Load custom MCP servers
        for server_data in config.get("mcp_servers", []):
            server = MCPServerConfig.from_dict(server_data)
            self.register_mcp_server(server)
        
        # Load custom preset if defined
        if "preset" in config:
            preset = ToolPreset.from_dict(config["preset"])
            self.register_preset(preset)


# =============================================================================
# SINGLETON
# =============================================================================

_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """Get the global tool registry singleton."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def reset_registry() -> None:
    """Reset the registry (for testing)."""
    global _registry
    _registry = None
