#
# Ralph Pipeline Setup Script (PowerShell)
#
# Usage:
#   irm https://raw.githubusercontent.com/willbox858/Ralph_Pipeline/master/setup.ps1 | iex
#
# Or download and run:
#   Invoke-WebRequest -Uri "https://raw.githubusercontent.com/willbox858/Ralph_Pipeline/master/setup.ps1" -OutFile setup.ps1
#   .\setup.ps1
#

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Ralph Pipeline Setup" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check if we're in a git repo
$isGitRepo = git rev-parse --is-inside-work-tree 2>$null
if (-not $isGitRepo) {
    Write-Host "Not in a git repository. Initializing..." -ForegroundColor Yellow
    git init
    Write-Host ""
}

# Check if .claude already exists
if (Test-Path ".claude") {
    Write-Host "Error: .claude directory already exists." -ForegroundColor Red
    Write-Host "If you want to reinstall, remove it first: Remove-Item -Recurse -Force .claude"
    exit 1
}

# Add submodule
Write-Host "[1/5] Adding Ralph Pipeline as submodule..." -ForegroundColor Green
git submodule add https://github.com/willbox858/Ralph_Pipeline.git .ralph-pipeline

# Create junction to .claude (Windows equivalent of symlink for directories)
Write-Host "[2/5] Creating .claude junction..." -ForegroundColor Green
cmd /c "mklink /J .claude .ralph-pipeline\.claude"

# Create Specs directory
Write-Host "[3/5] Creating Specs directory..." -ForegroundColor Green
New-Item -ItemType Directory -Force -Path "Specs\Active" | Out-Null

# Copy root files
Write-Host "[4/5] Copying project files..." -ForegroundColor Green

# CLAUDE.md
@"
# Project Instructions

You are working on this project with the Ralph Pipeline for spec-driven development.

## Quick Start

Run ``/orient`` to understand the system and current state.

## Slash Commands

| Command | Purpose |
|---------|---------|
| ``/orient`` | Get oriented - understand the system and current state |
| ``/spec <name>`` | Create a new feature spec |
| ``/ralph <path>`` | Start the pipeline on a spec |
| ``/status <path>`` | Check pipeline progress |
| ``/review <path>`` | Handle specs flagged for human review |

## Project-Specific Instructions

<!-- Add your project-specific instructions here -->

## Key Directories

``````
.claude/            # Ralph Pipeline (submodule - don't edit directly)
.ralph-pipeline/    # Pipeline submodule root
Specs/Active/       # Your feature specs go here
src/                # Generated source code
``````

## Tech Stack

<!-- Define your project's tech stack here. This overrides STYLE.md defaults. -->
"@ | Out-File -FilePath "CLAUDE.md" -Encoding UTF8

# STYLE.md
@"
# Project Style Guide

## Language

<!-- Specify your language here. Options: TypeScript, C#, Python, Go, Java, Rust -->
**Primary Language:** TypeScript

## Project Structure

``````
src/
  components/       # Feature implementations
  shared/           # Shared types and utilities
tests/
  unit/            # Unit tests
  integration/     # Integration tests
Specs/
  Active/          # Active feature specs
``````

## Naming Conventions

- **Files:** kebab-case (e.g., ``user-service.ts``)
- **Classes/Interfaces:** PascalCase (e.g., ``UserService``)
- **Functions/Variables:** camelCase (e.g., ``getUserById``)
- **Constants:** UPPER_SNAKE_CASE (e.g., ``MAX_RETRIES``)

## Code Style

- 2 space indentation
- Single quotes for strings
- Semicolons required
- Max line length: 100 characters

## Testing

- Test files: ``*.test.ts`` or ``*.spec.ts``
- Use descriptive test names
- Aim for >80% code coverage

## Architecture Preferences

- Prefer composition over inheritance
- Use dependency injection
- Keep functions small and focused
- Avoid deep nesting (max 3 levels)
"@ | Out-File -FilePath "STYLE.md" -Encoding UTF8

# Update .gitignore
Write-Host "[5/5] Updating .gitignore..." -ForegroundColor Green
$gitignoreContent = @"
# Ralph Pipeline
.orchestrator-lock
.agent-active

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
"@

if (Test-Path ".gitignore") {
    $existing = Get-Content ".gitignore" -Raw
    if ($existing -notmatch "\.orchestrator-lock") {
        Add-Content ".gitignore" "`n# Ralph Pipeline`n.orchestrator-lock`n.agent-active"
    }
} else {
    $gitignoreContent | Out-File -FilePath ".gitignore" -Encoding UTF8
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  Setup Complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Edit CLAUDE.md with project-specific instructions"
Write-Host "  2. Edit STYLE.md with your coding conventions"
Write-Host "  3. Run: git add . ; git commit -m 'Add Ralph Pipeline'"
Write-Host "  4. Start Claude Code and run /orient"
Write-Host ""
Write-Host "To create your first spec:"
Write-Host "  /spec my-feature"
Write-Host ""
