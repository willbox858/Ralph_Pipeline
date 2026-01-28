# Ralph v2 - Complete Package

A hierarchical development pipeline using JSON-based specs, adversarial agent loops, and hierarchical messaging.

## Features

- **Adversarial Architecture**: Proposer ↔ Critic loop catches design flaws before implementation
- **Adversarial Implementation**: Implementer ↔ Verifier loop ensures code meets spec
- **Hierarchical Messaging**: Parent ↔ Child communication only (no peer chaos)
- **Style Enforcement**: STYLE.md defines conventions for all agents
- **Safety Limits**: Depth, cost, and agent caps prevent runaway execution

## Quick Start

1. **Copy contents to your project root**

2. **Edit STYLE.md** with your conventions

3. **Start a session**
   ```
   /Orient
   ```

4. **Create a feature**
   ```
   /BuildFeature my-feature
   ```

5. **Define the spec** (collaboratively)

6. **Implement**
   ```
   /ImplementAll
   ```

## Directory Structure

```
your-project/
├── CLAUDE.md              # Orchestrator instructions
├── STYLE.md               # Your coding conventions (EDIT THIS)
├── .claude/
│   ├── settings.json      # Hook configuration
│   ├── hooks/             # Guard hooks
│   ├── scripts/
│   │   ├── ralph-recursive.py   # Main engine
│   │   ├── check-status.py      # /Orient, /Status
│   │   ├── scaffold-children.py # /Scaffold
│   │   └── init-orchestrator.py
│   ├── agents/
│   │   ├── proposer.md    # Designs architecture
│   │   ├── critic.md      # Reviews architecture
│   │   ├── implementer.md # Writes code
│   │   ├── verifier.md    # Tests code
│   │   ├── coordinator.md # Routes messages
│   │   └── spec-writer.md # Helps write specs
│   ├── lib/
│   │   └── spec.py        # Spec parsing library
│   ├── schema/
│   │   ├── spec-schema.json
│   │   └── message-schema.json
│   └── templates/
│       └── spec-template.json
└── Specs/
    └── Active/
        └── my-feature/
            ├── spec.json
            ├── messages.json   # Parent's inbox/outbox
            └── children/
                ├── shared/
                └── component-a/
```

## Agent Roles

| Agent | Loop Partner | Role |
|-------|--------------|------|
| Proposer | Critic | Designs system structure |
| Critic | Proposer | Reviews architecture proposals |
| Implementer | Verifier | Writes code |
| Verifier | Implementer | Runs tests, reports failures |
| Coordinator | — | Routes messages between levels |

## Adversarial Loops

### Architecture Loop (Proposer ↔ Critic)

```
Proposer creates architecture proposal
         ↓
Critic reviews proposal
         ↓
    Approved? ──→ Yes ──→ Proceed to implementation
         ↓
        No
         ↓
Proposer revises based on critique
         ↓
    (repeat until approved or max iterations)
```

### Implementation Loop (Implementer ↔ Verifier)

```
Implementer writes code
         ↓
Verifier runs tests
         ↓
    Pass? ──→ Yes ──→ Mark complete
         ↓
        No
         ↓
Implementer fixes based on errors
         ↓
    (repeat until pass or max iterations)
```

## Messaging System

Agents communicate only with direct parent/children—never peers.

### Message Types

| Type | Direction | Purpose |
|------|-----------|---------|
| `need_shared_type` | Child → Parent | Request cross-cutting type |
| `dependency_issue` | Child → Parent | Report blocker |
| `proceed` | Parent → Child | Dependency ready, start work |
| `spec_update` | Parent → Child | Parent modified your spec |

### Example Flow

```
1. Parser discovers: "I need Token type for output"
2. Parser → Parent: { type: "need_shared_type", name: "Token" }
3. Parent adds Token to shared_types
4. Parent → Shared: "Add Token"
5. Shared implements Token
6. Parent → Parser: { type: "proceed" }
```

## Style Guide (STYLE.md)

Edit `STYLE.md` to define your conventions. Agents will follow them.

```markdown
## Code Style
- Naming: PascalCase for public, _camelCase for private
- Formatting: Allman braces, 4-space indent

## Architecture Style
- Prefer composition over inheritance
- Keep classes under 200 lines

## Anti-Patterns to Avoid
- God classes
- Deep inheritance
```

## Commands

| Command | Description |
|---------|-------------|
| `/Orient` | Show current location and status |
| `/BuildFeature name` | Start new feature spec |
| `/Status` | Show full spec tree |
| `/Scaffold` | Create children from non-leaf spec |
| `/Implement` | Run Ralph on current leaf |
| `/ImplementAll` | Recursive implementation |

## Running Ralph

### Dry Run (see what would happen)
```bash
python3 .claude/scripts/ralph-recursive.py --spec spec.json --dry-run
```

### Simulated (no API calls)
```bash
python3 .claude/scripts/ralph-recursive.py --spec spec.json
```

### Live (actually calls API)
```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 .claude/scripts/ralph-recursive.py --spec spec.json --live --confirm-each
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--dry-run` | false | Print actions without executing |
| `--live` | false | Actually call Anthropic API |
| `--max-depth` | 3 | Max recursion depth |
| `--max-iterations` | 10 | Max impl iterations per leaf |
| `--max-arch-iterations` | 5 | Max architecture iterations |
| `--max-agents` | 50 | Total agent spawn limit |
| `--max-cost` | 50.0 | Cost limit in USD |
| `--confirm-each` | false | Confirm each agent spawn |

## Spec Format

```json
{
  "name": "Feature Name",
  "status": "draft",
  
  "overview": {
    "problem": "What this solves",
    "success": "Success criteria"
  },
  
  "interfaces": {
    "provides": [{"name": "IFoo", "members": [...]}],
    "requires": [{"name": "IBar", "source": "external"}],
    "shared_types": [{"name": "Token", "kind": "record"}]
  },
  
  "structure": {
    "is_leaf": true,
    "classes": [
      {"name": "Foo", "type": "class", "location": "src/Foo.cs"}
    ],
    "children": []
  },
  
  "criteria": {
    "acceptance": [{"id": "AC-001", "behavior": "...", "test": "..."}],
    "integration": []
  }
}
```

## Safety Features

- **Orchestrator Guard**: Blocks source file modifications from orchestrator
- **Scope Guard**: Restricts agents to files defined in spec
- **Cost Tracking**: Estimates API cost, stops at limit
- **Depth Limit**: Prevents infinite recursion
- **Confirmation Gates**: Optional manual approval for each spawn

## Requirements

- Python 3.10+
- `anthropic` package (for live mode): `pip install anthropic`
- `ANTHROPIC_API_KEY` environment variable (for live mode)

## Troubleshooting

**"Spec not ready"**
- Check `constraints.open_questions` is empty
- Verify all required fields are filled

**"Architecture loop exhausted"**
- Proposer and Critic couldn't agree
- Review the proposals in spec directory
- May need human intervention on architecture

**"Blocked by dependency"**
- Check `runtime.depends_on`
- Complete that sibling first

**"Scope violation"**
- File not in `structure.classes`
- Update spec or navigate to correct spec
