# Ralph Pipeline Setup

This guide covers the dependencies and setup required to run the Ralph Pipeline.

## Prerequisites

- **Python 3.10+**
- **Claude Code** (runtime for the Agent SDK)
- **Anthropic account** with API access

---

## Step 1: Install Claude Code

The Agent SDK requires Claude Code as its runtime. Install it first:

### Windows (WinGet)
```powershell
winget install Anthropic.ClaudeCode
```

### macOS/Linux/WSL
```bash
curl -fsSL https://claude.ai/install.sh | bash
```

### Homebrew (macOS)
```bash
brew install --cask claude-code
```

After installation, **authenticate by running**:
```bash
claude
```

Follow the prompts to log in. The SDK will use this authentication automatically.

---

## Step 2: Install Python Dependencies

### Option A: Using pip (recommended)

Create a virtual environment and install dependencies:

```bash
# Create and activate virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

# Install dependencies
pip install claude-agent-sdk mcp
```

### Option B: Using uv (faster)

If you have [uv](https://docs.astral.sh/uv/) installed:

```bash
uv add claude-agent-sdk mcp
```

---

## Step 3: API Key (Optional)

If you've authenticated Claude Code (Step 1), the SDK uses that authentication automatically.

Otherwise, set your API key:

```bash
# Create .env file
echo "ANTHROPIC_API_KEY=your-api-key" > .env
```

Get your API key from the [Claude Console](https://platform.claude.com/).

---

## Step 4: Verify Installation

Test that everything is working:

```bash
# Test Python imports
python -c "from claude_agent_sdk import query; print('Agent SDK: OK')"
python -c "from mcp.server import Server; print('MCP: OK')"

# Test Ralph modules
cd /path/to/Ralph_Pipeline
python -c "
import sys
sys.path.insert(0, '.claude/lib')
from ralph_db import get_db
from hooks import load_agent_config
from message_hooks import merge_hooks
print('Ralph modules: OK')
"
```

---

## Running the Pipeline

### Start the orchestrator (live mode)

```bash
python .claude/scripts/orchestrator.py --spec Specs/Active/your-feature/spec.json --live
```

### Dry run (no actual agent calls)

```bash
python .claude/scripts/orchestrator.py --spec Specs/Active/your-feature/spec.json --dry-run
```

### Simulated mode (for testing)

```bash
python .claude/scripts/orchestrator.py --spec Specs/Active/your-feature/spec.json
```

---

## Troubleshooting

### "Claude Code not found"

1. Install Claude Code (see Step 1)
2. Restart your terminal
3. Verify: `claude --version`

### "API key not found"

1. Run `claude` and authenticate, OR
2. Set `ANTHROPIC_API_KEY` in your environment or `.env` file

### "ModuleNotFoundError: No module named 'claude_agent_sdk'"

```bash
pip install claude-agent-sdk
```

### "ModuleNotFoundError: No module named 'mcp'"

```bash
pip install mcp
```

### Import errors in Ralph modules

Make sure you're running from the project root:

```bash
cd /path/to/Ralph_Pipeline
python .claude/scripts/orchestrator.py --spec ...
```

---

## Dependencies Summary

| Package | Purpose | Install |
|---------|---------|---------|
| `claude-agent-sdk` | Agent SDK for spawning Claude agents | `pip install claude-agent-sdk` |
| `mcp` | MCP server for status tools | `pip install mcp` |
| Claude Code | Runtime for Agent SDK | `winget install Anthropic.ClaudeCode` |

---

## More Information

- [Claude Agent SDK Docs](https://platform.claude.com/docs/en/agent-sdk/quickstart)
- [Claude Code Setup](https://code.claude.com/docs/en/setup)
- [MCP Documentation](https://modelcontextprotocol.io/)
