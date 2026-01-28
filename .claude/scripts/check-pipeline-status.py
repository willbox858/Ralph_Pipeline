#!/usr/bin/env python3
"""
Ralph Pipeline Status Checker

This script is called by user-facing Claude to check on pipeline progress.
It reads the state from spec files and provides a summary.

Usage:
    python check-pipeline-status.py --root path/to/spec.json
    python check-pipeline-status.py --root path/to/spec.json --json
    python check-pipeline-status.py --root path/to/spec.json --watch
"""

import argparse
import json
import sys
import time
from pathlib import Path
from datetime import datetime

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

try:
    from spec import load_spec
except ImportError:
    # Fallback if spec module not available
    def load_spec(path):
        return json.loads(Path(path).read_text(encoding='utf-8'))


def gather_status(root_path: Path) -> dict:
    """Recursively gather status from all specs."""
    
    specs = {}
    
    def process_spec(spec_path: Path, depth: int = 0, parent: str = None):
        if not spec_path.exists():
            return
        
        try:
            if hasattr(load_spec, '__module__'):
                spec = load_spec(spec_path)
                spec_dict = {
                    "name": spec.name,
                    "status": spec.status,
                    "is_leaf": spec.is_leaf,
                    "iteration": spec.ralph_iteration,
                    "tests_passed": spec.all_tests_passed,
                    "integration_passed": spec.integration_tests_passed,
                }
            else:
                spec_dict = load_spec(spec_path)
                spec_dict = {
                    "name": spec_dict.get("name", spec_path.parent.name),
                    "status": spec_dict.get("status", "unknown"),
                    "is_leaf": spec_dict.get("structure", {}).get("is_leaf"),
                    "iteration": spec_dict.get("runtime", {}).get("ralph_iteration", 0),
                    "tests_passed": spec_dict.get("runtime", {}).get("all_tests_passed", False),
                    "integration_passed": spec_dict.get("runtime", {}).get("integration_tests_passed", False),
                }
        except Exception as e:
            spec_dict = {
                "name": spec_path.parent.name,
                "status": "error",
                "error": str(e)
            }
        
        spec_dict["depth"] = depth
        spec_dict["parent"] = parent
        spec_dict["path"] = str(spec_path)
        
        name = spec_dict["name"]
        specs[name] = spec_dict
        
        # Check for children
        children_dir = spec_path.parent / "children"
        if children_dir.exists():
            spec_dict["children"] = []
            for child_dir in sorted(children_dir.iterdir()):
                if child_dir.is_dir():
                    child_spec = child_dir / "spec.json"
                    if child_spec.exists():
                        spec_dict["children"].append(child_dir.name)
                        process_spec(child_spec, depth + 1, name)
        
        # Check for research.json
        research_path = spec_path.parent / "research.json"
        spec_dict["has_research"] = research_path.exists()
        
        # Check for messages
        messages_path = spec_path.parent / "messages.json"
        if messages_path.exists():
            try:
                msgs = json.loads(messages_path.read_text(encoding='utf-8'))
                spec_dict["pending_messages"] = len([m for m in msgs.get("inbox", []) if m.get("status") == "pending"])
            except:
                spec_dict["pending_messages"] = 0
        
        # Check for hibernation context
        context_path = spec_path.parent / "agent-context.json"
        spec_dict["hibernating"] = context_path.exists()
    
    process_spec(root_path)
    return specs


def format_status(specs: dict) -> str:
    """Format status as human-readable text."""
    lines = []
    lines.append("=" * 60)
    lines.append("RALPH PIPELINE STATUS")
    lines.append(f"Checked at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 60)
    
    # Summary
    total = len(specs)
    complete = len([s for s in specs.values() if s["status"] == "complete"])
    in_progress = len([s for s in specs.values() if s["status"] == "in_progress"])
    pending = len([s for s in specs.values() if s["status"] in ["pending", "draft"]])
    failed = len([s for s in specs.values() if s["status"] in ["failed", "blocked"]])
    
    lines.append("")
    lines.append(f"Total Specs:   {total}")
    lines.append(f"* Complete:    {complete}")
    lines.append(f"+ In Progress: {in_progress}")
    lines.append(f"o Pending:     {pending}")
    if failed:
        lines.append(f"X Failed:      {failed}")
    lines.append("")

    # Progress bar
    if total > 0:
        pct = int(complete / total * 100)
        bar_len = 40
        filled = int(bar_len * complete / total)
        bar = "#" * filled + "-" * (bar_len - filled)
        lines.append(f"Progress: [{bar}] {pct}%")
        lines.append("")
    
    # Tree view
    lines.append("SPEC TREE:")
    lines.append("-" * 40)
    
    def format_spec(name: str, spec: dict):
        indent = "  " * spec["depth"]
        
        # Status icon
        status_icons = {
            "complete": "*",
            "in_progress": "+",
            "pending": "o",
            "draft": "o",
            "failed": "X",
            "blocked": "!X",
        }
        icon = status_icons.get(spec["status"], "?")

        # Type indicator
        type_str = ""
        if spec["is_leaf"] is True:
            type_str = " [leaf]"
        elif spec["is_leaf"] is False:
            type_str = " [branch]"

        # Extra info
        extras = []
        if spec.get("hibernating"):
            extras.append("zzz hibernating")
        if spec.get("iteration", 0) > 0:
            extras.append(f"iter {spec['iteration']}")
        if spec.get("pending_messages", 0) > 0:
            extras.append(f"msg:{spec['pending_messages']}")
        if spec.get("tests_passed"):
            extras.append("tests ok")
        if spec.get("integration_passed"):
            extras.append("integration ok")
        
        extra_str = f" ({', '.join(extras)})" if extras else ""
        
        return f"{indent}{icon} {name}{type_str}{extra_str}"
    
    # Sort by depth then name for tree view
    sorted_specs = sorted(specs.items(), key=lambda x: (x[1]["depth"], x[0]))
    for name, spec in sorted_specs:
        lines.append(format_spec(name, spec))
    
    # Issues section
    issues = []
    for name, spec in specs.items():
        if spec["status"] in ["failed", "blocked"]:
            issues.append(f"  - {name}: {spec['status']}")
        if spec.get("error"):
            issues.append(f"  - {name}: {spec['error']}")
    
    if issues:
        lines.append("")
        lines.append("! ISSUES:")
        lines.extend(issues)
    
    lines.append("")
    lines.append("=" * 60)
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Check Ralph pipeline status")
    parser.add_argument("--root", required=True, help="Path to root spec.json")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--watch", action="store_true", help="Continuously watch status")
    parser.add_argument("--interval", type=int, default=5, help="Watch interval in seconds")
    
    args = parser.parse_args()
    
    root_path = Path(args.root)
    if not root_path.exists():
        print(f"ERROR: Spec not found: {root_path}")
        sys.exit(1)
    
    def show_status():
        specs = gather_status(root_path)
        
        if args.json:
            print(json.dumps(specs, indent=2))
        else:
            print(format_status(specs))
    
    if args.watch:
        try:
            while True:
                # Clear screen
                print("\033[2J\033[H", end="")
                show_status()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped watching")
    else:
        show_status()


if __name__ == "__main__":
    main()
