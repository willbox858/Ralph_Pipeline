# Upgrade Ralph Pipeline

Upgrade a repo from an older Ralph Pipeline version to v4.

## Arguments

```
/upgrade              # Upgrade current repo
/upgrade --check      # Check what needs upgrading (no changes)
/upgrade /path/to/repo  # Upgrade a different repo
```

## What This Upgrades

| Component | Description |
|-----------|-------------|
| `.ralph/ralph.db` | SQLite database for specs, events, messages |
| Agent configs | JSON configs for each agent role |
| Hooks library | Permission enforcement via PreToolUse |
| MCP server | Status tools (ralph_list_specs, etc.) |
| Orchestrator | Updated with hooks integration |

## Execution

First, check what needs upgrading:
```bash
python upgrade.py --check --target "$ARGUMENTS"
```

If the user confirms, run the actual upgrade:
```bash
python upgrade.py --target "$ARGUMENTS"
```

## Version Detection

The script detects:
- **v3**: Has orchestrator but no database/hooks/MCP
- **v4**: Has all new features (database, hooks, MCP)
- **none**: Not a Ralph repo

## Post-Upgrade Steps

After upgrading:
1. Restart Claude Code (to load MCP server)
2. Run `python setup.py --check` to verify dependencies
3. Test with `/pipeline-status`

## Flags

| Flag | Effect |
|------|--------|
| `--check` | Preview only, no changes |
| `--force` | Skip confirmations |
| `--skip-specs` | Don't migrate existing specs |
| `--source /path` | Use different source repo |
