# Approve Generated Stubs

Review and approve generated stub files for a spec before implementation begins.

## Arguments

This command accepts a spec path as an argument:
```
/approve-stubs Specs/Active/my-feature/spec.json
```

## When This Is Needed

After the scaffold phase generates stub files, you should review them to:
- Verify file structure and locations are correct
- Check that interface signatures match expectations
- Ensure naming conventions are followed
- Make any necessary adjustments before implementation

## What This Does

1. Lists all stub files defined in the spec
2. Shows stub file contents for review
3. Allows you to edit stubs if needed
4. Marks stubs as approved when ready

## Review Process

### Step 1: List Stub Files

First, identify all stub files for this spec:

```bash
python -c "
from pathlib import Path
import sys; sys.path.insert(0, '.claude/lib')
from stub_approval.reviewer import list_stubs

spec_path = Path('$SPEC_PATH')
stubs = list_stubs(spec_path)

if not stubs:
    print('[!] No stub files found')
    print('    Either stubs have not been generated yet,')
    print('    or the files listed in spec.structure.classes do not exist.')
else:
    print(f'Found {len(stubs)} stub file(s):')
    print()
    for stub in stubs:
        size_kb = stub.size / 1024
        modified = stub.last_modified.strftime('%Y-%m-%d %H:%M')
        print(f'  [ ] {stub.name}')
        print(f'      Path: {stub.path}')
        print(f'      Size: {size_kb:.1f} KB | Modified: {modified}')
        print()
"
```

### Step 2: Review Each Stub

For each stub file, display its contents:

```bash
python -c "
from pathlib import Path
import sys; sys.path.insert(0, '.claude/lib')
from stub_approval.reviewer import list_stubs, read_stub

spec_path = Path('$SPEC_PATH')
stubs = list_stubs(spec_path)

for stub in stubs:
    print('=' * 60)
    print(f'FILE: {stub.name}')
    print(f'PATH: {stub.path}')
    print('=' * 60)
    print()
    content = read_stub(stub.path)
    print(content)
    print()
"
```

### Step 3: Edit If Needed

If any stubs need changes:

1. Use the Edit tool to modify the stub file
2. Common changes include:
   - Adjusting method signatures
   - Adding missing imports
   - Fixing type annotations
   - Adding documentation comments

### Step 4: Approve Stubs

Once all stubs look correct, approve them:

```bash
python -c "
from pathlib import Path
import sys; sys.path.insert(0, '.claude/lib')
from stub_approval.reviewer import approve_stubs

spec_path = Path('$SPEC_PATH')
approve_stubs(spec_path)
print('[OK] Stubs approved for: $SPEC_PATH')
print('     The spec is now ready for implementation.')
"
```

## Verification

After approval, verify the status:

```bash
python -c "
from pathlib import Path
import sys; sys.path.insert(0, '.claude/lib')
from stub_approval.reviewer import get_approval_status

spec_path = Path('$SPEC_PATH')
approved = get_approval_status(spec_path)
status = '[OK] Approved' if approved else '[ ] Not approved'
print(f'Stub approval status: {status}')
"
```

## Status Icons

| Icon | Meaning |
|------|---------|
| [ ] | Not reviewed / Not approved |
| [OK] | Approved and ready |
| [!] | Issue found - needs attention |

## What Happens Next

After stubs are approved:
1. The `stubs_approved` flag is set to `true` in spec.json
2. The orchestrator can proceed with implementation
3. Implementer agents will fill in the stub bodies

## Troubleshooting

**No stub files found:**
- Ensure the scaffold phase has run
- Check that `structure.classes` has valid `location` entries
- Verify paths are relative to project root

**Path resolution issues:**
- Stub locations in spec are relative to project root
- The reviewer looks for .git, .claude, or CLAUDE.md to find root

**Editing stubs:**
- Always use UTF-8 encoding
- Preserve existing structure
- Don't remove interface signatures the implementer needs
