# Ralph Pipeline Configuration

View or initialize the Ralph Pipeline configuration for this project.

## Arguments

- `--init`: Initialize configuration for a new project (interactive wizard)

## Instructions

### Without Arguments: View Current Config

1. Check if `ralph.config.json` exists in project root
2. If exists: Read and display the current configuration
3. If missing: Inform user and suggest using `--init`

### With `--init`: Initialize New Project

Run an interactive configuration wizard:

#### Step 1: Check Prerequisites

1. Verify Ralph submodule exists (look for `Ralph_Pipeline/` or similar)
2. If not found, instruct user to add it first:
   ```
   git submodule add <ralph-repo-url> Ralph_Pipeline
   git submodule update --init
   ```

#### Step 2: Handle Existing Configuration

If `ralph.config.json` already exists:
1. Display current config summary
2. Ask user:
   - "Use as reference for new config?" (read values, then replace)
   - "Rename to `.ralph.config.backup.json` before creating new?"
   - "Cancel initialization?"

#### Step 3: Detect Tech Stack (Auto + Confirm)

Scan project for telltale files:

| Files Found | Detected Stack |
|-------------|----------------|
| `*.csproj` + `Assembly-CSharp.csproj` or `ProjectSettings/` | `unity` |
| `*.csproj`, `*.sln` (no Unity markers) | `csharp` |
| `pyproject.toml`, `setup.py`, `requirements.txt` | `python` |
| `package.json` + `tsconfig.json` | `typescript` |
| `package.json` (no tsconfig) | `javascript` |
| `Cargo.toml` | `rust` |
| `go.mod` | `go` |
| `project.godot` | `godot` |

Present detection result and ask for confirmation:
```
Detected tech stack: unity (C# with Unity 2022.3)
Is this correct? [Y/n]
```

If uncertain or user says no, ask them to specify.

#### Step 4: Gather Project Settings

Auto-detect with confirmation for each:

1. **Project Name**: Default to directory name
2. **Source Directory**:
   - Unity: `Assets/Scripts`
   - Python: `src` or root if flat
   - C#: `src` or detect from .csproj
3. **Build Command**: Tech stack default or custom
4. **Test Command**: Tech stack default or custom
5. **Lint Command**: Tech stack default (optional)

Only ask clarifying questions if:
- Multiple valid options detected
- Detection confidence is low
- Tech stack requires special setup

#### Step 5: Configure MCP Servers (Guided Conversation)

This is a guided conversation to configure any MCP servers the project needs.

**Start by asking:**
```
Does this project use any MCP servers?

MCP servers provide specialized tools for specific platforms or services.
Common examples:
- Unity MCP (@anthropic/mcp-unity) - Unity Editor integration
- Godot MCP (@anthropic/mcp-godot) - Godot Editor integration
- Custom project tools - Your own MCP servers

Do you want to configure MCP servers? [y/N]
```

**If yes, guide through each server:**

1. Ask for server name (e.g., "unity", "godot", "my-custom-server")
2. Ask for command to run the server:
   - For npm packages: `npx -y @package/name`
   - For local scripts: `python ./tools/my-server.py`
   - For binaries: `/path/to/server`
3. Ask for any arguments (as a list)
4. Ask for environment variables (optional)
5. Ask for tool names this server provides (optional, for documentation)

**Example conversation:**
```
Server name: unity
Command to start server: npx
Arguments (comma-separated): -y, @anthropic/mcp-unity
Environment variables (KEY=VALUE, comma-separated): UNITY_PROJECT_PATH=.
Tool names (optional, comma-separated): mcp__unity__run_tests, mcp__unity__compile

Added MCP server 'unity'.

Add another MCP server? [y/N]
```

**Build the mcp_servers object:**
```json
"mcp_servers": {
  "<server-name>": {
    "type": "stdio",
    "command": "<command>",
    "args": ["<arg1>", "<arg2>"],
    "env": {"KEY": "VALUE"},
    "tools": ["tool1", "tool2"]
  }
}
```

If user declines MCP servers, set `"mcp_servers": {}`.

#### Step 6: Create Directory Structure

Create these directories **only if they don't exist**:
- `Specs/Active/`
- `Specs/Complete/`
- `.ralph/state/`
- `.ralph/prompts/`

Skip any directories that already exist.

#### Step 7: Generate Configuration Files

**Only create files if they don't exist.**

If `ralph.config.json` doesn't exist, create it:
```json
{
  "name": "<project-name>",
  "tech_stack": "<detected-stack>",
  "mcp_servers": { ... },
  "role_overrides": {},
  "build_command": "<command>",
  "test_command": "<command>",
  "lint_command": "<command>",
  "specs_dir": "Specs/Active",
  "source_dir": "<detected-source>",
  "max_iterations": 15
}
```

If `.mcp.json` doesn't exist, create it:
```json
{
  "mcpServers": {
    "ralph": {
      "type": "stdio",
      "command": "cmd",
      "args": ["/c", "cd", "Ralph_Pipeline", "&&", "python", "-m", "ralph.mcp_server.server"]
    }
  }
}
```

Note: The `.mcp.json` should also include any project MCP servers configured in Step 5.

#### Step 8: Verify and Report

Check what was created/already existed:
- [ ] `ralph.config.json` (created / already existed)
- [ ] `.mcp.json` (created / already existed)
- [ ] `Specs/Active/` (created / already existed)
- [ ] `.ralph/state/` (created / already existed)

Report success with next steps.

## Output Format

### View Config (no flags)

```
=== Ralph Configuration ===

Project: MyProject
Tech Stack: unity
Source: Assets/Scripts
Specs: Specs/Active

Build: (via Unity MCP)
Test: (via Unity MCP)
Lint: (none)

MCP Servers:
  - unity: npx -y @anthropic/mcp-unity
  - custom-tool: python ./tools/analyzer.py

Role Overrides: (none)

Max Iterations: 15
```

Or if missing:
```
No ralph.config.json found.

Run /ralph:config --init to initialize Ralph for this project.
```

### Init Complete

```
=== Ralph Initialized ===

Project: MyProject
Tech Stack: unity
Source: Assets/Scripts

MCP Servers: 2 configured
  - unity
  - custom-tool

Files:
  [created] ralph.config.json
  [created] .mcp.json
  [exists]  Specs/Active/
  [created] .ralph/state/

Next Steps:
1. Run setup-ralph.ps1 to link Claude files (if not already done)
2. Review ralph.config.json and adjust if needed
3. Add to .gitignore:
   .ralph/state/
   .ralph-backup/
4. Create your first spec with /ralph:new-spec
5. Check status anytime with /ralph:status

Ready to use Ralph Pipeline!
```

## Tech Stack Defaults Reference

| Stack | source_dir | build_command | test_command |
|-------|------------|---------------|--------------|
| python | `src` | `python -m py_compile` | `pytest -v` |
| csharp | `src` | `dotnet build` | `dotnet test` |
| typescript | `src` | `npm run build` | `npm test` |
| unity | `Assets/Scripts` | (MCP) | (MCP) |
| godot | `scripts` | (MCP) | (MCP) |
| rust | `src` | `cargo build` | `cargo test` |
| go | `.` | `go build ./...` | `go test ./...` |

## Error Handling

- **Submodule not found**: Provide exact git commands to add it
- **Existing config conflict**: Always offer backup before overwriting
- **Unknown tech stack**: Ask user to specify manually, use python defaults as fallback
- **File already exists**: Skip creation, report as "exists" in final summary
