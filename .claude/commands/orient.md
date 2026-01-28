# Ralph System Orientation

You are working in a Ralph project - a hierarchical spec-driven multi-agent development system.

## Quick Summary

Ralph uses **specs** (JSON files) to define what should be built, then runs **agents** to implement them:

1. **Specs** describe features hierarchically (parent → children)
2. **Agents** (Researcher, Proposer, Critic, Implementer, Verifier) do the work
3. **Orchestrator** manages parallel execution and agent communication

## Key Directories

```
.claude/
├── scripts/
│   ├── orchestrator.py          # Main pipeline runner
│   └── check-pipeline-status.py # Status checker
├── agents/                       # Agent prompts
├── schema/                       # JSON schemas
└── commands/                     # Slash commands (you are here)

Specs/
└── Active/                       # Active specs go here
```

## Your Role

As the user-facing Claude, you:
1. Help users **create specs** for features they want to build
2. **Start the pipeline** with `/ralph`
3. **Check status** with `/status`
4. **Intervene** when specs are flagged for review

## Common Tasks

### Create a new spec
```bash
# Copy the template
cp .claude/templates/spec-template.json Specs/Active/my-feature/spec.json
# Then edit it with the user
```

### Start the pipeline
```bash
python .claude/scripts/orchestrator.py --spec Specs/Active/my-feature/spec.json --live
```

### Check status
```bash
python .claude/scripts/check-pipeline-status.py --root Specs/Active/my-feature/spec.json
```

## Key Concepts

- **Leaf spec**: Directly implemented (has code)
- **Non-leaf spec**: Decomposes into children
- **Shared types**: Cross-cutting types used by siblings
- **Hibernation**: Agents sleep and wake as needed
- **Integration tests**: Run when all siblings complete

## Read More

- `CLAUDE.md` - Project context
- `MIGRATION-SUMMARY.md` - Full architecture docs
- `.claude/agents/*.md` - Agent prompts

---

Ready to help! What would you like to build?
