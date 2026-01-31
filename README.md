# Ralph Pipeline v2

A programmatic pipeline for orchestrating LLM agents in software development.

## Philosophy

**Programmatic layer handles deterministic logic:**
- State machine (phases, transitions)
- Scope enforcement (agents can only touch allowed paths)
- Message routing (validated, logged)
- Tool provisioning (per role + tech stack)

**Agent layer handles soft logic:**
- Understanding requirements
- Designing architecture
- Writing code
- Reviewing and critiquing
- Diagnosing failures

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      USER                                       │
│                        │                                        │
│            (conversation, /commands)                            │
│                        ▼                                        │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                INTERFACE AGENT                           │   │
│  │         (User-facing Claude Code instance)               │   │
│  │  • Helps draft specs                                     │   │
│  │  • Receives approval requests via MCP                    │   │
│  │  • Queries status via /StatusCheck                       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                        │                                        │
│                        ▼                                        │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   ORCHESTRATOR                           │   │
│  │            (Programmatic Python engine)                  │   │
│  │  • State machine • Message bus • Agent deployment        │   │
│  └─────────────────────────────────────────────────────────┘   │
│                        │                                        │
│         ┌──────────────┼──────────────┐                        │
│         ▼              ▼              ▼                        │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐                  │
│  │ARCHITECTURE│ │IMPLEMENTAT'N│ │MAINTENANCE │                  │
│  │   TEAM     │ │   TEAM     │ │   TEAM     │                  │
│  │Proposer    │ │Implementer │ │Analyzer    │                  │
│  │Critic      │ │Verifier    │ │Troubleshoot│                  │
│  │Spec-Writer │ │            │ │Editor      │                  │
│  └────────────┘ └────────────┘ └────────────┘                  │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# Initialize a project
ralph init --language Python

# Create a spec
mkdir -p Specs/Active/my-feature
cat > Specs/Active/my-feature/spec.json << 'EOF'
{
  "name": "my-feature",
  "problem": "Need a calculator that can parse and evaluate expressions",
  "success_criteria": "Can evaluate '2 + 3 * 4' correctly"
}
EOF

# Start the pipeline
ralph start my-feature

# Check status
ralph status
```

## User Flow

1. **User proposes feature** → Interface Agent helps draft spec
2. **Spec submitted** → Orchestrator creates directory, starts architecture phase
3. **Architecture Team works** → Proposer designs, Critic reviews
4. **User approval gate** → User reviews architecture, approves/rejects
5. **If non-leaf** → Children created, recurse
6. **If leaf** → Implementation Team works → Implementer codes, Verifier tests
7. **User approval gate** → User reviews code, approves/rejects
8. **Complete** → Notify parent, integrate when all siblings done

## Tech Stack Configuration

Ralph supports multiple languages via tool presets:

```json
{
  "tech_stack": {
    "language": "C#",
    "runtime": "Unity 2022.3",
    "mcp_tools": ["unity"]
  }
}
```

Built-in presets: `python`, `csharp`, `typescript`, `unity`, `godot`, `rust`, `go`

Each preset configures:
- Available tools (Read, Write, Bash, etc.)
- MCP servers (Unity, Godot, etc.)
- Build/test commands
- File patterns

## Hooks

Ralph uses Claude Code hooks for:
- **Scope enforcement**: Agents can only write to allowed paths
- **Message injection**: Pending messages delivered via PreToolUse
- **Artifact tracking**: Files created/modified are logged
- **Audit logging**: All tool uses are recorded

## Directory Structure

```
my-project/
├── ralph.config.json         # Project configuration
├── Specs/
│   └── Active/
│       └── my-feature/
│           ├── spec.json     # Feature spec
│           └── children/     # Child specs (if non-leaf)
├── src/                      # Generated code
└── .ralph/
    ├── state/                # Pipeline state
    └── prompts/              # Custom agent prompts
```

## Spec Schema

```json
{
  "name": "feature-name",
  "problem": "What problem does this solve?",
  "success_criteria": "How do we know it works?",
  "is_leaf": true,
  "classes": [
    {
      "name": "Calculator",
      "kind": "class",
      "responsibility": "Evaluates expressions",
      "location": "src/calculator.py"
    }
  ],
  "acceptance_criteria": [
    {
      "id": "AC-1",
      "behavior": "Evaluates 2+2 to 4"
    }
  ],
  "constraints": {
    "tech_stack": {
      "language": "Python"
    }
  }
}
```

## Installation

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install the Claude Agent SDK
pip3 install claude-agent-sdk

# Install Ralph Pipeline
pip3 install -e Ralph_Pipeline/
```

Or if published:

```bash
pip3 install ralph-pipeline
```

## Requirements

- Python 3.11+
- Claude Code CLI (bundled with claude-agent-sdk)
- API key from [Anthropic Console](https://console.anthropic.com/)

Set your API key:
```bash
export ANTHROPIC_API_KEY=your-api-key
```

## Agent SDK Integration

Ralph uses the [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview) to invoke agents. The SDK provides:

- **Built-in tools**: Read, Write, Edit, Bash, Glob, Grep, WebSearch, etc.
- **MCP servers**: Connect to Unity, Godot, databases, APIs
- **Permission modes**: Control what agents can do autonomously
- **Session management**: Context, compaction, retries

Example agent invocation:

```python
from ralph import AgentRole, Spec, init_orchestrator

# Initialize
orchestrator = init_orchestrator(Path("."))

# Submit a spec
spec_data = {
    "name": "my-feature",
    "problem": "Need a REST API client",
    "success_criteria": "Can GET/POST to endpoints"
}
spec_id = await orchestrator.submit_spec(spec_data)
```

Under the hood, Ralph calls `claude_agent_sdk.query()`:

```python
from claude_agent_sdk import query, ClaudeAgentOptions

async for message in query(
    prompt="Implement the REST client per the spec...",
    options=ClaudeAgentOptions(
        allowed_tools=["Read", "Write", "Edit", "Bash"],
        system_prompt="You are an expert Python developer...",
        permission_mode="acceptEdits",
        mcp_servers={"unity": {...}}  # If Unity project
    )
):
    # Handle streaming messages...
```
