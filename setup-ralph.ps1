<#
.SYNOPSIS
    Sets up the Ralph Pipeline in a project using a submodule.

.DESCRIPTION
    This script configures a project to use the Ralph Pipeline by:
    - Creating a symlink from .claude -> RalphSubmodule/.claude
    - Copying CLAUDE.md from the submodule
    - Setting up required directory structure

    Expected setup:
    1. Add Ralph as submodule: git submodule add <repo> Ralph_Pipeline
    2. Copy this script to project root
    3. Run: .\setup-ralph.ps1

.PARAMETER RalphPath
    Path to the Ralph submodule. Defaults to "Ralph_Pipeline" in current directory.

.PARAMETER Force
    Overwrite existing files without prompting.

.EXAMPLE
    .\setup-ralph.ps1

.EXAMPLE
    .\setup-ralph.ps1 -RalphPath "libs/ralph"

.EXAMPLE
    .\setup-ralph.ps1 -Force
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$RalphPath = "Ralph_Pipeline",
    
    [Parameter()]
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# Get project root (where the script is run from)
$ProjectPath = Get-Location

# Resolve Ralph submodule path
if (-not [System.IO.Path]::IsPathRooted($RalphPath)) {
    $RalphPath = Join-Path $ProjectPath $RalphPath
}

Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║                   Ralph Pipeline Setup                       ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "Project Root:    $ProjectPath" -ForegroundColor Yellow
Write-Host "Ralph Submodule: $RalphPath" -ForegroundColor Yellow
Write-Host ""

# ============================================================================
# VERIFY SUBMODULE EXISTS
# ============================================================================

$ralphClaudeDir = Join-Path $RalphPath ".claude"
$ralphClaudeMd = Join-Path $RalphPath "CLAUDE.md"

if (-not (Test-Path $RalphPath)) {
    Write-Host "ERROR: Ralph submodule not found at: $RalphPath" -ForegroundColor Red
    Write-Host ""
    Write-Host "To add Ralph as a submodule:" -ForegroundColor Yellow
    Write-Host "  git submodule add <ralph-repo-url> Ralph_Pipeline" -ForegroundColor White
    Write-Host "  git submodule update --init" -ForegroundColor White
    Write-Host ""
    Write-Host "Or specify a different path:" -ForegroundColor Yellow
    Write-Host "  .\setup-ralph.ps1 -RalphPath 'path/to/ralph'" -ForegroundColor White
    exit 1
}

if (-not (Test-Path $ralphClaudeDir)) {
    Write-Host "ERROR: .claude directory not found in Ralph submodule" -ForegroundColor Red
    Write-Host "  Expected: $ralphClaudeDir" -ForegroundColor Gray
    exit 1
}

if (-not (Test-Path $ralphClaudeMd)) {
    Write-Host "ERROR: CLAUDE.md not found in Ralph submodule" -ForegroundColor Red
    Write-Host "  Expected: $ralphClaudeMd" -ForegroundColor Gray
    exit 1
}

Write-Host "✓ Ralph submodule verified" -ForegroundColor Green
Write-Host ""

# ============================================================================
# STEP 1: Backup existing files
# ============================================================================

Write-Host "[1/5] Checking for existing files..." -ForegroundColor Cyan

$claudeDir = Join-Path $ProjectPath ".claude"
$claudeMd = Join-Path $ProjectPath "CLAUDE.md"
$backupDir = Join-Path $ProjectPath ".ralph-backup"

$needsBackup = @()

if (Test-Path $claudeDir) {
    $item = Get-Item $claudeDir -Force
    if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        Write-Host "  .claude is already a symlink - will replace" -ForegroundColor Yellow
        Remove-Item $claudeDir -Force
    } else {
        $needsBackup += ".claude"
    }
}

if (Test-Path $claudeMd) {
    # Check if it's already Ralph's CLAUDE.md (has "Ralph Pipeline" header)
    $content = Get-Content $claudeMd -First 1 -ErrorAction SilentlyContinue
    if ($content -match "Ralph Pipeline") {
        Write-Host "  CLAUDE.md is already Ralph's - will replace" -ForegroundColor Yellow
    } else {
        $needsBackup += "CLAUDE.md"
    }
}

if ($needsBackup.Count -gt 0) {
    Write-Host "  Found existing: $($needsBackup -join ', ')" -ForegroundColor Yellow
    
    if (-not $Force) {
        $response = Read-Host "  Back up and replace? (y/n)"
        if ($response -ne 'y' -and $response -ne 'Y') {
            Write-Host "Aborted." -ForegroundColor Red
            exit 1
        }
    }
    
    # Create backup directory
    if (-not (Test-Path $backupDir)) {
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    }
    
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    
    foreach ($item in $needsBackup) {
        $src = Join-Path $ProjectPath $item
        $dst = Join-Path $backupDir "$item.$timestamp"
        
        Write-Host "  Backing up: $item -> .ralph-backup/$item.$timestamp" -ForegroundColor Gray
        Move-Item -Path $src -Destination $dst -Force
    }
    
    Write-Host "  ✓ Backup complete" -ForegroundColor Green
} else {
    Write-Host "  ✓ No conflicts" -ForegroundColor Green
}

# ============================================================================
# STEP 2: Create directory structure
# ============================================================================

Write-Host "[2/5] Creating directory structure..." -ForegroundColor Cyan

$dirsToCreate = @(
    "Specs/Active",
    "Specs/Complete",
    ".ralph/state",
    ".ralph/prompts"
)

foreach ($dir in $dirsToCreate) {
    $fullPath = Join-Path $ProjectPath $dir
    if (-not (Test-Path $fullPath)) {
        New-Item -ItemType Directory -Path $fullPath -Force | Out-Null
        Write-Host "  Created: $dir" -ForegroundColor Gray
    }
}

Write-Host "  ✓ Directories created" -ForegroundColor Green

# ============================================================================
# STEP 3: Create symlinks
# ============================================================================

Write-Host "[3/5] Creating symlinks..." -ForegroundColor Cyan

# Create junction for .claude directory (doesn't require admin on Windows)
try {
    $result = cmd /c mklink /J "`"$claudeDir`"" "`"$ralphClaudeDir`"" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "mklink failed: $result"
    }
    Write-Host "  ✓ .claude -> $ralphClaudeDir (junction)" -ForegroundColor Green
} catch {
    Write-Host "  ⚠ Could not create junction: $_" -ForegroundColor Yellow
    Write-Host "    Copying instead..." -ForegroundColor Yellow
    Copy-Item -Path $ralphClaudeDir -Destination $claudeDir -Recurse -Force
    Write-Host "  ✓ .claude copied" -ForegroundColor Green
}

# Copy CLAUDE.md (file symlinks require admin, so just copy)
Copy-Item -Path $ralphClaudeMd -Destination $claudeMd -Force
Write-Host "  ✓ CLAUDE.md copied from submodule" -ForegroundColor Green

# ============================================================================
# STEP 4: Create MCP config and ralph.config.json
# ============================================================================

Write-Host "[4/5] Setting up configuration..." -ForegroundColor Cyan

# Create .mcp.json for MCP server config
$mcpConfigFile = Join-Path $ProjectPath ".mcp.json"

# Get the relative path to Ralph submodule
$ralphRelative = [System.IO.Path]::GetRelativePath($ProjectPath, $RalphPath).Replace("\", "/")

$mcpConfig = @{
    mcpServers = @{
        ralph = @{
            type = "stdio"
            command = "cmd"
            args = @("/c", "cd", $ralphRelative, "&&", "python", "-m", "ralph.mcp_server.server")
        }
    }
}

$mcpConfig | ConvertTo-Json -Depth 10 | Set-Content -Path $mcpConfigFile -Encoding UTF8
Write-Host "  Created: .mcp.json (MCP server config)" -ForegroundColor Gray

# Create ralph.config.json
$configFile = Join-Path $ProjectPath "ralph.config.json"

if (-not (Test-Path $configFile)) {
    $projectName = Split-Path $ProjectPath -Leaf
    
    $config = @{
        name = $projectName
        tech_stack = @{
            language = ""
            runtime = ""
            frameworks = @()
            test_framework = ""
            build_command = ""
            test_command = ""
            mcp_tools = @()
        }
        specs_dir = "Specs/Active"
        source_dir = "src"
        max_iterations = 15
    }
    
    $config | ConvertTo-Json -Depth 10 | Set-Content -Path $configFile -Encoding UTF8
    Write-Host "  Created: ralph.config.json" -ForegroundColor Gray
    Write-Host "  (Run /ralph:detect-stack to auto-configure)" -ForegroundColor Yellow
} else {
    Write-Host "  ralph.config.json already exists" -ForegroundColor Gray
}

Write-Host "  ✓ Configuration ready" -ForegroundColor Green

# ============================================================================
# STEP 5: Verify setup
# ============================================================================

Write-Host "[5/5] Verifying setup..." -ForegroundColor Cyan

$checks = @(
    @{ Path = ".claude"; Type = "Directory" },
    @{ Path = ".claude/settings.json"; Type = "File" },
    @{ Path = ".claude/commands"; Type = "Directory" },
    @{ Path = ".mcp.json"; Type = "File" },
    @{ Path = "CLAUDE.md"; Type = "File" },
    @{ Path = "Specs/Active"; Type = "Directory" },
    @{ Path = ".ralph/state"; Type = "Directory" },
    @{ Path = "ralph.config.json"; Type = "File" }
)

$allPassed = $true
foreach ($check in $checks) {
    $fullPath = Join-Path $ProjectPath $check.Path
    $exists = Test-Path $fullPath
    
    if ($exists) {
        Write-Host "  ✓ $($check.Path)" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $($check.Path) MISSING" -ForegroundColor Red
        $allPassed = $false
    }
}

# ============================================================================
# DONE
# ============================================================================

Write-Host ""
if ($allPassed) {
    Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "║                    Setup Complete! ✓                         ║" -ForegroundColor Green
    Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "  1. Open this project in Claude Code" -ForegroundColor White
    Write-Host "  2. Run: /ralph:detect-stack" -ForegroundColor White
    Write-Host "  3. Review ralph.config.json" -ForegroundColor White
    Write-Host "  4. Run: /ralph:new-spec to create your first spec" -ForegroundColor White
    Write-Host ""
    Write-Host "Available commands:" -ForegroundColor Cyan
    Write-Host "  /ralph:status       - Check pipeline status" -ForegroundColor Gray
    Write-Host "  /ralph:new-spec     - Create a new feature spec" -ForegroundColor Gray
    Write-Host "  /ralph:approve      - Approve pending spec" -ForegroundColor Gray
    Write-Host "  /ralph:reject       - Reject with feedback" -ForegroundColor Gray
    Write-Host "  /ralph:detect-stack - Auto-detect tech stack" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Recommended .gitignore additions:" -ForegroundColor Cyan
    Write-Host "  .ralph/state/" -ForegroundColor Gray
    Write-Host "  .ralph-backup/" -ForegroundColor Gray
} else {
    Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Red
    Write-Host "║                 Setup had issues ⚠                           ║" -ForegroundColor Red
    Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Red
    Write-Host ""
    Write-Host "Some files are missing. Check the errors above." -ForegroundColor Yellow
}
