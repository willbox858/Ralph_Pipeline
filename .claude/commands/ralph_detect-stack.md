# Detect Project Tech Stack

Automatically detect and configure the project's technology stack.

## Instructions

Analyze the project to determine:

1. **Primary Language** - Look for telltale files
2. **Runtime/Framework** - Check for framework configs
3. **Test Framework** - Find test configuration
4. **Build System** - Identify build tools
5. **Special Tools** - Unity, Godot, etc.

## Detection Rules

### C# / .NET
- `*.csproj`, `*.sln` → C# / .NET
- `Assembly-CSharp.csproj` or `ProjectSettings/` → Unity
- Look for `.NET` version in csproj

### Python
- `pyproject.toml`, `setup.py`, `requirements.txt` → Python
- Check for `pytest` in dependencies
- Look for `ruff.toml` or `[tool.ruff]`

### TypeScript / JavaScript
- `package.json` → Node.js
- `tsconfig.json` → TypeScript
- Check `dependencies` for frameworks (React, Vue, etc.)

### Rust
- `Cargo.toml` → Rust

### Go
- `go.mod` → Go

### Godot
- `project.godot` → Godot (GDScript or C#)

## Output: ralph.config.json

Create or update `ralph.config.json`:

```json
{
  "name": "<project-name>",
  "tech_stack": {
    "language": "C#",
    "runtime": "Unity 2022.3",
    "frameworks": ["Unity"],
    "test_framework": "Unity Test Framework",
    "build_command": "",
    "test_command": "",
    "mcp_tools": ["unity"]
  },
  "mcp_servers": [
    {
      "name": "unity",
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-unity"],
      "env": {"UNITY_PROJECT_PATH": "."}
    }
  ],
  "specs_dir": "Specs/Active",
  "source_dir": "Assets/Scripts",
  "max_iterations": 15
}
```

## Report to User

```
🔍 Tech Stack Detection Complete

Language: C#
Runtime: Unity 2022.3 LTS
Framework: Unity
Tests: Unity Test Framework
MCP Tools: unity

Configuration saved to ralph.config.json
```

## If Ambiguous

Ask the user to clarify:
- Multiple languages present
- Framework version uncertain
- Test framework not obvious
