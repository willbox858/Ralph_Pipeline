"""
Command line interface for the Ralph pipeline.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize a new Ralph project."""
    project_dir = Path(args.path)
    
    (project_dir / "Specs" / "Active").mkdir(parents=True, exist_ok=True)
    (project_dir / ".ralph" / "state").mkdir(parents=True, exist_ok=True)
    
    config = {
        "name": project_dir.name,
        "tech_stack": {
            "language": args.language or "Python",
            "test_framework": "pytest" if (args.language or "Python") == "Python" else "",
        },
        "specs_dir": "Specs/Active",
        "max_iterations": 15,
    }
    
    config_file = project_dir / "ralph.config.json"
    if not config_file.exists() or args.force:
        config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
        print(f"Created {config_file}")
    
    print(f"\nRalph project initialized in {project_dir}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Check pipeline status."""
    from .orchestrator import get_orchestrator, init_orchestrator
    
    project_dir = Path(args.path)
    
    try:
        orchestrator = get_orchestrator()
    except RuntimeError:
        orchestrator = init_orchestrator(project_dir)
    
    status = orchestrator.get_status_summary()
    
    print("\n=== Ralph Pipeline Status ===\n")
    s = status["status"]
    print(f"Specs: {s['specs_complete']}/{s['specs_total']} complete")
    
    if status.get("specs"):
        print("\n--- Specs ---")
        for spec in status["specs"]:
            print(f"  {spec['name']}: {spec['phase']}")
    
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    """Start the pipeline on a spec."""
    from .orchestrator import init_orchestrator, PipelineConfig
    
    project_dir = Path(args.path)
    spec_file = project_dir / "Specs" / "Active" / args.spec / "spec.json"
    
    if not spec_file.exists():
        print(f"Spec not found: {spec_file}")
        return 1
    
    with open(spec_file, "r", encoding="utf-8") as f:
        spec_data = json.load(f)
    
    config = PipelineConfig(dry_run=args.dry_run)
    orchestrator = init_orchestrator(project_dir, config=config)
    
    async def run():
        spec_id = await orchestrator.submit_spec(spec_data)
        print(f"Submitted spec: {spec_id}")
    
    asyncio.run(run())
    return 0


def main(argv: Optional[list] = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Ralph Pipeline")
    parser.add_argument("--path", "-p", default=".", help="Project directory")
    
    subparsers = parser.add_subparsers(dest="command")
    
    init_p = subparsers.add_parser("init", help="Initialize project")
    init_p.add_argument("--language", "-l", help="Primary language")
    init_p.add_argument("--force", "-f", action="store_true")
    
    subparsers.add_parser("status", help="Check status")
    
    start_p = subparsers.add_parser("start", help="Start pipeline")
    start_p.add_argument("spec", help="Spec name")
    start_p.add_argument("--dry-run", action="store_true")
    
    args = parser.parse_args(argv)
    
    commands = {"init": cmd_init, "status": cmd_status, "start": cmd_start}
    
    if args.command:
        return commands[args.command](args)
    
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
