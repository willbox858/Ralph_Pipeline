# Ralph Pipeline Status

Check the current status of the Ralph pipeline.

## Instructions

1. Read the pipeline state from `.ralph/state/`
2. List all active specs and their phases
3. Show any pending approvals
4. Report any errors or blocked specs

## Output Format

Provide a clear summary:

```
=== Ralph Pipeline Status ===

Active Specs: X
- spec-name-1: ARCHITECTURE (iteration 2/15)
- spec-name-2: AWAITING_IMPL_APPROVAL ⚠️ NEEDS REVIEW

Pending Approvals: Y
- spec-name-2: Implementation ready for review

Completed: Z
Failed: W
```

## Check These Files

- `.ralph/state/specs/` - Spec state files
- `.ralph/state/message_bus.json` - Pending messages
- `Specs/Active/*/spec.json` - Spec details
