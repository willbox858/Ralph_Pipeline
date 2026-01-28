#!/usr/bin/env python3
"""
PreToolUse hook - Enforces file scope based on spec.json.

Agents can only modify files listed in structure.classes[].location.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))


def get_spec_dir() -> Path:
    """Find nearest spec.json directory."""
    cwd = Path(os.getcwd())
    
    for parent in [cwd] + list(cwd.parents):
        if (parent / "spec.json").exists():
            return parent
    
    return cwd


def get_allowed_locations(spec_path: Path) -> list[str]:
    """Get allowed file locations from spec."""
    try:
        from spec import load_spec
        spec = load_spec(spec_path)
        return [c.location for c in spec.classes if c.location]
    except:
        # Fallback: parse directly
        try:
            data = json.loads(spec_path.read_text())
            classes = data.get("structure", {}).get("classes", [])
            return [c.get("location", "") for c in classes if c.get("location")]
        except:
            return []


def is_test_file(path: str) -> bool:
    """Check if path is a test file."""
    path_lower = path.lower()
    return (
        "/test" in path_lower or
        "/tests" in path_lower or
        "test_" in path_lower or
        "_test." in path_lower or
        ".test." in path_lower or
        ".spec." in path_lower
    )


def is_spec_file(path: str) -> bool:
    """Check if path is a spec/config file."""
    name = Path(path).name.lower()
    return name in {"spec.json", "state.json", "errors.json"} or "/.claude/" in path.lower()


def main():
    data = json.load(sys.stdin)
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    
    # Only check write operations
    if tool_name.lower() not in {"write", "edit", "create", "str_replace", "str_replace_editor"}:
        print(json.dumps({"decision": "allow"}))
        return
    
    file_path = tool_input.get("file_path") or tool_input.get("path") or ""
    
    # Always allow test files
    if is_test_file(file_path):
        print(json.dumps({"decision": "allow"}))
        return
    
    # Always allow spec/config files
    if is_spec_file(file_path):
        print(json.dumps({"decision": "allow"}))
        return
    
    # Find spec
    spec_dir = get_spec_dir()
    spec_path = spec_dir / "spec.json"
    
    if not spec_path.exists():
        # No spec context, allow
        print(json.dumps({"decision": "allow"}))
        return
    
    # Get allowed locations
    allowed = get_allowed_locations(spec_path)
    
    if not allowed:
        # No classes defined (non-leaf spec), only allow tests
        print(json.dumps({
            "decision": "block",
            "reason": f"""SCOPE VIOLATION

This spec has no classes defined (non-leaf spec).
Only test files can be modified at this level.

File: {file_path}

Navigate to a leaf spec to implement source files.
"""
        }))
        return
    
    # Check if file is in allowed locations
    file_path_normalized = file_path.replace("\\", "/")
    
    for loc in allowed:
        loc_normalized = loc.replace("\\", "/")
        if file_path_normalized.endswith(loc_normalized) or loc_normalized in file_path_normalized:
            print(json.dumps({"decision": "allow"}))
            return
    
    print(json.dumps({
        "decision": "block",
        "reason": f"""SCOPE VIOLATION

File is not in spec's allowed locations.

File: {file_path}

Allowed locations (from structure.classes):
{chr(10).join(f'  - {loc}' for loc in allowed)}

Update spec.json if this file needs modification.
"""
    }))


if __name__ == "__main__":
    main()
