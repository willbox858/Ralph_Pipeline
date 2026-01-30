#!/bin/bash
#
# Ralph Pipeline Setup Script
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/willbox858/Ralph_Pipeline/master/setup.sh | bash
#
# Or clone and run:
#   git clone https://github.com/willbox858/Ralph_Pipeline.git .ralph-temp
#   bash .ralph-temp/setup.sh
#   rm -rf .ralph-temp
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo ""
echo "=========================================="
echo "  Ralph Pipeline Setup"
echo "=========================================="
echo ""

# Check if we're in a git repo
if ! git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
    echo -e "${YELLOW}Not in a git repository. Initializing...${NC}"
    git init
    echo ""
fi

# Check if .claude already exists
if [ -d ".claude" ]; then
    echo -e "${RED}Error: .claude directory already exists.${NC}"
    echo "If you want to reinstall, remove it first: rm -rf .claude"
    exit 1
fi

# Add submodule
echo -e "${GREEN}[1/5]${NC} Adding Ralph Pipeline as submodule..."
git submodule add https://github.com/willbox858/Ralph_Pipeline.git .ralph-pipeline

# Create symlink to .claude
echo -e "${GREEN}[2/5]${NC} Creating .claude symlink..."
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" || "$OSTYPE" == "cygwin" ]]; then
    # Windows - use directory junction or copy
    cmd //c "mklink /J .claude .ralph-pipeline\\.claude" 2>/dev/null || cp -r .ralph-pipeline/.claude .claude
else
    # Unix - use symlink
    ln -s .ralph-pipeline/.claude .claude
fi

# Create Specs directory
echo -e "${GREEN}[3/5]${NC} Creating Specs directory..."
mkdir -p Specs/Active

# Copy root files (these are meant to be customized per-project)
echo -e "${GREEN}[4/5]${NC} Copying project files..."

# CLAUDE.md - copy and customize
cat > CLAUDE.md << 'CLAUDEMD'
# Project Instructions

You are working on this project with the Ralph Pipeline for spec-driven development.

## Quick Start

Run `/orient` to understand the system and current state.

## Slash Commands

| Command | Purpose |
|---------|---------|
| `/orient` | Get oriented - understand the system and current state |
| `/spec <name>` | Create a new feature spec |
| `/ralph <path>` | Start the pipeline on a spec |
| `/status <path>` | Check pipeline progress |
| `/review <path>` | Handle specs flagged for human review |

## Project-Specific Instructions

<!-- Add your project-specific instructions here -->

## Key Directories

```
.claude/            # Ralph Pipeline (submodule - don't edit directly)
.ralph-pipeline/    # Pipeline submodule root
Specs/Active/       # Your feature specs go here
src/                # Generated source code
```

## Tech Stack

<!-- Define your project's tech stack here. This overrides STYLE.md defaults. -->
<!-- Example:
This project uses:
- Language: TypeScript
- Runtime: Node.js 20+
- Framework: Fastify
- Testing: Jest
-->

CLAUDEMD

# STYLE.md - copy template for customization
cat > STYLE.md << 'STYLEMD'
# Project Style Guide

## Language

<!-- Specify your language here. Options: TypeScript, C#, Python, Go, Java, Rust -->
**Primary Language:** TypeScript

## Project Structure

```
src/
  components/       # Feature implementations
  shared/           # Shared types and utilities
tests/
  unit/            # Unit tests
  integration/     # Integration tests
Specs/
  Active/          # Active feature specs
```

## Naming Conventions

- **Files:** kebab-case (e.g., `user-service.ts`)
- **Classes/Interfaces:** PascalCase (e.g., `UserService`)
- **Functions/Variables:** camelCase (e.g., `getUserById`)
- **Constants:** UPPER_SNAKE_CASE (e.g., `MAX_RETRIES`)

## Code Style

- 2 space indentation
- Single quotes for strings
- Semicolons required
- Max line length: 100 characters

## Testing

- Test files: `*.test.ts` or `*.spec.ts`
- Use descriptive test names: `it('should return user when valid ID provided')`
- Aim for >80% code coverage

## Architecture Preferences

- Prefer composition over inheritance
- Use dependency injection
- Keep functions small and focused
- Avoid deep nesting (max 3 levels)

STYLEMD

# Create .mcp.json for MCP server discovery
echo -e "${GREEN}[5/8]${NC} Creating .mcp.json..."
cat > .mcp.json << 'MCPJSON'
{
  "mcpServers": {
    "ralph-status": {
      "type": "stdio",
      "command": "python",
      "args": [".claude/scripts/status-mcp-server.py"],
      "env": {}
    }
  }
}
MCPJSON

# Create .ralph directory and initialize database
echo -e "${GREEN}[6/8]${NC} Initializing Ralph database..."
mkdir -p .ralph
python3 -c "import sys; sys.path.insert(0, '.claude/lib'); from ralph_db import RalphDB; RalphDB('.ralph/ralph.db')" 2>/dev/null || \
python -c "import sys; sys.path.insert(0, '.claude/lib'); from ralph_db import RalphDB; RalphDB('.ralph/ralph.db')"

# Install Python dependencies
echo -e "${GREEN}[7/8]${NC} Checking Python dependencies..."
if [ -f ".ralph-pipeline/setup.py" ]; then
    python3 .ralph-pipeline/setup.py --check 2>/dev/null || python .ralph-pipeline/setup.py --check || true
fi

# Create .gitignore entries if needed
echo -e "${GREEN}[8/8]${NC} Updating .gitignore..."
if [ -f ".gitignore" ]; then
    # Append if not already present
    grep -q ".orchestrator-lock" .gitignore || echo -e "\n# Ralph Pipeline\n.orchestrator-lock\n.agent-active\n.ralph/" >> .gitignore
else
    cat > .gitignore << 'GITIGNORE'
# Ralph Pipeline
.orchestrator-lock
.agent-active

# Ralph data
.ralph/

# Generated
src/
dist/
node_modules/
__pycache__/
*.pyc

# OS
.DS_Store
Thumbs.db

# Editors
.idea/
.vscode/
*.swp
GITIGNORE
fi

echo ""
echo -e "${GREEN}=========================================="
echo "  Setup Complete!"
echo "==========================================${NC}"
echo ""
echo "Next steps:"
echo "  1. Edit CLAUDE.md with project-specific instructions"
echo "  2. Edit STYLE.md with your coding conventions"
echo "  3. Run: git add . && git commit -m 'Add Ralph Pipeline'"
echo "  4. Start Claude Code and run /orient"
echo ""
echo "To create your first spec:"
echo "  /spec my-feature"
echo ""
