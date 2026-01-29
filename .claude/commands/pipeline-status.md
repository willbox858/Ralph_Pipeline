# Check Ralph Pipeline Status

Check the current status of a Ralph pipeline.

## Arguments

This command accepts a spec path as an argument:
```
/pipeline-status Specs/Active/my-feature/spec.json
```

## What This Shows

- Overall progress (% complete)
- Tree view of all specs with status
- Active/hibernating agents
- Any specs flagged for review

## Execution

```bash
python .claude/scripts/check-pipeline-status.py --root "$SPEC_PATH"
```

## Status Icons

| Icon | Meaning |
|------|---------|
| [x] | Complete |
| [>] | In progress |
| [ ] | Pending |
| [X] | Failed |
| [!] | Blocked (needs review) |
| [z] | Hibernating |
| [m] | Has pending messages |

## Example Output

```
============================================================
RALPH PIPELINE STATUS
Checked at: 2026-01-28 12:34:56
============================================================

Total Specs:   4
[x] Complete:    1
[>] In Progress: 2
[ ] Pending:     1

Progress: [############============================] 25%

SPEC TREE:
----------------------------------------
[ ] calculator [branch]
  [x] shared [leaf] (tests passed)
  [>] parser [leaf] (iter 3)
  [>] evaluator [leaf] (iter 2, [z] hibernating)
```

## Watch Mode

For continuous monitoring:
```bash
python .claude/scripts/check-pipeline-status.py --root "$SPEC_PATH" --watch
```

## JSON Output

For programmatic access:
```bash
python .claude/scripts/check-pipeline-status.py --root "$SPEC_PATH" --json
```
