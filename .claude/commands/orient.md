# Ralph System Orientation

You are working in a Ralph project - a hierarchical spec-driven multi-agent development system.

## Quick Summary

Ralph uses **specs** (JSON files) to define what should be built, then runs **agents** to implement them:

1. **Specs** describe features hierarchically (parent -> children)
2. **Agents** (Researcher, Proposer, Critic, Implementer, Verifier) do the work
3. **Orchestrator** manages parallel execution and agent communication
4. **Database** tracks specs, events, and messages (`.ralph/ralph.db`)

## Key Directories

```
.claude/
├── scripts/
│   ├── orchestrator.py       # Main pipeline runner
│   └── status-mcp-server.py  # MCP server for ralph_* tools
├── agents/
│   ├── *.md                  # Agent prompts
│   └── configs/*.json        # Agent permissions/settings
├── lib/                      # Shared Python modules
├── schema/                   # JSON schemas
└── commands/                 # Slash commands (you are here)

.ralph/
└── ralph.db                  # SQLite database

Specs/
└── Active/                   # Active specs go here
```

## Your Role

As the user-facing Claude, you:
1. Help users **create specs** for features they want to build
2. **Start the pipeline** with `/ralph`
3. **Check status** with `/pipeline-status` or MCP tools
4. **Intervene** when specs are flagged for review

## Slash Commands

| Command | Purpose |
|---------|---------|
| `/orient` | You are here |
| `/spec <name>` | Create a new feature spec |
| `/ralph <path>` | Start the pipeline |
| `/pipeline-status` | Check pipeline progress |
| `/review <path>` | Handle blocked/failed specs |
| `/upgrade` | Upgrade older Ralph repos to v4 |

## MCP Tools (if loaded)

These tools query the database directly:

| Tool | Purpose |
|------|---------|
| `ralph_pipeline_summary` | Overview of all specs |
| `ralph_list_specs` | List specs with optional status filter |
| `ralph_get_spec` | Get details for one spec |
| `ralph_spec_tree` | Hierarchical view |
| `ralph_review_queue` | Specs needing attention |

## Common Tasks

### Create a new spec
```
/spec my-feature
```

### Start the pipeline
```
/ralph Specs/Active/my-feature/spec.json
```

### Check status
```
/pipeline-status Specs/Active/my-feature/spec.json
```
Or use `ralph_pipeline_summary` MCP tool.

## Key Concepts

- **Leaf spec**: Directly implemented (has code)
- **Non-leaf spec**: Decomposes into children
- **Shared types**: Cross-cutting types used by siblings
- **Hibernation**: Agents sleep and wake as needed
- **Hooks**: Permission enforcement per agent role

## Read More

- `CLAUDE.md` - Project context
- `STYLE.md` - Code style conventions
- `.claude/agents/*.md` - Agent prompts
- `.claude/agents/configs/*.json` - Agent permissions

---

Ready to help! What would you like to build?
