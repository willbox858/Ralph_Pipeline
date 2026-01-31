"""Default configurations for Ralph pipeline.

This module contains the default configurations extracted from registry.py.
These serve as the base that project-level configs can extend or override.
"""

from typing import Any, Dict, List, Set


# =============================================================================
# DEFAULT MCP SERVER CONFIGURATIONS
# =============================================================================

UNITY_MCP_SERVER = {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@anthropic/mcp-unity"],
    "env": {"UNITY_PROJECT_PATH": "."},
    "tools": [
        "unity_run_tests",
        "unity_get_logs",
        "unity_compile",
        "unity_open_scene",
        "unity_get_hierarchy",
        "unity_get_components",
        "unity_execute_menu_item",
    ],
}

GODOT_MCP_SERVER = {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@anthropic/mcp-godot"],
    "tools": [
        "godot_run_scene",
        "godot_get_nodes",
        "godot_run_tests",
        "godot_get_script",
    ],
}


# =============================================================================
# DEFAULT TECH STACK CONFIGURATIONS
# =============================================================================

TECH_STACK_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "python": {
        "description": "Python projects with pytest",
        "mcp_servers": {},
        "builtin_tools": ["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
        "build_command": "python -m py_compile {file}",
        "test_command": "pytest {test_dir} -v",
        "lint_command": "ruff check {source_dir}",
        "source_patterns": ["*.py"],
        "test_patterns": ["test_*.py", "*_test.py"],
    },
    "csharp": {
        "description": "C# / .NET projects",
        "mcp_servers": {},
        "builtin_tools": ["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
        "build_command": "dotnet build",
        "test_command": "dotnet test",
        "lint_command": "dotnet format --verify-no-changes",
        "source_patterns": ["*.cs"],
        "test_patterns": ["*Tests.cs", "*Test.cs"],
    },
    "typescript": {
        "description": "TypeScript / Node.js projects",
        "mcp_servers": {},
        "builtin_tools": ["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
        "build_command": "npm run build",
        "test_command": "npm test",
        "lint_command": "npm run lint",
        "source_patterns": ["*.ts", "*.tsx"],
        "test_patterns": ["*.test.ts", "*.spec.ts"],
    },
    "unity": {
        "description": "Unity game projects (C#)",
        "mcp_servers": {
            "unity": UNITY_MCP_SERVER,
        },
        "builtin_tools": ["Read", "Write", "Edit", "Grep", "Glob"],
        "build_command": "",  # Unity compiles via MCP
        "test_command": "",   # Unity tests via MCP
        "lint_command": "",
        "source_patterns": ["*.cs"],
        "test_patterns": ["*Tests.cs"],
    },
    "godot": {
        "description": "Godot game projects (GDScript/C#)",
        "mcp_servers": {
            "godot": GODOT_MCP_SERVER,
        },
        "builtin_tools": ["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
        "build_command": "",
        "test_command": "",
        "lint_command": "",
        "source_patterns": ["*.gd", "*.cs"],
        "test_patterns": ["test_*.gd"],
    },
    "rust": {
        "description": "Rust projects with Cargo",
        "mcp_servers": {},
        "builtin_tools": ["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
        "build_command": "cargo build",
        "test_command": "cargo test",
        "lint_command": "cargo clippy",
        "source_patterns": ["*.rs"],
        "test_patterns": ["*_test.rs"],
    },
    "go": {
        "description": "Go projects",
        "mcp_servers": {},
        "builtin_tools": ["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
        "build_command": "go build ./...",
        "test_command": "go test ./...",
        "lint_command": "golangci-lint run",
        "source_patterns": ["*.go"],
        "test_patterns": ["*_test.go"],
    },
}

# Aliases for tech stacks
TECH_STACK_ALIASES: Dict[str, str] = {
    "c#": "csharp",
    "ts": "typescript",
    "golang": "go",
}


# =============================================================================
# DEFAULT ROLE TOOL CONFIGURATIONS
# =============================================================================

DEFAULT_ROLE_TOOLS: Dict[str, List[str]] = {
    # Architecture team - read-only
    "spec_writer": ["Read", "Grep", "Glob"],
    "proposer": ["Read", "Grep", "Glob"],
    "critic": ["Read", "Grep", "Glob"],

    # Implementation team - full access
    "implementer": ["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
    "verifier": ["Read", "Bash", "Grep", "Glob"],  # Can run tests but not edit

    # Maintenance team
    "analyzer": ["Read", "Grep", "Glob"],
    "troubleshooter": ["Read", "Bash", "Grep", "Glob"],
    "editor": ["Read", "Write", "Edit", "Grep", "Glob"],
}

# Default max_turns per role - SDK conversation turns per invocation
# Implementers need more turns for complex implementations
DEFAULT_ROLE_MAX_TURNS: Dict[str, int] = {
    "spec_writer": 30,
    "proposer": 40,
    "critic": 25,
    "implementer": 75,
    "verifier": 40,
    "analyzer": 30,
    "troubleshooter": 50,
    "editor": 50,
}

# Tools that are always forbidden regardless of configuration
FORBIDDEN_TOOLS: Set[str] = {
    "Task",  # Don't let agents spawn sub-agents
}


# =============================================================================
# PUBLIC API
# =============================================================================

def get_defaults(tech_stack: str) -> Dict[str, Any]:
    """
    Get default configuration for a tech stack.

    Args:
        tech_stack: The tech stack name (e.g., 'python', 'unity', 'typescript')

    Returns:
        Dict containing the default configuration for the tech stack.
        Falls back to 'python' defaults if the tech stack is unknown.
    """
    # Resolve aliases
    normalized = tech_stack.lower()
    if normalized in TECH_STACK_ALIASES:
        normalized = TECH_STACK_ALIASES[normalized]

    # Get tech stack config or fall back to python
    tech_config = TECH_STACK_DEFAULTS.get(normalized, TECH_STACK_DEFAULTS["python"])

    return {
        "tech_stack": normalized,
        "tools": tech_config["builtin_tools"].copy(),
        "mcp_servers": {k: dict(v) for k, v in tech_config["mcp_servers"].items()},
        "role_tools": {k: list(v) for k, v in DEFAULT_ROLE_TOOLS.items()},
        "role_max_turns": dict(DEFAULT_ROLE_MAX_TURNS),
        "build_command": tech_config["build_command"],
        "test_command": tech_config["test_command"],
        "lint_command": tech_config["lint_command"],
        "source_patterns": tech_config["source_patterns"].copy(),
        "test_patterns": tech_config["test_patterns"].copy(),
    }


def get_available_tech_stacks() -> List[str]:
    """Get list of available tech stack names (including aliases)."""
    stacks = list(TECH_STACK_DEFAULTS.keys())
    stacks.extend(TECH_STACK_ALIASES.keys())
    return sorted(stacks)
