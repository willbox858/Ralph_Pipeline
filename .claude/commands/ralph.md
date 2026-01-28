# Start Ralph Pipeline

Start the Ralph orchestrator to process a spec.

## Arguments

This command accepts a spec path as an argument:
```
/ralph Specs/Active/my-feature/spec.json
```

## What This Does

1. Validates the spec exists
2. Starts the orchestrator in the background
3. Reports initial status

## Execution

```bash
# Check spec exists
if [ ! -f "$SPEC_PATH" ]; then
    echo "ERROR: Spec not found: $SPEC_PATH"
    exit 1
fi

# Start orchestrator
python .claude/scripts/orchestrator.py \
    --spec "$SPEC_PATH" \
    --live \
    --max-concurrent 5

# The orchestrator will run until complete or blocked
```

## Options

You can modify the command with these flags:
- `--dry-run` - See what would happen without executing
- `--max-concurrent N` - Limit parallel agents (default: 5)
- `--max-iterations N` - Limit impl retries per spec (default: 10)

## After Starting

The pipeline runs autonomously. You can:
- Use `/status` to check progress
- Wait for completion notification
- Intervene if specs are flagged for review

## Example

User: "Build me a calculator with parsing and evaluation"

1. Create the spec structure
2. Run `/ralph Specs/Active/calculator/spec.json`
3. Monitor with `/status Specs/Active/calculator/spec.json`

---

**Note**: Ensure `ANTHROPIC_API_KEY` is set for live execution.
