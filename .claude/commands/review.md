# Review Flagged Specs

Handle specs that have been flagged for human review.

## When This Is Needed

Specs get flagged when:
- Implementation fails after max iterations
- Integration tests fail
- Agent requests human decision
- Unresolvable dependency conflicts

## Usage

```
/review Specs/Active/my-feature/spec.json
```

## What This Shows

1. Which specs are blocked/failed
2. Why they were flagged
3. Error details and context
4. Options for resolution

## Review Process

### 1. Check Status First
```bash
python .claude/scripts/check-pipeline-status.py --root "$SPEC_PATH" --json
```

Look for specs with `"phase": "blocked"` or `"phase": "failed"`.

### 2. Examine the Flagged Spec

Navigate to the spec directory and check:
- `spec.json` - Current spec state, errors field
- `research.json` - What research was done
- `messages.json` - Any pending messages
- `agent-context.json` - If hibernating, what state

### 3. Common Issues & Fixes

**Implementation keeps failing:**
- Check `spec.errors` for the actual failures
- Review the acceptance criteria - too strict?
- Check research.json - wrong library recommendation?
- Simplify the spec and re-run

**Integration tests failing:**
- Check how children interact
- Look for interface mismatches
- May need to add shared types

**Agent stuck waiting:**
- Check `agent-context.json` for `resume_trigger`
- Manually resolve and clear the hibernation

### 4. Resolution Options

**Option A: Fix and Retry**
```bash
# Edit the spec
vim Specs/Active/my-feature/children/parser/spec.json

# Reset status
# Set "status": "pending", clear errors

# Re-run
python .claude/scripts/orchestrator.py --spec "$SPEC_PATH" --live
```

**Option B: Simplify Scope**
- Reduce acceptance criteria
- Split into smaller specs
- Mark some criteria as "stretch goals"

**Option C: Manual Implementation**
- Implement the failing piece yourself
- Mark spec as complete
- Continue pipeline

**Option D: Abandon Subtree**
- If fundamentally broken
- Document why
- Consider alternative approach

## After Resolution

1. Clear the blocked/failed status
2. Re-run `/ralph` to continue
3. Monitor with `/status`

## Prevention Tips

- Start with simpler specs
- Use `--dry-run` first
- Check research.json quality
- Set reasonable iteration limits
