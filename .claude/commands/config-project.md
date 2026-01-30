# Configure Project

Set up Ralph configuration for this project.

## What This Creates

1. **`ralph.verifier.json`** - Tells agents how to run tests
2. **`STYLE.md`** (optional) - Code style guide for agents

## Step 1: Detect Current Setup

First, look for existing configuration:

```bash
python -c "
from pathlib import Path
import json

root = Path('.')
found = []

# Check for ralph config
if (root / 'ralph.verifier.json').exists():
    found.append('[OK] ralph.verifier.json exists')
else:
    found.append('[ ] ralph.verifier.json - MISSING')

# Check for style guide
if (root / 'STYLE.md').exists():
    found.append('[OK] STYLE.md exists')
else:
    found.append('[ ] STYLE.md - optional')

# Detect project type
indicators = {
    'Unity': ['Assets', 'ProjectSettings'],
    'Unreal': ['Source', 'Config'],
    'Python': ['pyproject.toml', 'setup.py', 'requirements.txt'],
    'Node.js': ['package.json'],
    'C++': ['CMakeLists.txt'],
    'C#': ['*.csproj', '*.sln'],
}

detected = []
for proj_type, markers in indicators.items():
    for marker in markers:
        if '*' in marker:
            if list(root.glob(marker)):
                detected.append(proj_type)
                break
        elif (root / marker).exists():
            detected.append(proj_type)
            break

print('Current configuration:')
for f in found:
    print(f'  {f}')
print()
if detected:
    print(f'Detected project type(s): {', '.join(set(detected))}')
else:
    print('Could not auto-detect project type')
"
```

## Step 2: Ask About Project Type

Ask the user:

**What type of project is this?**
- Python (pytest, unittest)
- Unity (C# with Unity Test Framework)
- Unreal (C++ with Automation System)
- C++ (Google Test, Catch2, etc.)
- Node.js/TypeScript (Jest, Vitest, Mocha)
- Other

## Step 3: Ask About Test Configuration

Based on project type, ask relevant questions:

### For Unity:
- Do you have MCP configured for Unity? (required for running tests)
- Which test modes? EditMode, PlayMode, or both?
- Any specific test assemblies to target?

### For Python:
- pytest or unittest?
- Where are tests located? (tests/, test/, etc.)
- Any coverage requirements?

### For Unreal:
- Using the Automation System?
- Module names for tests?

### For C++:
- Which test framework? (Google Test, Catch2, doctest)
- How are tests built? (CMake target name)

### For Node.js/TypeScript:
- Which test runner? (Jest, Vitest, Mocha)
- Test command? (npm test, npx jest, etc.)

## Step 4: Generate Configuration

Based on answers, create `ralph.verifier.json`:

### Unity Example:
```json
{
  "project_type": "unity",
  "test_method": "unity_mcp",
  "unity": {
    "test_modes": ["EditMode"],
    "assembly_names": [],
    "timeout_seconds": 300
  },
  "file_verification": {
    "required_extensions": [".cs"]
  }
}
```

### Python Example:
```json
{
  "project_type": "python",
  "test_method": "cli",
  "test_command": "pytest",
  "test_paths": ["tests/"],
  "file_verification": {
    "required_extensions": [".py"]
  }
}
```

### Unreal Example:
```json
{
  "project_type": "unreal",
  "test_method": "cli",
  "test_command": "UnrealEditor-Cmd.exe <project> -ExecCmds=\"Automation RunTests <filter>\" -unattended -nopause",
  "unreal": {
    "test_filter": "Project.",
    "modules": []
  },
  "file_verification": {
    "required_extensions": [".cpp", ".h"]
  }
}
```

### C++ Example:
```json
{
  "project_type": "cpp",
  "test_method": "cli",
  "test_command": "ctest --output-on-failure",
  "build_command": "cmake --build build",
  "file_verification": {
    "required_extensions": [".cpp", ".h", ".hpp"]
  }
}
```

### Node.js/TypeScript Example:
```json
{
  "project_type": "typescript",
  "test_method": "cli",
  "test_command": "npm test",
  "file_verification": {
    "required_extensions": [".ts", ".tsx"]
  }
}
```

## Step 5: Write the File

After confirming with the user, write the config:

```python
import json
from pathlib import Path

config = {
    # ... built from user answers
}

Path('ralph.verifier.json').write_text(
    json.dumps(config, indent=2),
    encoding='utf-8'
)
print('[OK] Created ralph.verifier.json')
```

## Step 6: STYLE.md (Optional)

Ask if user wants to create/update STYLE.md with project conventions:
- Naming conventions
- Code patterns to follow
- Patterns to avoid
- Formatting preferences

If yes, help them write it based on their preferences.

## Verification

After setup, verify the configuration:

```bash
python -c "
from pathlib import Path
import json

config_path = Path('ralph.verifier.json')
if config_path.exists():
    config = json.loads(config_path.read_text())
    print('[OK] ralph.verifier.json')
    print(f'    Project type: {config.get(\"project_type\")}')
    print(f'    Test method: {config.get(\"test_method\")}')
    if config.get('test_command'):
        print(f'    Test command: {config.get(\"test_command\")}')
else:
    print('[!] ralph.verifier.json not found')
"
```

## What Happens Next

With `ralph.verifier.json` in place:
1. Verifier agents will use your test configuration
2. Tests will run with the correct framework/command
3. Unity projects will use MCP tools instead of CLI

You can now run `/ralph` on specs and agents will know how to verify implementations.
