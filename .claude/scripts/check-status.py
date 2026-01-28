#!/usr/bin/env python3
"""
Check status of spec tree.
Usage:
    python3 check-status.py [--tree] [--json] [--spec PATH]
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from spec import load_spec, Spec


@dataclass
class StatusNode:
    name: str
    path: Path
    status: str
    is_leaf: Optional[bool]
    depends_on: list[str]
    children: list["StatusNode"]
    tests_passed: bool = False
    blocked_by: Optional[str] = None


STATUS_ICONS = {
    "draft": "[d]",
    "ready": "[r]",
    "in_progress": "[~]",
    "complete": "[*]",
    "failed": "[X]",
    "blocked": "[w]",
}


def find_specs_root() -> Path:
    """Find the Specs/Active directory."""
    cwd = Path.cwd()
    
    # Check if we're in a spec directory
    if (cwd / "spec.json").exists():
        return cwd
    
    # Look for Specs/Active
    for parent in [cwd] + list(cwd.parents):
        specs_dir = parent / "Specs" / "Active"
        if specs_dir.exists():
            return specs_dir
    
    return cwd


def build_status_tree(spec_dir: Path, depth: int = 0) -> Optional[StatusNode]:
    """Build a status tree from a spec directory."""
    spec_file = spec_dir / "spec.json"
    
    if not spec_file.exists():
        return None
    
    try:
        spec = load_spec(spec_file)
    except Exception as e:
        return StatusNode(
            name=spec_dir.name,
            path=spec_dir,
            status="error",
            is_leaf=None,
            depends_on=[],
            children=[],
        )
    
    node = StatusNode(
        name=spec.name,
        path=spec_dir,
        status=spec.status,
        is_leaf=spec.is_leaf,
        depends_on=spec.depends_on,
        children=[],
        tests_passed=spec.all_tests_passed,
    )
    
    # Check if blocked by dependencies
    if spec.depends_on:
        children_dir = spec_dir.parent
        for dep in spec.depends_on:
            dep_spec = children_dir / dep / "spec.json"
            if dep_spec.exists():
                try:
                    dep_data = load_spec(dep_spec)
                    if dep_data.status != "complete":
                        node.blocked_by = dep
                        break
                except:
                    pass
    
    # Recursively process children
    children_dir = spec_dir / "children"
    if children_dir.exists():
        for child_dir in sorted(children_dir.iterdir()):
            if child_dir.is_dir():
                child_node = build_status_tree(child_dir, depth + 1)
                if child_node:
                    node.children.append(child_node)
    
    return node


def print_status_tree(node: StatusNode, prefix: str = "", is_last: bool = True, depth: int = 0):
    """Print status tree with nice formatting."""
    connector = "`-- " if is_last else "|-- "
    
    # Determine status display
    if node.blocked_by:
        status_str = f"[w]blocked:{node.blocked_by}"
    else:
        icon = STATUS_ICONS.get(node.status, "?")
        status_str = f"{icon} {node.status}"
    
    # Leaf/non-leaf indicator
    if node.is_leaf is True:
        type_str = "[leaf]"
    elif node.is_leaf is False:
        type_str = "[non-leaf]"
    else:
        type_str = "[?]"
    
    # Special marker for shared
    name_str = node.name
    if node.name == "shared" or node.name == "Shared Types":
        name_str = f"{node.name} *"
    
    print(f"{prefix}{connector}{name_str} {type_str} {status_str}")
    
    # Print children
    new_prefix = prefix + ("    " if is_last else "|   ")
    for i, child in enumerate(node.children):
        is_child_last = (i == len(node.children) - 1)
        print_status_tree(child, new_prefix, is_child_last, depth + 1)


def print_current_status(spec_path: Path):
    """Print status for a single spec."""
    try:
        spec = load_spec(spec_path)
    except Exception as e:
        print(f"Error loading spec: {e}")
        return
    
    print(f"Spec: {spec.name}")
    print(f"Path: {spec_path.parent}")
    print(f"Status: {spec.status}")
    print(f"Type: {'Leaf' if spec.is_leaf else 'Non-leaf' if spec.is_leaf is False else 'Undecided'}")
    
    if spec.depends_on:
        print(f"Depends on: {', '.join(spec.depends_on)}")
    
    if spec.is_leaf:
        print(f"Classes: {len(spec.classes)}")
        print(f"Acceptance criteria: {len(spec.acceptance)}")
        print(f"Tests passed: {spec.all_tests_passed}")
        if spec.ralph_iteration > 0:
            print(f"Ralph iteration: {spec.ralph_iteration}")
    else:
        print(f"Children: {len(spec.children)}")
        print(f"Integration criteria: {len(spec.integration)}")
    
    if spec.constraints.get("open_questions") if hasattr(spec, 'constraints') else spec.open_questions:
        questions = spec.open_questions if hasattr(spec, 'open_questions') else []
        if questions:
            print(f"Open questions: {len(questions)}")


def to_json(node: StatusNode) -> dict:
    """Convert status tree to JSON-serializable dict."""
    return {
        "name": node.name,
        "path": str(node.path),
        "status": node.status,
        "is_leaf": node.is_leaf,
        "depends_on": node.depends_on,
        "blocked_by": node.blocked_by,
        "tests_passed": node.tests_passed,
        "children": [to_json(c) for c in node.children]
    }


def main():
    parser = argparse.ArgumentParser(description="Check spec status")
    parser.add_argument("--tree", action="store_true", help="Show full tree")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--spec", type=str, help="Path to specific spec.json")
    
    args = parser.parse_args()
    
    if args.spec:
        spec_path = Path(args.spec)
        if not spec_path.exists():
            print(f"Spec not found: {spec_path}")
            sys.exit(1)
        
        if args.json:
            spec = load_spec(spec_path)
            from spec import spec_to_dict
            print(json.dumps(spec_to_dict(spec), indent=2))
        else:
            print_current_status(spec_path)
        return
    
    # Find specs root
    root = find_specs_root()
    
    # Check if we're in a spec directory
    if (root / "spec.json").exists():
        if args.tree:
            node = build_status_tree(root)
            if node:
                if args.json:
                    print(json.dumps(to_json(node), indent=2))
                else:
                    print_status_tree(node, "", True, 0)
        else:
            print_current_status(root / "spec.json")
        return
    
    # Show all specs in Active
    print(f"Specs root: {root}")
    print()
    
    specs_found = False
    for spec_dir in sorted(root.iterdir()):
        if spec_dir.is_dir() and (spec_dir / "spec.json").exists():
            specs_found = True
            node = build_status_tree(spec_dir)
            if node:
                if args.json:
                    print(json.dumps(to_json(node), indent=2))
                else:
                    print_status_tree(node, "", True, 0)
                print()
    
    if not specs_found:
        print("No specs found. Use /BuildFeature to create one.")


if __name__ == "__main__":
    main()
