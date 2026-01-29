# Start Refactoring Pipeline

Analyze existing code and plan incremental refactoring with continuous test validation.

## Arguments

This command accepts a target path as an argument:
```
/refactor src/legacy/processor.py
/refactor src/utils/
/refactor MyClass
```

Target can be:
- A file path: `src/module.py`
- A directory: `src/legacy/`
- A class name: `DataProcessor` (will search for it)

## What This Does

1. Creates a refactor spec in `Specs/Active/refactor-<target>/`
2. Runs the Analyzer agent to examine the code
3. Presents analysis results for user approval
4. Plans incremental transformations with test checkpoints

## Interactive Flow

### Phase 1: Target Identification

```
User: /refactor src/legacy/processor.py

Claude: I'll analyze src/legacy/processor.py for refactoring opportunities.

First, let me understand your goals. What would you like to improve?

[ ] Reduce complexity
[ ] Improve testability
[ ] Extract reusable components
[ ] Modernize patterns
[ ] Other: ___________
```

### Phase 2: Analysis

```
Claude: Running analysis...

[OK] Parsed code structure
  - 2 classes, 8 functions
  - 156 lines of code

[OK] Analyzed dependencies
  - 3 internal imports
  - 5 external imports
  - No circular dependencies

[OK] Discovered test coverage
  - Overall: 72%
  - 2 test groups identified

[OK] Identified refactoring opportunities
  - 3 seam points found
  - 4 refactoring suggestions
```

### Phase 3: Review & Approval

```
Claude: Here's what I found:

## Code Structure
- DataProcessor class (lines 10-150)
  - 4 methods, complexity score: 25
  - Hotspot: _transform() has complexity 15

## Test Coverage
- processor_core group: 95% coverage
- processor_transform group: 45% coverage

## Suggested Refactorings

1. [LOW RISK] Introduce dependency injection in __init__
   - Improves testability
   - Affects: processor_core tests

2. [LOW RISK] Extract 3 methods from _transform()
   - Reduces complexity from 15 to 5
   - Affects: processor_transform tests

3. [MEDIUM RISK] Extract validation logic to separate class
   - Better separation of concerns
   - Affects: processor_core, processor_transform tests

Would you like to proceed with these refactorings?
[ ] Yes, start with suggestion 1
[ ] Yes, start with suggestion 2
[ ] Let me review the full analysis first
[ ] Modify the plan
```

### Phase 4: Incremental Execution

```
Claude: Starting refactoring step 1: Introduce dependency injection

[..] Creating branch: ralph/refactor-processor
[..] Applying change to DataProcessor.__init__
[..] Running processor_core tests...

[OK] All 5 tests passed

Checkpoint reached! Changes committed.

Continue to step 2?
[ ] Yes, continue
[ ] Review changes first
[ ] Stop here
```

## Spec Structure Created

```
Specs/Active/refactor-<target>/
  spec.json           # Refactor spec with analysis
  analysis.json       # Detailed analysis output
  (children/)         # Created if decomposed
```

## Refactor Spec Fields

The spec.json includes refactor-specific fields:

```json
{
  "name": "refactor-processor",
  "status": "in_progress",

  "refactor": {
    "type": "incremental",
    "target": "src/legacy/processor.py",
    "goals": ["reduce_complexity", "improve_testability"],
    "baseline_commit": "abc123",
    "analysis_approved": true,
    "current_step": 1,
    "test_groups": [
      {
        "name": "processor_core",
        "tests": ["test_process", "test_validate"],
        "status": "passing"
      }
    ],
    "steps_completed": [],
    "steps_remaining": ["RO-001", "RO-002"]
  }
}
```

## Key Principles

### 1. Tests Are Checkpoints

Each refactoring step is complete when its TestGroup passes. No predetermined number of steps - the tests determine progress.

### 2. Human Approval Required

- Analysis must be approved before changes begin
- Each step can be reviewed before continuing
- User can stop at any checkpoint

### 3. Safe Rollback

Uses git-worktree-isolation for safe transformations:
- All changes happen in isolated branches
- Easy rollback if tests fail
- Merge only after verification

### 4. Incremental Progress

- Small, focused changes
- Each change is independently valuable
- Can stop at any point with working code

## Refactoring Patterns Supported

| Pattern | Use Case |
|---------|----------|
| Extract Method | Long functions with multiple responsibilities |
| Extract Class | Classes doing too many things |
| Introduce Seam | Making code testable |
| Wrap Method | Adding behavior without modifying |
| Strangler Fig | Gradual module replacement |
| Dependency Injection | Removing hard-coded dependencies |

## After Starting

Monitor progress:
```
/pipeline-status Specs/Active/refactor-<target>/spec.json
```

Review if blocked:
```
/review Specs/Active/refactor-<target>/spec.json
```

## Example Session

```
User: /refactor src/ralph/worktree.py

Claude: I'll analyze src/ralph/worktree.py for refactoring.

What are your goals?
> Improve testability and reduce the size of WorktreeManager

Running analysis...
[OK] Analysis complete

WorktreeManager is 577 lines with 15 methods.
Test coverage: 89% (61 tests)

Top suggestions:
1. Extract git command execution to GitRunner class
2. Extract branch name logic to BranchNaming utility
3. Introduce interface for subprocess calls (testability)

Shall I proceed with #3 first? It enables easier testing
of the other extractions.

User: Yes, start with #3

Claude: Creating isolation branch...
Applying dependency injection for subprocess...
Running worktree tests...

[OK] 61/61 tests passed

Step 1 complete. Ready for step 2?
```

---

**Note**: This command requires:
- Python 3.10+ for ast.end_lineno support
- pytest and pytest-cov for coverage analysis
- git for worktree isolation
