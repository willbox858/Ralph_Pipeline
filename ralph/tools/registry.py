"""
Tool Registry for the Ralph pipeline.

Manages available tools and MCP servers based on tech stack configuration.
This is the key to solving the "Unity tests don't work" problem - each
tech stack defines what tools are available.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
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
    builtin_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob", "LS"],
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
    builtin_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob", "LS"],
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
    builtin_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob", "LS"],
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
                "unity_run_tests",
                "unity_get_logs",
                "unity_compile",
                "unity_open_scene",
                "unity_get_hierarchy",
                "unity_get_components",
                "unity_execute_menu_item",
            ],
            env={"UNITY_PROJECT_PATH": "."},
        )
    ],
    builtin_tools=["Read", "Write", "Edit", "Grep", "Glob", "LS"],
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
                "godot_run_scene",
                "godot_get_nodes",
                "godot_run_tests",
                "godot_get_script",
            ],
        )
    ],
    builtin_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob", "LS"],
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
    builtin_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob", "LS"],
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
    builtin_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob", "LS"],
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
    "spec_writer": {"Read", "Grep", "Glob", "LS"},
    "proposer": {"Read", "Grep", "Glob", "LS"},
    "critic": {"Read", "Grep", "Glob", "LS"},
    
    # Implementation team - full access
    "implementer": {"Read", "Write", "Edit", "Bash", "Grep", "Glob", "LS"},
    "verifier": {"Read", "Bash", "Grep", "Glob", "LS"},  # Can run tests but not edit
    
    # Maintenance team
    "analyzer": {"Read", "Grep", "Glob", "LS"},
    "troubleshooter": {"Read", "Bash", "Grep", "Glob", "LS"},
    "editor": {"Read", "Write", "Edit", "Grep", "Glob", "LS"},
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
    """
    
    def __init__(self):
        self._presets: Dict[str, ToolPreset] = dict(BUILTIN_PRESETS)
        self._custom_mcp_servers: Dict[str, MCPServerConfig] = {}
    
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
    
    def get_tools_for_role(
        self,
        role: str,
        tech_stack: str,
        additional_mcp: Optional[List[str]] = None,
    ) -> Dict[str, any]:
        """
        Get tool configuration for an agent role.
        
        Args:
            role: Agent role (proposer, implementer, verifier, etc.)
            tech_stack: Tech stack name (python, csharp, unity, etc.)
            additional_mcp: Additional MCP server names to include
            
        Returns:
            Dict with builtin_tools, mcp_servers, and commands
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
        # These are provided by the Ralph MCP server
        ralph_tools = [
            "ralph_send_message",
            "ralph_get_spec",
            "ralph_get_sibling_status",
            "ralph_report_error",
        ]
        
        return {
            "builtin_tools": builtin_tools,
            "mcp_servers": mcp_servers,
            "ralph_tools": ralph_tools,
            "build_command": preset.build_command,
            "test_command": preset.test_command,
            "lint_command": preset.lint_command,
            "source_patterns": preset.source_patterns,
            "test_patterns": preset.test_patterns,
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
