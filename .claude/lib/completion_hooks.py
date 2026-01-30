#!/usr/bin/env python3
"""
Completion Hooks - Post-spec-completion actions.
Location: lib/completion_hooks.py

Hooks run after a spec completes successfully. They can:
- Copy files to final destinations
- Update imports
- Run integration scripts
- Consolidate multi-child outputs
"""

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable


@dataclass
class CopyHook:
    """Copy files from spec output to a destination."""
    source_pattern: str  # Glob pattern relative to spec dir, e.g., "src/**/*.py"
    destination: str     # Destination directory, e.g., ".claude/lib/"
    flatten: bool = False  # If True, copy all files to dest root (no subdirs)
    overwrite: bool = True


@dataclass
class CommandHook:
    """Run a shell command after completion."""
    command: str
    working_dir: Optional[str] = None  # Relative to project root
    continue_on_error: bool = False


@dataclass
class ConsolidateHook:
    """Consolidate outputs from child specs into a single location."""
    children: list[str]  # Child spec names to consolidate from
    source_subdir: str   # Subdir within each child's output, e.g., "src/"
    destination: str     # Where to consolidate, e.g., "src/combined/"


@dataclass
class CompletionHooks:
    """Collection of hooks to run after spec completion."""
    copy: list[CopyHook] = field(default_factory=list)
    commands: list[CommandHook] = field(default_factory=list)
    consolidate: list[ConsolidateHook] = field(default_factory=list)


def load_hooks_from_spec(spec_path: Path) -> Optional[CompletionHooks]:
    """
    Load completion hooks from a spec's hooks.json file.

    Looks for {spec_dir}/hooks.json
    """
    hooks_file = spec_path.parent / "hooks.json"
    if not hooks_file.exists():
        return None

    try:
        data = json.loads(hooks_file.read_text(encoding='utf-8'))
        return parse_hooks(data)
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Warning: Failed to parse {hooks_file}: {e}")
        return None


def parse_hooks(data: dict) -> CompletionHooks:
    """Parse hooks JSON into CompletionHooks object."""
    hooks = CompletionHooks()

    for copy_data in data.get("copy", []):
        hooks.copy.append(CopyHook(
            source_pattern=copy_data.get("source_pattern", ""),
            destination=copy_data.get("destination", ""),
            flatten=copy_data.get("flatten", False),
            overwrite=copy_data.get("overwrite", True),
        ))

    for cmd_data in data.get("commands", []):
        hooks.commands.append(CommandHook(
            command=cmd_data.get("command", ""),
            working_dir=cmd_data.get("working_dir"),
            continue_on_error=cmd_data.get("continue_on_error", False),
        ))

    for cons_data in data.get("consolidate", []):
        hooks.consolidate.append(ConsolidateHook(
            children=cons_data.get("children", []),
            source_subdir=cons_data.get("source_subdir", "src/"),
            destination=cons_data.get("destination", ""),
        ))

    return hooks


def find_project_root(start_path: Path) -> Optional[Path]:
    """Find project root by looking for .claude or .git directory."""
    current = start_path.resolve()
    for _ in range(15):
        if (current / ".claude").is_dir() or (current / ".git").is_dir():
            return current
        if current.parent == current:
            break
        current = current.parent
    return None


def run_hooks(
    spec_path: Path,
    hooks: CompletionHooks,
    log_func: Optional[Callable[[str], None]] = None
) -> list[dict]:
    """
    Run completion hooks for a spec.

    Returns list of results for each hook executed.
    """
    results = []
    log = log_func or print

    spec_dir = spec_path.parent
    project_root = find_project_root(spec_path)
    if not project_root:
        project_root = spec_dir

    # Run copy hooks
    for hook in hooks.copy:
        result = _run_copy_hook(hook, spec_dir, project_root, log)
        results.append(result)

    # Run consolidate hooks
    for hook in hooks.consolidate:
        result = _run_consolidate_hook(hook, spec_dir, project_root, log)
        results.append(result)

    # Run command hooks
    for hook in hooks.commands:
        result = _run_command_hook(hook, project_root, log)
        results.append(result)
        if not result["success"] and not hook.continue_on_error:
            break

    return results


def _run_copy_hook(
    hook: CopyHook,
    spec_dir: Path,
    project_root: Path,
    log: Callable[[str], None]
) -> dict:
    """Execute a copy hook."""
    result = {
        "type": "copy",
        "source_pattern": hook.source_pattern,
        "destination": hook.destination,
        "success": False,
        "files_copied": [],
        "error": None,
    }

    try:
        # Resolve destination
        dest = Path(hook.destination)
        if not dest.is_absolute():
            dest = project_root / dest
        dest.mkdir(parents=True, exist_ok=True)

        # Find source files
        source_files = list(spec_dir.glob(hook.source_pattern))

        for src_file in source_files:
            if src_file.is_file():
                if hook.flatten:
                    dest_file = dest / src_file.name
                else:
                    # Preserve relative path structure
                    rel_path = src_file.relative_to(spec_dir)
                    dest_file = dest / rel_path

                dest_file.parent.mkdir(parents=True, exist_ok=True)

                if dest_file.exists() and not hook.overwrite:
                    log(f"  Skipping (exists): {dest_file}")
                    continue

                shutil.copy2(src_file, dest_file)
                result["files_copied"].append(str(dest_file))
                log(f"  Copied: {src_file.name} -> {dest_file}")

        result["success"] = True
        log(f"Copy hook completed: {len(result['files_copied'])} files")

    except Exception as e:
        result["error"] = str(e)
        log(f"Copy hook failed: {e}")

    return result


def _run_consolidate_hook(
    hook: ConsolidateHook,
    spec_dir: Path,
    project_root: Path,
    log: Callable[[str], None]
) -> dict:
    """Execute a consolidate hook."""
    result = {
        "type": "consolidate",
        "children": hook.children,
        "destination": hook.destination,
        "success": False,
        "files_copied": [],
        "error": None,
    }

    try:
        # Resolve destination
        dest = Path(hook.destination)
        if not dest.is_absolute():
            dest = project_root / dest
        dest.mkdir(parents=True, exist_ok=True)

        # Find child spec directories
        children_dir = spec_dir / "children"

        for child_name in hook.children:
            child_dir = children_dir / child_name
            source_dir = child_dir / hook.source_subdir

            if not source_dir.exists():
                log(f"  Warning: Child source not found: {source_dir}")
                continue

            # Copy all files from source_dir to dest, preserving structure
            for src_file in source_dir.rglob("*"):
                if src_file.is_file():
                    rel_path = src_file.relative_to(source_dir)
                    dest_file = dest / rel_path
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, dest_file)
                    result["files_copied"].append(str(dest_file))
                    log(f"  Consolidated: {child_name}/{rel_path}")

        result["success"] = True
        log(f"Consolidate hook completed: {len(result['files_copied'])} files")

    except Exception as e:
        result["error"] = str(e)
        log(f"Consolidate hook failed: {e}")

    return result


def _run_command_hook(
    hook: CommandHook,
    project_root: Path,
    log: Callable[[str], None]
) -> dict:
    """Execute a command hook."""
    result = {
        "type": "command",
        "command": hook.command,
        "success": False,
        "output": "",
        "error": None,
    }

    try:
        # Resolve working directory
        cwd = project_root
        if hook.working_dir:
            cwd = project_root / hook.working_dir

        log(f"Running command: {hook.command}")

        proc = subprocess.run(
            hook.command,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        result["output"] = proc.stdout + proc.stderr
        result["success"] = proc.returncode == 0

        if not result["success"]:
            result["error"] = f"Exit code {proc.returncode}"
            log(f"Command failed (exit {proc.returncode}): {proc.stderr[:200]}")
        else:
            log(f"Command completed successfully")

    except subprocess.TimeoutExpired:
        result["error"] = "Command timed out (5 min limit)"
        log(f"Command timed out")
    except Exception as e:
        result["error"] = str(e)
        log(f"Command hook failed: {e}")

    return result


def create_default_hooks(spec_name: str, destination: str) -> dict:
    """Create a default hooks.json for copying outputs to a destination."""
    return {
        "copy": [
            {
                "source_pattern": "src/**/*",
                "destination": destination,
                "flatten": False,
                "overwrite": True
            }
        ],
        "commands": [],
        "consolidate": []
    }
