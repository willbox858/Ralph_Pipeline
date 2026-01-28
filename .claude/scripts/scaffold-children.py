#!/usr/bin/env python3
"""
Scaffold child specs from a non-leaf spec.
Usage:
    python3 scaffold-children.py --spec ./spec.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from spec import load_spec, save_spec, create_child_spec, create_shared_spec, Spec


def scaffold_children(spec_path: Path, skip_shared: bool = False) -> list[Path]:
    """Create child spec directories and files from parent spec."""
    
    spec = load_spec(spec_path)
    spec_dir = spec_path.parent
    children_dir = spec_dir / "children"
    
    if spec.is_leaf:
        print(f"Error: {spec.name} is a leaf spec (cannot have children)")
        sys.exit(1)
    
    if not spec.children:
        print(f"Error: {spec.name} has no children defined in structure.children")
        sys.exit(1)
    
    children_dir.mkdir(exist_ok=True)
    created = []
    
    # Create shared/ first if there are shared types
    if spec.shared_types and not skip_shared:
        shared_dir = children_dir / "shared"
        shared_dir.mkdir(exist_ok=True)
        shared_path = shared_dir / "spec.json"
        
        if not shared_path.exists():
            shared_spec = create_shared_spec(spec, shared_path)
            save_spec(shared_spec, shared_path)
            created.append(shared_path)
            print(f"* Created: shared/ (contains {len(spec.shared_types)} shared types)")
    
    # Create other children
    for child_def in spec.children:
        child_dir = children_dir / child_def.name
        child_dir.mkdir(exist_ok=True)
        child_path = child_dir / "spec.json"
        
        if not child_path.exists():
            child_spec = create_child_spec(spec, child_def, child_path)
            
            # If parent has shared types, child depends on shared
            if spec.shared_types and "shared" not in child_spec.depends_on:
                child_spec.depends_on.insert(0, "shared")
            
            save_spec(child_spec, child_path)
            created.append(child_path)
            
            deps_str = f" (depends on: {', '.join(child_spec.depends_on)})" if child_spec.depends_on else ""
            print(f"* Created: {child_def.name}/{deps_str}")
        else:
            print(f"  Skipped: {child_def.name}/ (already exists)")
    
    return created


def main():
    parser = argparse.ArgumentParser(description="Scaffold child specs")
    parser.add_argument("--spec", required=True, help="Path to parent spec.json")
    parser.add_argument("--skip-shared", action="store_true", help="Don't create shared/ child")
    
    args = parser.parse_args()
    
    spec_path = Path(args.spec)
    if not spec_path.exists():
        print(f"Spec not found: {spec_path}")
        sys.exit(1)
    
    print(f"Scaffolding children for: {spec_path.parent.name}")
    print()
    
    created = scaffold_children(spec_path, args.skip_shared)
    
    print()
    print(f"Created {len(created)} child spec(s)")
    
    if created:
        # Check for shared dependency
        spec = load_spec(spec_path)
        if spec.shared_types:
            print()
            print("!  shared/ must be completed first (other children depend on it)")
            print(f"   Navigate: cd {spec_path.parent}/children/shared")


if __name__ == "__main__":
    main()
