#!/usr/bin/env python3
"""
Ralph Pipeline Submodule Update Script

Run this from the PARENT project to update the Ralph Pipeline submodule.

Usage:
    python ralph-pipeline/update-submodule.py
    python ralph-pipeline/update-submodule.py --check
    python ralph-pipeline/update-submodule.py --upgrade

Options:
    --check     Show what would be done (no changes)
    --upgrade   Also run upgrade.py after pulling
    --no-commit Don't commit the submodule reference update
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path = None, check: bool = True) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            check=False
        )
        if check and result.returncode != 0:
            return result.returncode, result.stdout, result.stderr
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def get_current_commit(repo_path: Path) -> str:
    """Get the current HEAD commit hash."""
    code, stdout, _ = run(["git", "rev-parse", "HEAD"], cwd=repo_path)
    return stdout[:8] if code == 0 else "unknown"


def get_remote_commit(repo_path: Path, branch: str = "master") -> str:
    """Get the latest remote commit hash."""
    # Fetch first
    run(["git", "fetch", "origin"], cwd=repo_path, check=False)
    code, stdout, _ = run(["git", "rev-parse", f"origin/{branch}"], cwd=repo_path)
    return stdout[:8] if code == 0 else "unknown"


def has_uncommitted_changes(repo_path: Path) -> bool:
    """Check if repo has uncommitted changes."""
    code, stdout, _ = run(["git", "status", "--porcelain"], cwd=repo_path)
    return bool(stdout.strip())


def main():
    parser = argparse.ArgumentParser(
        description="Update Ralph Pipeline submodule",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--check", action="store_true", help="Preview only, no changes")
    parser.add_argument("--upgrade", action="store_true", help="Run upgrade.py after pulling")
    parser.add_argument("--no-commit", action="store_true", help="Don't commit the submodule update")
    parser.add_argument("--branch", default="master", help="Branch to pull (default: master)")

    args = parser.parse_args()

    # Determine paths
    script_path = Path(__file__).resolve()
    submodule_path = script_path.parent
    submodule_name = submodule_path.name

    # Find parent repo (walk up until we find .git that's not a file)
    parent_path = submodule_path.parent
    while parent_path != parent_path.parent:
        git_path = parent_path / ".git"
        if git_path.exists() and git_path.is_dir():
            break
        parent_path = parent_path.parent
    else:
        print("ERROR: Could not find parent git repository")
        print("       This script should be run from within a parent project")
        print("       that has Ralph Pipeline as a submodule.")
        sys.exit(1)

    # Check if this is actually a submodule
    gitmodules = parent_path / ".gitmodules"
    if not gitmodules.exists():
        print("ERROR: No .gitmodules found in parent repo")
        print("       Ralph Pipeline doesn't appear to be a submodule.")
        sys.exit(1)

    print("=" * 60)
    print("RALPH PIPELINE SUBMODULE UPDATE")
    print("=" * 60)
    print(f"Parent repo:  {parent_path}")
    print(f"Submodule:    {submodule_path.relative_to(parent_path)}")
    if args.check:
        print("Mode:         CHECK ONLY (no changes)")
    print("=" * 60)
    print()

    # Get current state
    current = get_current_commit(submodule_path)
    remote = get_remote_commit(submodule_path, args.branch)

    print(f"Current commit: {current}")
    print(f"Remote commit:  {remote}")
    print()

    if current == remote:
        print("Already up to date.")
        if args.upgrade:
            print()
            print("Running upgrade check anyway...")
            code, stdout, stderr = run(
                [sys.executable, "upgrade.py", "--check"],
                cwd=submodule_path
            )
            print(stdout)
            if stderr:
                print(stderr)
        sys.exit(0)

    # Check for local changes in submodule
    if has_uncommitted_changes(submodule_path):
        print("WARNING: Submodule has uncommitted changes")
        print("         Commit or stash them before updating.")
        sys.exit(1)

    if args.check:
        print(f"Would pull {args.branch} ({current} -> {remote})")
        if not args.no_commit:
            print(f"Would commit submodule reference update in parent")
        if args.upgrade:
            print("Would run upgrade.py")
        sys.exit(0)

    # Pull latest
    print(f"Pulling {args.branch}...")
    code, stdout, stderr = run(
        ["git", "pull", "origin", args.branch],
        cwd=submodule_path
    )
    if code != 0:
        print(f"ERROR: git pull failed")
        print(stderr)
        sys.exit(1)
    print(stdout if stdout else "  Done")
    print()

    # Commit submodule reference in parent
    if not args.no_commit:
        print("Staging submodule reference update...")
        code, _, stderr = run(
            ["git", "add", str(submodule_path.relative_to(parent_path))],
            cwd=parent_path
        )
        if code != 0:
            print(f"ERROR: git add failed: {stderr}")
            sys.exit(1)

        # Check if there's actually something to commit
        code, stdout, _ = run(["git", "status", "--porcelain"], cwd=parent_path)
        if not stdout.strip():
            print("  No changes to commit (submodule already at this commit)")
        else:
            new_commit = get_current_commit(submodule_path)
            commit_msg = f"Update {submodule_name} submodule ({current} -> {new_commit})"

            print(f"Committing: {commit_msg}")
            code, _, stderr = run(
                ["git", "commit", "-m", commit_msg],
                cwd=parent_path
            )
            if code != 0:
                print(f"ERROR: git commit failed: {stderr}")
                sys.exit(1)
            print("  Done")
        print()

    # Run upgrade if requested
    if args.upgrade:
        print("Running upgrade...")
        print("-" * 40)
        result = subprocess.run(
            [sys.executable, "upgrade.py"],
            cwd=submodule_path
        )
        print("-" * 40)
        if result.returncode != 0:
            print("Upgrade completed with errors (see above)")
        print()

    print("=" * 60)
    print("UPDATE COMPLETE")
    print()
    print("Next steps:")
    if not args.upgrade:
        print(f"  1. Run: python {submodule_name}/upgrade.py --check")
    print(f"  2. Restart Claude Code to load MCP server")
    print(f"  3. Test with /pipeline-status")
    print("=" * 60)


if __name__ == "__main__":
    main()
