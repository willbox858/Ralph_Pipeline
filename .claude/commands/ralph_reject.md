# Reject Ralph Spec

Reject a spec and send it back for revision.

## Arguments

- `$ARGUMENTS` - The spec ID/name and feedback for rejection

## Instructions

1. Parse the spec identifier and feedback from arguments
2. Find the spec in `Specs/Active/`
3. Verify it's in an approval phase
4. Record the rejection feedback
5. Reset the phase for another iteration
6. Increment the iteration counter

## Phase Transitions

```
AWAITING_ARCH_APPROVAL → ARCHITECTURE (retry design)
AWAITING_IMPL_APPROVAL → IMPLEMENTATION (retry coding)
AWAITING_INTEG_APPROVAL → INTEGRATION (retry integration)
```

## Output

Confirm the rejection:

```
❌ Rejected: <spec-name>

Feedback recorded:
> <user's feedback here>

Phase reset to: ARCHITECTURE
Iteration: 3/15

The pipeline will retry with your feedback.
```

## Important

- **Feedback is required** - Ask user for specific feedback if not provided
- The feedback becomes part of the error context for the next iteration
- If max iterations reached, spec moves to BLOCKED state
