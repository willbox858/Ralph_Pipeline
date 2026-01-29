#!/usr/bin/env python3
"""
Stub reviewer - Helper functions for reviewing and approving generated stubs.
Location: src/stub_approval/reviewer.py
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .types import StubInfo


def list_stubs(spec_path: Path) -> list[StubInfo]:
    """List all stub files defined in a spec.

    Reads the spec.json and returns StubInfo for each file listed in
    structure.classes that exists on disk.

    Args:
        spec_path: Path to the spec.json file.

    Returns:
        List of StubInfo objects for existing stub files.

    Raises:
        FileNotFoundError: If spec_path does not exist.
        json.JSONDecodeError: If spec.json is invalid JSON.
    """
    if not spec_path.exists():
        raise FileNotFoundError(f"Spec not found: {spec_path}")

    data = json.loads(spec_path.read_text(encoding='utf-8'))

    # Get project root (where spec files are relative to)
    # Assume spec is in Specs/Active/feature/spec.json or similar
    # and stub locations are relative to project root
    project_root = _find_project_root(spec_path)

    stubs: list[StubInfo] = []
    classes = data.get("structure", {}).get("classes", [])

    for class_def in classes:
        location = class_def.get("location", "")
        if not location:
            continue

        # Resolve the stub file path
        stub_path = project_root / location

        if stub_path.exists():
            stat = stub_path.stat()
            stubs.append(StubInfo(
                path=stub_path,
                name=stub_path.name,
                size=stat.st_size,
                last_modified=datetime.fromtimestamp(stat.st_mtime)
            ))

    return stubs


def read_stub(path: Path) -> str:
    """Read the content of a stub file.

    Args:
        path: Path to the stub file.

    Returns:
        The file content as a string.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Stub file not found: {path}")

    return path.read_text(encoding='utf-8')


def approve_stubs(spec_path: Path) -> bool:
    """Mark stubs as approved in the spec.

    Sets stubs_approved=true in the spec.json file.

    Args:
        spec_path: Path to the spec.json file.

    Returns:
        True if approval was successful.

    Raises:
        FileNotFoundError: If spec_path does not exist.
        json.JSONDecodeError: If spec.json is invalid JSON.
    """
    if not spec_path.exists():
        raise FileNotFoundError(f"Spec not found: {spec_path}")

    # Read current spec
    data = json.loads(spec_path.read_text(encoding='utf-8'))

    # Set approval flag at root level
    data["stubs_approved"] = True

    # Write back with preserved formatting
    spec_path.write_text(json.dumps(data, indent=2), encoding='utf-8')

    return True


def get_approval_status(spec_path: Path) -> bool:
    """Check if stubs have been approved for a spec.

    Args:
        spec_path: Path to the spec.json file.

    Returns:
        True if stubs_approved is set to true, False otherwise.

    Raises:
        FileNotFoundError: If spec_path does not exist.
    """
    if not spec_path.exists():
        raise FileNotFoundError(f"Spec not found: {spec_path}")

    data = json.loads(spec_path.read_text(encoding='utf-8'))
    return data.get("stubs_approved", False)


def _find_project_root(spec_path: Path) -> Path:
    """Find the project root directory from a spec path.

    Walks up the directory tree looking for common project markers
    like .git, pyproject.toml, or .claude directory.

    Args:
        spec_path: Path to a spec.json file.

    Returns:
        The project root directory, or the spec's parent if not found.
    """
    markers = [".git", "pyproject.toml", ".claude", "CLAUDE.md"]

    current = spec_path.parent
    while current != current.parent:  # Stop at filesystem root
        for marker in markers:
            if (current / marker).exists():
                return current
        current = current.parent

    # Fallback to spec's parent directory
    return spec_path.parent
