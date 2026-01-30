#!/usr/bin/env python3
"""
Verifier Configuration - Per-project verification settings.
Location: lib/verifier_config.py

Projects can define a `ralph.verifier.json` file in their root to configure
how Ralph verifies specs (test commands, Unity MCP usage, etc.).
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


CONFIG_FILENAME = "ralph.verifier.json"


@dataclass
class UnityConfig:
    """Unity-specific verification settings."""
    test_mode: str = "EditMode"  # EditMode, PlayMode, Both
    assembly_names: list[str] = field(default_factory=list)


@dataclass
class CompilationConfig:
    """Compilation verification settings."""
    command: Optional[str] = None
    skip: bool = False


@dataclass
class FileVerificationConfig:
    """File existence verification settings."""
    required_extensions: list[str] = field(default_factory=list)
    skip: bool = False


@dataclass
class VerifierConfig:
    """Per-project verifier configuration."""
    project_type: str = "unknown"  # unity, python, typescript, csharp, go, rust, java, custom
    test_command: Optional[str] = None
    test_method: str = "cli"  # cli, unity_mcp, custom_mcp, manual
    unity: UnityConfig = field(default_factory=UnityConfig)
    compilation: CompilationConfig = field(default_factory=CompilationConfig)
    file_verification: FileVerificationConfig = field(default_factory=FileVerificationConfig)


# Default test commands by project type
DEFAULT_TEST_COMMANDS = {
    "python": "pytest",
    "typescript": "npm test",
    "csharp": "dotnet test",
    "go": "go test ./...",
    "rust": "cargo test",
    "java": "mvn test",
    "unity": None,  # Uses Unity MCP, not CLI
}


def find_project_root(start_path: Path) -> Optional[Path]:
    """Find project root by looking for .claude or .git directory."""
    current = start_path.resolve()
    for _ in range(15):  # Max depth
        if (current / ".claude").is_dir() or (current / ".git").is_dir():
            return current
        if current.parent == current:
            break
        current = current.parent
    return None


def load_verifier_config(spec_path: Path) -> VerifierConfig:
    """
    Load verifier configuration for a project.

    Looks for ralph.verifier.json in the project root.
    Falls back to auto-detection if not found.
    """
    project_root = find_project_root(spec_path)
    if not project_root:
        return _auto_detect_config(spec_path)

    config_path = project_root / CONFIG_FILENAME
    if not config_path.exists():
        return _auto_detect_config(spec_path, project_root)

    try:
        data = json.loads(config_path.read_text(encoding='utf-8'))
        return _parse_config(data)
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Warning: Failed to parse {config_path}: {e}")
        return _auto_detect_config(spec_path, project_root)


def _parse_config(data: dict) -> VerifierConfig:
    """Parse config dict into VerifierConfig object."""
    config = VerifierConfig(
        project_type=data.get("project_type", "unknown"),
        test_command=data.get("test_command"),
        test_method=data.get("test_method", "cli"),
    )

    # Unity settings
    unity_data = data.get("unity", {})
    config.unity = UnityConfig(
        test_mode=unity_data.get("test_mode", "EditMode"),
        assembly_names=unity_data.get("assembly_names", []),
    )

    # Compilation settings
    comp_data = data.get("compilation", {})
    config.compilation = CompilationConfig(
        command=comp_data.get("command"),
        skip=comp_data.get("skip", False),
    )

    # File verification settings
    file_data = data.get("file_verification", {})
    config.file_verification = FileVerificationConfig(
        required_extensions=file_data.get("required_extensions", []),
        skip=file_data.get("skip", False),
    )

    # Set test_method based on project_type if not explicitly set
    if config.project_type == "unity" and config.test_method == "cli":
        config.test_method = "unity_mcp"

    return config


def _auto_detect_config(spec_path: Path, project_root: Optional[Path] = None) -> VerifierConfig:
    """Auto-detect project type and create default config."""
    if not project_root:
        project_root = find_project_root(spec_path) or spec_path.parent

    config = VerifierConfig()

    # Unity detection
    if (project_root / "Assets").is_dir() or (project_root / "ProjectSettings").is_dir():
        config.project_type = "unity"
        config.test_method = "unity_mcp"
        config.file_verification.required_extensions = [".cs", ".meta"]
        return config

    # Python
    if (project_root / "pyproject.toml").exists() or (project_root / "setup.py").exists():
        config.project_type = "python"
        config.test_command = "pytest"
        return config

    # TypeScript/Node
    if (project_root / "package.json").exists():
        config.project_type = "typescript"
        config.test_command = "npm test"
        return config

    # C#/.NET (non-Unity)
    if list(project_root.glob("*.csproj")) or list(project_root.glob("*.sln")):
        config.project_type = "csharp"
        config.test_command = "dotnet test"
        return config

    # Go
    if (project_root / "go.mod").exists():
        config.project_type = "go"
        config.test_command = "go test ./..."
        return config

    # Rust
    if (project_root / "Cargo.toml").exists():
        config.project_type = "rust"
        config.test_command = "cargo test"
        return config

    # Java
    if (project_root / "pom.xml").exists():
        config.project_type = "java"
        config.test_command = "mvn test"
        return config

    if (project_root / "build.gradle").exists():
        config.project_type = "java"
        config.test_command = "gradle test"
        return config

    return config


def get_test_command(config: VerifierConfig) -> Optional[str]:
    """Get the test command to run based on config."""
    if config.test_command:
        return config.test_command
    return DEFAULT_TEST_COMMANDS.get(config.project_type)


def create_default_config(project_type: str) -> dict:
    """Create a default config dict for a project type."""
    config = {
        "project_type": project_type,
        "test_method": "unity_mcp" if project_type == "unity" else "cli",
    }

    if project_type == "unity":
        config["unity"] = {
            "test_mode": "EditMode",
            "assembly_names": []
        }
        config["file_verification"] = {
            "required_extensions": [".cs", ".meta"]
        }
    elif project_type in DEFAULT_TEST_COMMANDS:
        config["test_command"] = DEFAULT_TEST_COMMANDS[project_type]

    return config
