# Ralph Pipeline

A hierarchical, spec-driven development pipeline using Claude agents. Define features as JSON specs, let agents handle implementation.

## Quick Setup

### Bash (Linux/macOS/Git Bash)
```bash
curl -sSL https://raw.githubusercontent.com/willbox858/Ralph_Pipeline/master/setup.sh | bash
```

### PowerShell (Windows)
```powershell
irm https://raw.githubusercontent.com/willbox858/Ralph_Pipeline/master/setup.ps1 | iex
```

### Manual Setup
```bash
# Add as submodule
git submodule add https://github.com/willbox858/Ralph_Pipeline.git .ralph-pipeline

# Create junction/symlink to .claude
# Windows:
cmd /c "mklink /J .claude .ralph-pipeline\.claude"
# Unix:
ln -s .ralph-pipeline/.claude .claude

# Create specs directory
mkdir -p Specs/Active

# Copy and customize CLAUDE.md and STYLE.md from .ralph-pipeline/
```

## Features

- **Spec-Driven Development**: Define features as JSON specs with clear interfaces and criteria
- **Multi-Agent Architecture**: Specialized agents for research, architecture, implementation, and verification
- **Adversarial Loops**: Proposer <-> Critic and Implementer <-> Verifier ensure quality
- **Hierarchical Messaging**: Clean parent-child communication prevents chaos
- **Multi-Language Support**: Tech stack override system for TypeScript, C#, Python, Go, Java, Rust
- **Windows Compatible**: ASCII output, UTF-8 file handling

## Usage

Start Claude Code in your project and run:

```
/orient          # Understand the system and current state
/spec my-feature # Create a new feature spec
/ralph <path>    # Start the pipeline on a spec
/status <path>   # Check pipeline progress
/review <path>   # Handle blocked specs
```

## How It Works

```
1. Define Spec (you + Claude)
   |
2. Research Phase (researcher agent)
   |
3. Architecture Phase (proposer <-> critic loop)
   |
4. If non-leaf: Decompose into children, recurse
   If leaf: Implementation Phase (implementer <-> verifier loop)
   |
5. Integration Tests (when all children complete)
   |
6. Done!
```

## Directory Structure

```
your-project/
├── CLAUDE.md              # Project instructions (customize this)
├── STYLE.md               # Coding conventions (customize this)
├── .claude/               # Pipeline code (symlink to submodule)
├── .ralph-pipeline/       # Pipeline submodule
├── Specs/
│   └── Active/
│       └── my-feature/
│           ├── spec.json
│           ├── research.json
│           └── children/
│               ├── shared/
│               └── component-a/
└── src/                   # Generated source code
```

## Tech Stack Override

Specify language per-spec in `constraints.tech_stack`:

```json
{
  "constraints": {
    "tech_stack": {
      "language": "TypeScript",
      "runtime": "Node.js 20+",
      "frameworks": ["Fastify", "Jest"],
      "rationale": "Async I/O requirements"
    }
  }
}
```

Supported languages: TypeScript, C#, Python, Go, Java, Rust

## Agent Roles

| Agent | Purpose |
|-------|---------|
| Researcher | Finds libraries, patterns, best practices |
| Proposer | Designs system architecture |
| Critic | Reviews and challenges architecture |
| Implementer | Writes code to satisfy spec |
| Verifier | Runs tests, reports failures |
| Coordinator | Routes messages between parent/child |

## Updating the Pipeline

```bash
cd .ralph-pipeline
git pull origin master
cd ..
git add .ralph-pipeline
git commit -m "Update Ralph Pipeline"
```

## Requirements

- Python 3.10+
- Git
- Claude Code CLI

For live mode (API calls):
- `pip install anthropic`
- `ANTHROPIC_API_KEY` environment variable

## License

MIT
