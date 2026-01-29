# Ralph v2 → v4 Architecture & Migration Summary

## Evolution Overview

| Version | Key Feature | Status |
|---------|-------------|--------|
| v1 | Raw Anthropic API (broken) | ❌ Deprecated |
| v2 | Agent SDK integration | ✅ Works |
| v3 | Hibernating parents | ✅ Works |
| **v4** | **Full orchestrator with parallel execution** | ✅ **Current** |

---

## v4: The Full Orchestrator

### What's New

v4 introduces a **central orchestrator** that manages the entire pipeline:

1. **Parallel Execution** - Specs run concurrently (respecting dependencies)
2. **In-Process MCP Server** - Agents communicate via tool calls
3. **Universal Hibernation** - Any agent can sleep and wake
4. **Researcher Agent** - Gathers context before implementation
5. **Integration Testing** - Runs when all siblings complete
6. **Status Endpoint** - User-facing Claude can check progress

### Architecture

```
User ↔ Claude Code → python orchestrator.py
                          │
                    ┌─────┴─────┐
                    │Orchestrator│
                    │           │
                    │ • Work Queue
                    │ • Dependency Graph
                    │ • Completion Tracker
                    │ • Hibernation Manager
                    └─────┬─────┘
                          │
         ┌────────────────┼────────────────┐
         ↓                ↓                ↓
    ┌─────────┐     ┌─────────┐     ┌─────────┐
    │ Agent A │     │ Agent B │     │ Agent C │
    │(parallel)│    │(parallel)│    │(waiting)│
    └────┬────┘     └────┬────┘     └─────────┘
         │               │
         └───────┬───────┘
                 ↓
         ┌─────────────┐
         │ MCP Server  │ (in-process)
         │             │
         │ • send_message
         │ • hibernate
         │ • signal_complete
         │ • check_dependency
         │ • request_parent_decision
         └─────────────┘
```

### Processing Flow

```
┌─────────────────────────────────────────────────────────────┐
│                      NON-LEAF SPEC                          │
│                                                             │
│  1. Proposer ↔ Critic (architecture loop)                  │
│  2. Scaffold children directories                          │
│  3. HIBERNATE (parent sleeps)                              │
│                                                             │
│  ... children run in parallel ...                          │
│                                                             │
│  4. WAKE when all children complete                        │
│  5. Run integration tests                                  │
│  6. Complete or flag for review                            │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                        LEAF SPEC                            │
│                                                             │
│  1. RESEARCHER (runs first)                                │
│     - WebSearch for libraries                              │
│     - WebFetch documentation                               │
│     - Output research.json                                 │
│                                                             │
│  2. IMPLEMENTATION LOOP                                     │
│     ┌──────────────────────────────────────────┐           │
│     │ Implementer (reads research.json)        │           │
│     │      │                                   │           │
│     │      ├── needs help? → request_parent   │           │
│     │      │                 → hibernate       │           │
│     │      │                 → wake with answer│           │
│     │      │                                   │           │
│     │      ↓                                   │           │
│     │ Verifier (structured JSON output)        │           │
│     │      │                                   │           │
│     │      ├── pass? → complete               │           │
│     │      └── fail? → loop with errors       │           │
│     └──────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────────┘
```

### MCP Tools

Agents communicate with the orchestrator via MCP tools:

| Tool | Purpose | Blocks? |
|------|---------|---------|
| `send_message` | Send message to parent/sibling | No |
| `hibernate` | Save state and terminate | Yes (terminates) |
| `signal_complete` | Signal work is done | No |
| `check_dependency` | Check if dep is ready | No |
| `request_parent_decision` | Ask parent, hibernate until response | Yes |
| `get_my_messages` | Get pending messages | No |
| `respond_to_message` | Respond to a request | No |

### Parallelism Rules

1. **Dependency-aware**: Specs only run when `depends_on` are complete
2. **Concurrent limit**: Max N agents at once (`--max-concurrent`)
3. **Sibling parallelism**: After `shared/` completes, siblings run in parallel
4. **Integration gate**: Parent wakes only when ALL children complete

---

## File Structure

```
.claude/
├── scripts/
│   ├── orchestrator.py          # Main v4 orchestrator
│   ├── check-pipeline-status.py # Status checker for user-facing Claude
│   ├── status-mcp-server.py     # MCP server for ralph_* tools
│   ├── scaffold-children.py     # Child directory scaffolding
│   ├── migrate-specs-to-db.py   # Migration utility
│   └── init-orchestrator.py     # Initialization utility
│
├── agents/
│   ├── researcher.md            # Gathers context before implementation
│   ├── proposer.md              # Proposes architecture/structure
│   ├── critic.md                # Reviews proposals
│   ├── implementer.md           # Writes code
│   ├── verifier.md              # Runs tests, structured output
│   └── spec-writer.md           # Helps create specs
│
├── schema/
│   ├── spec-schema.json
│   ├── message-schema.json      # Updated with priority, wake_signals
│   ├── parent-context-schema.json
│   └── verification-result-schema.json
│
├── lib/
│   ├── spec.py                  # Spec dataclass and utilities
│   ├── ralph_db.py              # Database operations
│   ├── hooks.py                 # Hook utilities
│   └── message_hooks.py         # Message routing hooks
│
└── settings.json                # Hooks config
```

---

## Usage

### Start Pipeline

```bash
# Simulated (no API calls)
python .claude/scripts/orchestrator.py --spec Specs/Active/feature/spec.json

# Live execution
python .claude/scripts/orchestrator.py --spec Specs/Active/feature/spec.json --live

# With status server
python .claude/scripts/orchestrator.py --spec Specs/Active/feature/spec.json --live --status-port 8765
```

### Check Status (User-Facing Claude)

```bash
# One-time check
python .claude/scripts/check-pipeline-status.py --root Specs/Active/feature/spec.json

# Watch mode
python .claude/scripts/check-pipeline-status.py --root Specs/Active/feature/spec.json --watch

# JSON output
python .claude/scripts/check-pipeline-status.py --root Specs/Active/feature/spec.json --json
```

### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--spec` | required | Path to root spec.json |
| `--live` | false | Actually call Agent SDK |
| `--dry-run` | false | Print actions only |
| `--max-depth` | 3 | Max hierarchy depth |
| `--max-iterations` | 10 | Max impl iterations per spec |
| `--max-arch-iterations` | 5 | Max architecture loop iterations |
| `--max-agents` | 100 | Total agent spawn limit |
| `--max-concurrent` | 5 | Max parallel agents |
| `--model` | claude-sonnet-4-20250514 | Model to use |
| `--status-port` | 0 | HTTP status server port (0=disabled) |

---

## Key Design Decisions

### 1. In-Process MCP Server
The MCP server runs in the same Python process as the orchestrator. This means:
- No IPC overhead
- Shared state access
- Simple deployment

### 2. Universal Hibernation
Any agent can hibernate, not just parents. This enables:
- Child asks parent for decision → hibernates → wakes with answer
- Blocked on dependency → hibernates → wakes when ready
- Context preserved across sleep/wake cycles

### 3. Researcher Before Implementation
Every leaf runs a Researcher agent first. This ensures:
- Implementer has library recommendations
- Best practices documented
- Gotchas known upfront

### 4. Structured Verification Output
Verifier outputs JSON with explicit `verdict` field:
```json
{
  "verdict": "pass" | "fail_compilation" | "fail_tests",
  "compilation": { ... },
  "tests": { ... },
  "suggestions": [ ... ]
}
```

### 5. Integration at Sibling Boundaries
When ALL siblings complete, parent wakes and runs integration tests. This catches:
- Interface mismatches
- Missing integrations
- Cross-component bugs

### 6. Human Review for Failures
Permanent failures don't crash the pipeline. They:
- Mark the spec as `blocked`
- Halt that subtree
- Flag for human review
- Allow other subtrees to continue

---

## Requirements

```bash
pip install claude-agent-sdk
```

The orchestrator requires:
- Python 3.10+
- `claude-agent-sdk` package
- `ANTHROPIC_API_KEY` environment variable (for live mode)

---

## Troubleshooting

### "Max agents exceeded"
Increase `--max-agents` or check for infinite loops in your spec structure.

### "Dependency not found"
Ensure `depends_on` names match actual child directory names.

### Agent stuck in hibernation
Check `agent-context.json` in the spec directory for the `resume_trigger`.

### No progress
Run `check-pipeline-status.py --watch` to see what's happening. Look for:
- Blocked dependencies
- Failed specs
- Hibernating agents waiting for responses
