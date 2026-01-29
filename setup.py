#!/usr/bin/env python3
"""
Ralph Pipeline Setup Script

Checks for and installs required dependencies:
- Claude Code (via winget on Windows)
- Python packages: claude-agent-sdk, mcp

Only installs what's missing. Safe to run multiple times.

Usage:
    python setup.py
    python setup.py --check    # Check only, don't install
    python setup.py --verbose  # Show detailed output
"""

import subprocess
import sys
import shutil
import argparse
from pathlib import Path


def run_cmd(cmd: list[str], check: bool = True, capture: bool = True) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            check=False
        )
        return result.returncode, result.stdout or "", result.stderr or ""
    except FileNotFoundError:
        return 1, "", f"Command not found: {cmd[0]}"
    except Exception as e:
        return 1, "", str(e)


def check_claude_code() -> bool:
    """Check if Claude Code is installed."""
    # Check if 'claude' command exists
    if shutil.which("claude"):
        return True

    # On Windows, also check common install locations
    if sys.platform == "win32":
        common_paths = [
            Path.home() / "AppData" / "Local" / "Programs" / "claude-code" / "claude.exe",
            Path.home() / "AppData" / "Local" / "claude-code" / "claude.exe",
        ]
        for p in common_paths:
            if p.exists():
                return True

    return False


def check_python_package(package: str) -> bool:
    """Check if a Python package is installed."""
    try:
        __import__(package.replace("-", "_"))
        return True
    except ImportError:
        return False


def get_package_version(package: str) -> str:
    """Get installed version of a package."""
    try:
        import importlib.metadata
        return importlib.metadata.version(package)
    except Exception:
        return "unknown"


def install_claude_code(verbose: bool = False) -> bool:
    """Install Claude Code via winget (Windows only)."""
    if sys.platform != "win32":
        print("  ! Claude Code auto-install only supported on Windows")
        print("  ! Run: curl -fsSL https://claude.ai/install.sh | bash")
        return False

    # Check if winget is available
    if not shutil.which("winget"):
        print("  ! winget not found. Install Claude Code manually:")
        print("  ! https://code.claude.com/docs/en/setup")
        return False

    print("  Installing Claude Code via winget...")
    cmd = ["winget", "install", "Anthropic.ClaudeCode", "--accept-source-agreements", "--accept-package-agreements"]

    if verbose:
        # Run with output visible
        result = subprocess.run(cmd, check=False)
        return result.returncode == 0
    else:
        code, stdout, stderr = run_cmd(cmd)
        if code != 0:
            print(f"  ! Installation failed: {stderr}")
            return False
        return True


def install_pip_package(package: str, verbose: bool = False) -> bool:
    """Install a Python package via pip."""
    print(f"  Installing {package}...")
    cmd = [sys.executable, "-m", "pip", "install", package]

    if not verbose:
        cmd.append("--quiet")

    code, stdout, stderr = run_cmd(cmd)

    if code != 0:
        print(f"  ! Failed to install {package}: {stderr}")
        return False

    return True


def check_ralph_modules() -> list[str]:
    """Check if Ralph modules can be imported."""
    errors = []

    # Add lib to path temporarily
    lib_path = Path(__file__).parent / ".claude" / "lib"
    if lib_path.exists():
        sys.path.insert(0, str(lib_path))

    modules = [
        ("ralph_db", "Database module"),
        ("hooks", "Hook enforcement"),
        ("message_hooks", "Message delivery"),
        ("spec", "Spec handling"),
    ]

    for module, desc in modules:
        try:
            __import__(module)
        except ImportError as e:
            errors.append(f"{desc} ({module}): {e}")
        except Exception as e:
            errors.append(f"{desc} ({module}): {e}")

    return errors


def main():
    parser = argparse.ArgumentParser(description="Setup Ralph Pipeline dependencies")
    parser.add_argument("--check", action="store_true", help="Check only, don't install")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    print("=" * 50)
    print("Ralph Pipeline Setup")
    print("=" * 50)
    print()
    print(f"Python: {sys.executable}")
    print(f"Version: {sys.version.split()[0]}")
    print()

    all_ok = True
    needs_install = []

    # Check Claude Code
    print("[1/3] Checking Claude Code...")
    if check_claude_code():
        print("  OK - Claude Code is installed")
    else:
        print("  MISSING - Claude Code not found")
        needs_install.append("claude-code")
        all_ok = False

    # Check Python packages
    print()
    print("[2/3] Checking Python packages...")

    packages = [
        ("claude-agent-sdk", "claude_agent_sdk"),
        ("mcp", "mcp"),
    ]

    for pip_name, import_name in packages:
        if check_python_package(import_name):
            version = get_package_version(pip_name)
            print(f"  OK - {pip_name} ({version})")
        else:
            print(f"  MISSING - {pip_name}")
            needs_install.append(pip_name)
            all_ok = False

    # Check Ralph modules
    print()
    print("[3/3] Checking Ralph modules...")
    module_errors = check_ralph_modules()

    if module_errors:
        for err in module_errors:
            print(f"  ERROR - {err}")
        all_ok = False
    else:
        print("  OK - All Ralph modules importable")

    # Summary
    print()
    print("-" * 50)

    if all_ok:
        print("All dependencies satisfied!")
        print()
        print("Next steps:")
        print("  1. Run 'claude' to authenticate (if not already done)")
        print("  2. Use /ralph to start a pipeline")
        return 0

    if args.check:
        print(f"Missing: {', '.join(needs_install)}")
        print("Run without --check to install")
        return 1

    # Install missing dependencies
    print(f"Installing missing dependencies: {', '.join(needs_install)}")
    print()

    success = True

    if "claude-code" in needs_install:
        print("Installing Claude Code...")
        if install_claude_code(args.verbose):
            print("  OK - Claude Code installed")
            print("  ! Run 'claude' to authenticate before using the pipeline")
        else:
            print("  FAILED - See instructions above")
            success = False

    for pip_name, import_name in packages:
        if pip_name in needs_install:
            if install_pip_package(pip_name, args.verbose):
                print(f"  OK - {pip_name} installed")
            else:
                success = False

    print()
    if success:
        print("Setup complete!")
        print()
        print("Next steps:")
        print("  1. Restart your terminal (if Claude Code was just installed)")
        print("  2. Run 'claude' to authenticate")
        print("  3. Use /ralph to start a pipeline")
        return 0
    else:
        print("Some installations failed. See errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
