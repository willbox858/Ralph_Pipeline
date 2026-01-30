# Approve Ralph Spec

Approve a spec that's awaiting user review.

## Arguments

- `$ARGUMENTS` - The spec ID or name to approve

## Instructions

1. Parse the spec identifier from arguments
2. Find the spec in `Specs/Active/`
3. Verify it's in an approval phase:
   - `AWAITING_ARCH_APPROVAL` - Architecture review
   - `AWAITING_IMPL_APPROVAL` - Implementation review  
   - `AWAITING_INTEG_APPROVAL` - Integration review
4. Update the spec's phase to continue the pipeline
5. Log the approval

## Phase Transitions

```
AWAITING_ARCH_APPROVAL → IMPLEMENTATION (if leaf) or DECOMPOSING (if parent)
AWAITING_IMPL_APPROVAL → COMPLETE
AWAITING_INTEG_APPROVAL → COMPLETE
```

## Output

Confirm the approval:

```
✅ Approved: <spec-name>

Previous phase: AWAITING_IMPL_APPROVAL
New phase: COMPLETE

The pipeline will continue processing.
```

## If No Spec ID Provided

List specs awaiting approval and ask user to specify which one.
