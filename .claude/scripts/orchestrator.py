#!/usr/bin/env python3
"""
Ralph Orchestrator v4: Parallel Execution with Hibernation

The orchestrator is a Python process that:
1. Manages a work queue of specs to process
2. Tracks dependencies between specs
3. Spawns agents in parallel (respecting dependencies)
4. Provides MCP tools for agent communication
5. Handles hibernation/wake cycles for any agent
6. Triggers integration tests when siblings complete
7. Exposes status for user-facing Claude to query

Architecture:
    User <-> Claude Code -> runs orchestrator.py
                              |
                         Orchestrator
                              |
              +---------------+---------------+
              |               |               |
          Agent A         Agent B         Agent C
              +---------------+---------------+
                              |
                    MCP Server (in-process)
                    - send_message
                    - hibernate
                    - signal_complete
                    - check_dependency
                    - request_parent_decision

Requirements:
    pip install claude-agent-sdk

Usage:
    python orchestrator.py --spec path/to/spec.json [--dry-run] [--live]
"""

import argparse
import asyncio
import json
import os
import sys
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any, Callable, Awaitable
from enum import Enum
import traceback

# Force unbuffered output for better monitoring in background tasks
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from spec import (
    Spec, load_spec, save_spec, is_leaf, is_ready,
    create_child_spec, create_shared_spec, Child, spec_to_dict,
    ClassDef, Criterion, Errors, SharedType,
    validate_spec_paths, detect_project_type, fix_protected_paths
)
from ralph_db import get_db, RalphDB
from ralph_db import Spec as DBSpec, Message as DBMessage

# Import worktree and file ownership management
from worktree import WorktreeManager, BranchInfo, WorktreeInfo, MergeResult, GitError
from file_ownership import FileOwnershipTracker, ClaimResult
from completion_hooks import load_hooks_from_spec, run_hooks
import atexit
import signal


# =============================================================================
# PID FILE MANAGEMENT (Singleton Enforcement)
# =============================================================================

_PID_FILE: Optional[Path] = None


def _get_project_root() -> Path:
    """Find project root by looking for .claude directory."""
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".claude").is_dir():
            return parent
    return cwd


def _cleanup_pid_file():
    """Remove PID file on exit."""
    global _PID_FILE
    if _PID_FILE and _PID_FILE.exists():
        try:
            _PID_FILE.unlink()
        except OSError:
            pass


def _signal_handler(signum, frame):
    """Handle termination signals."""
    _cleanup_pid_file()
    sys.exit(128 + signum)


def acquire_singleton_lock() -> bool:
    """
    Acquire singleton lock by creating PID file.
    Returns True if lock acquired, False if another instance is running.
    """
    global _PID_FILE
    root = _get_project_root()
    _PID_FILE = root / ".orchestrator.pid"

    # Check for existing lock
    if _PID_FILE.exists():
        try:
            content = _PID_FILE.read_text().strip()
            existing_pid = int(content.split()[0])

            # Check if process is still running
            if sys.platform == "win32":
                import subprocess
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {existing_pid}", "/NH"],
                    capture_output=True, text=True
                )
                if str(existing_pid) in result.stdout:
                    return False  # Another orchestrator is running
            else:
                try:
                    os.kill(existing_pid, 0)
                    return False  # Process exists
                except OSError:
                    pass  # Process doesn't exist, stale PID file

            # Stale PID file, remove it
            _PID_FILE.unlink()
        except (ValueError, IndexError, OSError):
            # Corrupt PID file, remove it
            try:
                _PID_FILE.unlink()
            except OSError:
                pass

    # Create PID file
    try:
        _PID_FILE.write_text(f"{os.getpid()}\n")
    except OSError as e:
        print(f"WARNING: Could not create PID file: {e}")
        return True  # Continue anyway

    # Register cleanup
    atexit.register(_cleanup_pid_file)

    # Handle signals for cleanup
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGHUP, _signal_handler)

    return True


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class Config:
    max_depth: int = 3
    max_iterations: int = 10
    max_arch_iterations: int = 5
    max_total_agents: int = 100
    max_concurrent_agents: int = 5
    dry_run: bool = False
    live: bool = False
    model: str = "claude-opus-4-5-20251101"
    auto_fix_paths: bool = True  # Automatically redirect .claude/ paths to src/


CONFIG = Config()


class Phase(str, Enum):
    PENDING = "pending"
    RESEARCH = "research"
    ARCHITECTURE = "architecture"
    SCAFFOLD = "scaffold"  # Generate stubs, await approval before implementation
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"
    INTEGRATION = "integration"
    COMPLETE = "complete"
    FAILED = "failed"
    BLOCKED = "blocked"


class Priority(str, Enum):
    NORMAL = "normal"
    BLOCKING = "blocking"
    URGENT = "urgent"


# =============================================================================
# HIBERNATION CONTEXT (stored in DB spec.data)
# =============================================================================

@dataclass
class HibernationContext:
    spec_name: str
    agent_type: str
    phase: Phase
    state: dict
    resume_trigger: str  # e.g., "message_response:msg-001", "dependency:shared"
    instructions: str
    exported_at: str


def hibernation_to_dict(ctx: HibernationContext) -> dict:
    """Convert HibernationContext to dict for DB storage."""
    return {
        "spec_name": ctx.spec_name,
        "agent_type": ctx.agent_type,
        "phase": ctx.phase.value if isinstance(ctx.phase, Phase) else ctx.phase,
        "state": ctx.state,
        "resume_trigger": ctx.resume_trigger,
        "instructions": ctx.instructions,
        "exported_at": ctx.exported_at
    }


def hibernation_from_dict(d: dict) -> HibernationContext:
    """Restore HibernationContext from dict."""
    return HibernationContext(
        spec_name=d["spec_name"],
        agent_type=d["agent_type"],
        phase=Phase(d["phase"]) if isinstance(d["phase"], str) else d["phase"],
        state=d["state"],
        resume_trigger=d["resume_trigger"],
        instructions=d["instructions"],
        exported_at=d["exported_at"]
    )


# =============================================================================
# SPEC STATUS (local view, backed by DB)
# =============================================================================

@dataclass
class SpecStatus:
    """Local runtime view of spec status. Synced with DB."""
    name: str
    spec_id: str  # DB id
    path: Path
    phase: Phase
    depth: int
    parent: Optional[str] = None
    children: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    current_agent: Optional[str] = None
    iteration: int = 0
    error: Optional[str] = None
    worktree_path: Optional[Path] = None  # Path to spec's worktree (if created)


# =============================================================================
# ORCHESTRATOR STATE (hybrid: DB + in-memory for async)
# =============================================================================

class OrchestratorState:
    """
    Orchestrator state backed by ralph_db.

    DB-backed (persistent):
    - Spec registration and status
    - Messages between specs
    - Hibernation contexts
    - Agent run tracking

    In-memory only (async/runtime):
    - Wake events (asyncio.Event)
    - Pending response futures
    - Active asyncio tasks
    """

    def __init__(self, db: RalphDB):
        self.db = db

        # Local cache of spec statuses (synced with DB)
        self._specs: dict[str, SpecStatus] = {}

        # Async-only state (not persisted)
        self.wake_events: dict[str, asyncio.Event] = {}
        self.pending_responses: dict[str, asyncio.Future] = {}
        self.active_tasks: dict[str, asyncio.Task] = {}

        # Worktree and file ownership managers
        self.worktree_mgr: Optional[WorktreeManager] = None
        self.file_tracker: Optional[FileOwnershipTracker] = None

    def init_worktree_management(self):
        """Initialize worktree and file ownership managers."""
        try:
            self.worktree_mgr = WorktreeManager()
            self.file_tracker = FileOwnershipTracker()
            log("Worktree management initialized", "INFO")
        except GitError as e:
            log(f"Worktree management unavailable: {e}", "WARN")
            self.worktree_mgr = None
            self.file_tracker = None

    def cleanup_orphaned_worktrees(self):
        """Clean up stale/orphaned worktrees on startup."""
        if not self.worktree_mgr:
            return

        try:
            # Prune stale worktree references
            self.worktree_mgr._run_git_no_check('worktree', 'prune')
            log("Pruned stale worktree references", "INFO")
        except Exception as e:
            log(f"Failed to prune worktrees: {e}", "WARN")

    def get_default_branch(self) -> str:
        """Get the default branch name (main or master) for this repo."""
        if not self.worktree_mgr:
            return 'main'  # Fallback

        try:
            # Try to get from remote HEAD
            result = self.worktree_mgr._run_git_no_check(
                'symbolic-ref', 'refs/remotes/origin/HEAD'
            )
            if result and result.strip():
                # Returns something like 'refs/remotes/origin/main'
                return result.strip().split('/')[-1]
        except Exception:
            pass

        # Fallback: check if main or master exists locally
        try:
            result = self.worktree_mgr._run_git_no_check('branch', '--list', 'main')
            if result and 'main' in result:
                return 'main'
        except Exception:
            pass

        try:
            result = self.worktree_mgr._run_git_no_check('branch', '--list', 'master')
            if result and 'master' in result:
                return 'master'
        except Exception:
            pass

        return 'main'  # Ultimate fallback

    # =========================================================================
    # SPEC OPERATIONS
    # =========================================================================

    def register_spec(self, name: str, path: Path, depth: int,
                      parent: Optional[str] = None,
                      depends_on: Optional[list[str]] = None,
                      is_leaf: Optional[bool] = None) -> str:
        """Register a spec in the DB and local cache. Returns spec_id."""
        # Check if already exists by name
        existing = self.db.get_spec_by_name(name)
        if existing:
            spec_id = existing.id
            # Update local cache
            self._specs[name] = SpecStatus(
                name=name,
                spec_id=spec_id,
                path=path,
                phase=Phase(existing.status) if existing.status in [p.value for p in Phase] else Phase.PENDING,
                depth=existing.depth,
                parent=existing.data.get("parent"),
                children=existing.data.get("children", []),
                depends_on=existing.data.get("depends_on", []),
                iteration=existing.data.get("iteration", 0),
                worktree_path=Path(existing.data["worktree_path"]) if existing.data.get("worktree_path") else None
            )
            return spec_id

        # Create new
        spec_id = self.db.create_spec(
            name=name,
            parent_id=None,  # We track parent by name, not id
            data={
                "path": str(path),
                "parent": parent,
                "children": [],
                "depends_on": depends_on or [],
                "iteration": 0,
                "phase": Phase.PENDING.value,
                "worktree_path": None
            },
            is_leaf=is_leaf,
            depth=depth
        )

        # Create local cache entry
        self._specs[name] = SpecStatus(
            name=name,
            spec_id=spec_id,
            path=path,
            phase=Phase.PENDING,
            depth=depth,
            parent=parent,
            depends_on=depends_on or []
        )

        self.db.log_event(spec_id, "spec_registered", {
            "name": name,
            "path": str(path),
            "depth": depth,
            "parent": parent
        })

        return spec_id

    def get_spec_status(self, name: str) -> Optional[SpecStatus]:
        """Get spec status from local cache."""
        return self._specs.get(name)

    def set_spec_status(self, name: str, status: SpecStatus):
        """Set spec status in local cache and sync to DB."""
        self._specs[name] = status

        # Sync to DB
        self.db.update_spec(
            status.spec_id,
            status=status.phase.value,
            data={
                "path": str(status.path),
                "parent": status.parent,
                "children": status.children,
                "depends_on": status.depends_on,
                "iteration": status.iteration,
                "phase": status.phase.value,
                "current_agent": status.current_agent,
                "error": status.error,
                "worktree_path": str(status.worktree_path) if status.worktree_path else None
            }
        )

    def update_phase(self, name: str, phase: Phase):
        """Update just the phase of a spec."""
        status = self._specs.get(name)
        if status:
            status.phase = phase
            self.db.update_spec(status.spec_id, status=phase.value)
            self.db.log_event(status.spec_id, "phase_changed", {"phase": phase.value})

    # =========================================================================
    # WORKTREE OPERATIONS
    # =========================================================================

    def create_worktree_for_spec(self, spec_path: str, parent_spec_name: Optional[str] = None) -> Optional[Path]:
        """
        Create a worktree for a spec.

        Args:
            spec_path: Path to the spec.json file
            parent_spec_name: Name of parent spec (if any) for hierarchical branching

        Returns:
            Path to the worktree, or None if worktree management is unavailable
        """
        if not self.worktree_mgr:
            return None

        try:
            # Determine parent branch
            if parent_spec_name:
                parent_status = self._specs.get(parent_spec_name)
                if parent_status and parent_status.worktree_path:
                    # Get parent's branch name
                    parent_branch = self.worktree_mgr._spec_path_to_branch_name(str(parent_status.path))
                else:
                    parent_branch = self.get_default_branch()
            else:
                parent_branch = self.get_default_branch()

            # Create branch
            branch_info = self.worktree_mgr.create_spec_branch(spec_path, parent_branch)
            log(f"Created branch {branch_info.name} from {parent_branch}", "INFO")

            # Create worktree
            worktree_info = self.worktree_mgr.create_worktree(branch_info.name)
            log(f"Created worktree at {worktree_info.path}", "INFO")

            return Path(worktree_info.path)

        except GitError as e:
            log(f"Failed to create worktree: {e}", "ERROR")
            return None

    def claim_files_for_spec(self, spec_path: str, spec: Spec) -> ClaimResult:
        """
        Claim file ownership for a spec based on its classes.

        Args:
            spec_path: Path to the spec.json file
            spec: The loaded spec object

        Returns:
            ClaimResult with success status and any conflicts
        """
        if not self.file_tracker:
            return ClaimResult(success=True, message="File tracking unavailable")

        # Extract patterns from spec.classes
        patterns = []
        for cls in spec.classes:
            if hasattr(cls, 'location') and cls.location:
                # Use the location as-is (may contain wildcards)
                patterns.append(cls.location)

        if not patterns:
            return ClaimResult(success=True, patterns=[], message="No files to claim")

        return self.file_tracker.claim_files(spec_path, patterns)

    def merge_completed_spec(self, spec_path: str, parent_spec_name: Optional[str] = None) -> MergeResult:
        """
        Merge a completed spec's worktree into parent branch.

        Args:
            spec_path: Path to the spec.json file
            parent_spec_name: Name of parent spec (if any)

        Returns:
            MergeResult with success status and conflict info if applicable
        """
        if not self.worktree_mgr:
            return MergeResult(success=True, message="Worktree management unavailable")

        try:
            # Get branch names
            child_branch = self.worktree_mgr._spec_path_to_branch_name(spec_path)

            if parent_spec_name:
                parent_status = self._specs.get(parent_spec_name)
                if parent_status:
                    parent_branch = self.worktree_mgr._spec_path_to_branch_name(str(parent_status.path))
                else:
                    parent_branch = self.get_default_branch()
            else:
                parent_branch = self.get_default_branch()

            # Perform merge
            result = self.worktree_mgr.merge_up(child_branch, parent_branch)

            if result.success:
                log(f"Merged {child_branch} into {parent_branch}", "SUCCESS")
            elif result.conflict:
                log(f"Merge conflict: {result.conflict_files}", "WARN")

            return result

        except GitError as e:
            log(f"Failed to merge: {e}", "ERROR")
            return MergeResult(success=False, message=str(e))

    def cleanup_spec_worktree(self, spec_path: str, release_files: bool = True):
        """
        Clean up worktree and release file claims for a spec.

        Args:
            spec_path: Path to the spec.json file
            release_files: Whether to release file ownership claims
        """
        if self.worktree_mgr:
            try:
                self.worktree_mgr.cleanup(spec_path)
                log(f"Cleaned up worktree for {spec_path}", "INFO")
            except GitError as e:
                log(f"Failed to cleanup worktree: {e}", "WARN")

        if release_files and self.file_tracker:
            self.file_tracker.release_files(spec_path)
            log(f"Released file claims for {spec_path}", "INFO")

    # =========================================================================
    # MESSAGE OPERATIONS
    # =========================================================================

    def add_message(self, from_spec: str, to_spec: str, msg_type: str,
                    payload: dict, priority: Priority = Priority.NORMAL) -> str:
        """Send a message via DB. Returns message ID."""
        msg_id = self.db.send_message(
            from_spec=from_spec,
            to_spec=to_spec,
            type=msg_type,
            payload=payload,
            priority=priority.value
        )

        # Set wake event if blocking
        if priority == Priority.BLOCKING and to_spec in self.wake_events:
            self.wake_events[to_spec].set()

        return msg_id

    def get_pending_messages(self, spec_name: str) -> list[DBMessage]:
        """Get pending messages for a spec."""
        return self.db.get_pending_messages(spec_name)

    def mark_message_processed(self, msg_id: str, response: Optional[dict] = None):
        """Mark a message as processed."""
        self.db.mark_message_processed(msg_id, response)

        # Resolve any pending future
        if msg_id in self.pending_responses:
            self.pending_responses[msg_id].set_result(response)

    def get_message(self, msg_id: str) -> Optional[DBMessage]:
        """Get a message by ID."""
        return self.db.get_message(msg_id)

    # =========================================================================
    # HIBERNATION OPERATIONS
    # =========================================================================

    def hibernate_agent(self, ctx: HibernationContext):
        """Store hibernation context in DB and create wake event."""
        status = self._specs.get(ctx.spec_name)
        if not status:
            return

        # Store in spec's data
        spec = self.db.get_spec(status.spec_id)
        if spec:
            data = spec.data.copy()
            data["hibernation"] = hibernation_to_dict(ctx)
            self.db.update_spec(status.spec_id, data=data)

        # Create wake event
        self.wake_events[ctx.spec_name] = asyncio.Event()

        self.db.log_event(status.spec_id, "agent_hibernated", {
            "agent_type": ctx.agent_type,
            "phase": ctx.phase.value,
            "resume_trigger": ctx.resume_trigger
        })

    def wake_agent(self, spec_name: str) -> Optional[HibernationContext]:
        """Remove hibernation context and return it."""
        status = self._specs.get(spec_name)
        if not status:
            return None

        spec = self.db.get_spec(status.spec_id)
        if not spec or "hibernation" not in spec.data:
            return None

        ctx = hibernation_from_dict(spec.data["hibernation"])

        # Remove from DB
        data = spec.data.copy()
        del data["hibernation"]
        self.db.update_spec(status.spec_id, data=data)

        # Clean up wake event
        if spec_name in self.wake_events:
            del self.wake_events[spec_name]

        self.db.log_event(status.spec_id, "agent_woken", {
            "agent_type": ctx.agent_type,
            "phase": ctx.phase.value
        })

        return ctx

    def is_hibernating(self, spec_name: str) -> bool:
        """Check if a spec has a hibernating agent."""
        status = self._specs.get(spec_name)
        if not status:
            return False

        spec = self.db.get_spec(status.spec_id)
        return spec is not None and "hibernation" in spec.data

    def get_hibernation_context(self, spec_name: str) -> Optional[HibernationContext]:
        """Get hibernation context without removing it."""
        status = self._specs.get(spec_name)
        if not status:
            return None

        spec = self.db.get_spec(status.spec_id)
        if spec and "hibernation" in spec.data:
            return hibernation_from_dict(spec.data["hibernation"])
        return None

    # =========================================================================
    # AGENT TRACKING
    # =========================================================================

    def start_agent(self, spec_name: str, agent_type: str, iteration: int = 1) -> int:
        """Record agent start. Returns run ID."""
        status = self._specs.get(spec_name)
        if not status:
            return -1

        status.current_agent = agent_type
        return self.db.start_agent_run(status.spec_id, agent_type, iteration)

    def complete_agent(self, run_id: int, success: bool, result: Optional[dict] = None):
        """Record agent completion."""
        status_str = "completed" if success else "failed"
        self.db.complete_agent_run(run_id, status_str, result)

    def get_agents_spawned(self) -> int:
        """Get total count of agents spawned."""
        summary = self.db.get_pipeline_summary()
        return summary.get("running_agents", 0) + len(
            self.db.get_events(type="agent_spawned")
        )

    # =========================================================================
    # WORKFLOW QUERIES
    # =========================================================================

    def get_ready_specs(self) -> list[str]:
        """Get specs whose dependencies are satisfied and aren't blocked."""
        ready = []
        for name, status in self._specs.items():
            if status.phase in [Phase.COMPLETE, Phase.FAILED, Phase.BLOCKED]:
                continue
            if name in self.active_tasks:
                continue
            if self.is_hibernating(name):
                continue

            # Check dependencies
            deps_satisfied = all(
                self._specs.get(dep, SpecStatus(dep, "", Path(), Phase.PENDING, 0)).phase == Phase.COMPLETE
                for dep in status.depends_on
            )

            if deps_satisfied:
                ready.append(name)

        return ready

    def all_children_complete(self, parent_name: str) -> bool:
        """Check if all children of a parent are complete."""
        parent = self._specs.get(parent_name)
        if not parent:
            return False

        for child_name in parent.children:
            child = self._specs.get(child_name)
            if not child or child.phase != Phase.COMPLETE:
                return False

        return len(parent.children) > 0

    def flag_for_review(self, spec_name: str, reason: str, details: dict):
        """Flag a spec for human review."""
        status = self._specs.get(spec_name)
        if status:
            status.phase = Phase.BLOCKED
            self.db.update_spec(status.spec_id, status="blocked")
            self.db.log_event(status.spec_id, "flagged_for_review", {
                "reason": reason,
                "details": details,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

    def get_needs_review(self) -> list[dict]:
        """Get specs that need human review."""
        blocked = self.db.list_specs(status="blocked")
        failed = self.db.list_specs(status="failed")

        items = []
        for spec in blocked + failed:
            events = self.db.get_events(spec.id, type="flagged_for_review", limit=1)
            if events:
                items.append({
                    "spec": spec.name,
                    "spec_id": spec.id,
                    "status": spec.status,
                    "reason": events[0].data.get("reason", "unknown"),
                    "details": events[0].data.get("details", {}),
                    "timestamp": events[0].created_at
                })
            else:
                items.append({
                    "spec": spec.name,
                    "spec_id": spec.id,
                    "status": spec.status,
                    "reason": spec.status,
                    "details": {},
                    "timestamp": spec.updated_at
                })

        return items

    def get_hibernating_specs(self) -> list[str]:
        """Get list of hibernating spec names."""
        hibernating = []
        for name in self._specs:
            if self.is_hibernating(name):
                hibernating.append(name)
        return hibernating


# Global state instance (initialized in main)
STATE: Optional[OrchestratorState] = None


def get_state() -> OrchestratorState:
    """Get the global state, initializing if needed."""
    global STATE
    if STATE is None:
        STATE = OrchestratorState(get_db())
    return STATE


# =============================================================================
# MCP TOOLS
# =============================================================================

def create_mcp_tools():
    """Create MCP tools that access the database-backed STATE."""

    try:
        from claude_agent_sdk import tool, create_sdk_mcp_server
    except ImportError:
        print("ERROR: pip install claude-agent-sdk")
        sys.exit(1)

    state = get_state()

    @tool("send_message", "Send a message to another spec (parent or sibling)", {
        "to": str,
        "type": str,
        "payload": dict,
        "priority": str,
        "needs_response": bool
    })
    async def send_message(args: dict) -> dict:
        caller = args.get("_caller_spec", "unknown")
        priority = Priority(args.get("priority", "normal"))

        msg_id = state.add_message(
            from_spec=caller,
            to_spec=args["to"],
            msg_type=args["type"],
            payload=args["payload"],
            priority=priority
        )

        return {
            "content": [{
                "type": "text",
                "text": f"Message {msg_id} sent to {args['to']} (type: {args['type']}, priority: {args['priority']})"
            }]
        }

    @tool("hibernate", "Save state and gracefully terminate, to be woken later", {
        "resume_trigger": str,
        "state": dict,
        "instructions": str
    })
    async def hibernate(args: dict) -> dict:
        # The actual hibernation is handled by the orchestrator when it sees this response
        # We just signal the intent here
        return {
            "content": [{
                "type": "text",
                "text": "Hibernation requested. Saving state..."
            }],
            # Special field the orchestrator looks for
            "_hibernation_request": {
                "resume_trigger": args["resume_trigger"],
                "state": args["state"],
                "instructions": args["instructions"]
            }
        }

    @tool("signal_complete", "Signal that this spec's work is complete", {
        "success": bool,
        "summary": str
    })
    async def signal_complete(args: dict) -> dict:
        return {
            "content": [{
                "type": "text",
                "text": f"Completion signaled: {'success' if args['success'] else 'failure'}"
            }],
            "_completion_signal": {
                "success": args["success"],
                "summary": args["summary"]
            }
        }

    @tool("check_dependency", "Check if a dependency spec is complete", {
        "name": str
    })
    async def check_dependency(args: dict) -> dict:
        status = state.get_spec_status(args["name"])
        if not status:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Dependency '{args['name']}' not found"
                }],
                "ready": False,
                "status": "unknown"
            }

        ready = status.phase == Phase.COMPLETE
        return {
            "content": [{
                "type": "text",
                "text": f"Dependency '{args['name']}': {status.phase.value}"
            }],
            "ready": ready,
            "status": status.phase.value
        }

    @tool("request_parent_decision", "Request a decision from parent (blocks until response)", {
        "question": str,
        "context": dict
    })
    async def request_parent_decision(args: dict) -> dict:
        caller = args.get("_caller_spec", "unknown")
        caller_status = state.get_spec_status(caller)

        if not caller_status or not caller_status.parent:
            return {
                "content": [{
                    "type": "text",
                    "text": "Error: No parent to request decision from"
                }],
                "error": True
            }

        # Send blocking message to parent
        msg_id = state.add_message(
            from_spec=caller,
            to_spec=caller_status.parent,
            msg_type="decision_request",
            payload={
                "question": args["question"],
                "context": args["context"]
            },
            priority=Priority.BLOCKING
        )

        # Create future for response
        future = asyncio.get_running_loop().create_future()
        state.pending_responses[msg_id] = future

        # Signal hibernation with trigger being the response
        return {
            "content": [{
                "type": "text",
                "text": f"Decision requested from parent. Request ID: {msg_id}. Hibernating until response..."
            }],
            "_hibernation_request": {
                "resume_trigger": f"message_response:{msg_id}",
                "state": {},
                "instructions": f"Waiting for parent decision on: {args['question']}"
            }
        }

    @tool("get_my_messages", "Get pending messages for this spec", {})
    async def get_my_messages(args: dict) -> dict:
        caller = args.get("_caller_spec", "unknown")
        messages = state.get_pending_messages(caller)

        return {
            "content": [{
                "type": "text",
                "text": json.dumps([{
                    "id": m.id,
                    "from": m.from_spec,
                    "type": m.type,
                    "payload": m.payload,
                    "priority": m.priority
                } for m in messages], indent=2)
            }],
            "messages": messages
        }

    @tool("respond_to_message", "Respond to a message (for decision requests)", {
        "message_id": str,
        "response": dict
    })
    async def respond_to_message(args: dict) -> dict:
        msg_id = args["message_id"]
        msg = state.get_message(msg_id)

        if not msg:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Message {msg_id} not found"
                }],
                "error": True
            }

        state.mark_message_processed(msg_id, args["response"])

        return {
            "content": [{
                "type": "text",
                "text": f"Response sent for {msg_id}"
            }]
        }

    # =========================================================================
    # SPEC MANIPULATION TOOLS
    # =========================================================================

    @tool("update_spec_structure", "Update spec structure (is_leaf, children, classes). Used by proposer.", {
        "is_leaf": bool,
        "children": list,  # [{"name": str, "description": str, "criteria": list}]
        "classes": list,   # [{"name": str, "location": str, "description": str}]
        "rationale": str
    })
    async def update_spec_structure(args: dict) -> dict:
        caller = args.get("_caller_spec", "unknown")
        status = state.get_spec_status(caller)

        if not status or not status.path:
            return {
                "content": [{"type": "text", "text": f"Error: Spec '{caller}' not found"}],
                "error": True
            }

        try:
            spec = load_spec(status.path)

            # Update structure
            spec.is_leaf = args.get("is_leaf", spec.is_leaf)

            if "children" in args and args["children"]:
                spec.children = [
                    Child(**c) if isinstance(c, dict) else c
                    for c in args["children"]
                ]

            if "classes" in args and args["classes"]:
                spec.classes = [
                    ClassDef(**c) if isinstance(c, dict) else c
                    for c in args["classes"]
                ]

            # Save with rationale in notes
            save_spec(spec)

            # Log the decision
            state.db.log_event(status.spec_id, "structure_update", {
                "is_leaf": args.get("is_leaf"),
                "children_count": len(args.get("children", [])),
                "classes_count": len(args.get("classes", [])),
                "rationale": args.get("rationale", "")
            })

            return {
                "content": [{
                    "type": "text",
                    "text": f"Spec structure updated: is_leaf={spec.is_leaf}, {len(spec.children)} children, {len(spec.classes)} classes"
                }],
                "_structure_update": {
                    "is_leaf": spec.is_leaf,
                    "children": [c.name for c in spec.children],
                    "classes": [c.name for c in spec.classes]
                }
            }
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Error updating spec: {e}"}],
                "error": True
            }

    @tool("set_research_findings", "Save research findings. Used by researcher.", {
        "topics": list,           # [{"name": str, "summary": str, "sources": list}]
        "recommendations": list,  # [str]
        "patterns_found": list,   # [{"pattern": str, "location": str}]
        "risks": list,            # [{"risk": str, "mitigation": str}]
        "dependencies": list      # [{"name": str, "version": str, "purpose": str}]
    })
    async def set_research_findings(args: dict) -> dict:
        caller = args.get("_caller_spec", "unknown")
        status = state.get_spec_status(caller)

        if not status or not status.path:
            return {
                "content": [{"type": "text", "text": f"Error: Spec '{caller}' not found"}],
                "error": True
            }

        try:
            spec_dir = status.path.parent
            research_path = spec_dir / "research.json"

            research = {
                "spec_name": caller,
                "researched_at": datetime.now(timezone.utc).isoformat(),
                "topics": args.get("topics", []),
                "recommendations": args.get("recommendations", []),
                "patterns_found": args.get("patterns_found", []),
                "risks": args.get("risks", []),
                "dependencies": args.get("dependencies", [])
            }

            research_path.write_text(json.dumps(research, indent=2), encoding='utf-8')

            # Log to DB
            state.db.log_event(status.spec_id, "research_complete", {
                "topics_count": len(research["topics"]),
                "recommendations_count": len(research["recommendations"])
            })

            return {
                "content": [{
                    "type": "text",
                    "text": f"Research saved: {len(research['topics'])} topics, {len(research['recommendations'])} recommendations"
                }]
            }
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Error saving research: {e}"}],
                "error": True
            }

    @tool("submit_critique", "Submit critique of a proposal. Used by critic.", {
        "approved": bool,
        "critiques": list,  # [{"issue": str, "severity": str, "suggestion": str}]
        "strengths": list,  # [str]
        "overall_assessment": str
    })
    async def submit_critique(args: dict) -> dict:
        caller = args.get("_caller_spec", "unknown")
        status = state.get_spec_status(caller)

        if not status or not status.path:
            return {
                "content": [{"type": "text", "text": f"Error: Spec '{caller}' not found"}],
                "error": True
            }

        try:
            critique = {
                "type": "critique",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "approved": args.get("approved", False),
                "critiques": args.get("critiques", []),
                "strengths": args.get("strengths", []),
                "overall_assessment": args.get("overall_assessment", "")
            }

            # Log to DB
            state.db.log_event(status.spec_id, "critique_submitted", critique)

            # Also write to decisions.jsonl for compatibility
            spec_dir = status.path.parent
            decisions_file = spec_dir / "decisions.jsonl"
            with open(decisions_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(critique) + "\n")

            return {
                "content": [{
                    "type": "text",
                    "text": f"Critique submitted: {'APPROVED' if args.get('approved') else 'REJECTED'} ({len(args.get('critiques', []))} issues)"
                }],
                "_critique": critique
            }
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Error submitting critique: {e}"}],
                "error": True
            }

    @tool("report_verification", "Report verification/test results. Used by verifier.", {
        "verdict": str,  # "pass", "fail_compilation", "fail_tests"
        "compilation": dict,  # {"success": bool, "errors": [{"file": str, "line": int, "message": str}]}
        "tests": dict,  # {"total": int, "passed": int, "failed": int, "failures": [{"name": str, "message": str}]}
        "summary": str
    })
    async def report_verification(args: dict) -> dict:
        caller = args.get("_caller_spec", "unknown")
        status = state.get_spec_status(caller)

        if not status or not status.path:
            return {
                "content": [{"type": "text", "text": f"Error: Spec '{caller}' not found"}],
                "error": True
            }

        try:
            spec = load_spec(status.path)
            verdict = args.get("verdict", "fail_tests")
            compilation = args.get("compilation", {})
            tests = args.get("tests", {})

            # Update spec with errors if failed
            if verdict != "pass":
                spec.errors = Errors(
                    iteration=spec.ralph_iteration,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    compilation_success=compilation.get("success", True),
                    compilation_errors=[e.get("message", str(e)) for e in compilation.get("errors", [])],
                    test_failures=tests.get("failures", [])
                )
            else:
                spec.all_tests_passed = True

            save_spec(spec)

            # Log to DB
            state.db.log_event(status.spec_id, "verification", {
                "verdict": verdict,
                "iteration": spec.ralph_iteration,
                "compilation": compilation,
                "tests": tests,
                "summary": args.get("summary", "")
            })

            # Also write to verification.json for compatibility
            spec_dir = status.path.parent
            verification_file = spec_dir / "verification.json"
            verification_file.write_text(json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "iteration": spec.ralph_iteration,
                "verdict": verdict,
                "compilation": compilation,
                "tests": tests,
                "summary": args.get("summary", "")
            }, indent=2), encoding='utf-8')

            return {
                "content": [{
                    "type": "text",
                    "text": f"Verification reported: {verdict.upper()} - {args.get('summary', '')}"
                }],
                "_verification": {
                    "verdict": verdict,
                    "passed": verdict == "pass"
                }
            }
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Error reporting verification: {e}"}],
                "error": True
            }

    @tool("get_pipeline_status", "Get current pipeline status for a spec", {
        "spec_name": str
    })
    async def get_pipeline_status(args: dict) -> dict:
        spec_name = args.get("spec_name")

        if spec_name:
            status = state.get_spec_status(spec_name)
            if not status:
                return {
                    "content": [{"type": "text", "text": f"Spec '{spec_name}' not found"}],
                    "error": True
                }
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "name": status.name,
                        "phase": status.phase.value,
                        "depth": status.depth,
                        "iteration": status.iteration,
                        "current_agent": status.current_agent,
                        "children": status.children,
                        "error": status.error,
                        "worktree_path": str(status.worktree_path) if status.worktree_path else None
                    }, indent=2)
                }]
            }
        else:
            # Return all specs via get_status_dict
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps(get_status_dict(), indent=2)
                }]
            }

    @tool("add_root_spec", "Hot-add a new root spec to the running orchestrator", {
        "spec_path": str
    })
    async def add_root_spec(args: dict) -> dict:
        """Add a new root spec to be processed by the orchestrator."""
        spec_path_str = args.get("spec_path", "")

        if not spec_path_str:
            return {
                "content": [{"type": "text", "text": "Error: spec_path is required"}],
                "error": True
            }

        spec_path = Path(spec_path_str)

        # Handle relative paths
        if not spec_path.is_absolute():
            spec_path = Path.cwd() / spec_path

        if not spec_path.exists():
            return {
                "content": [{"type": "text", "text": f"Error: Spec not found: {spec_path}"}],
                "error": True
            }

        try:
            # Load and register the spec
            new_spec = load_spec(spec_path)

            # Check if already registered
            existing = state.get_spec_status(new_spec.name)
            if existing:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Spec '{new_spec.name}' is already registered (status: {existing.phase.value})"
                    }]
                }

            # Register as new root
            state.register_spec(
                name=new_spec.name,
                path=spec_path,
                depth=0
            )

            # Set status to ready so it gets picked up
            new_spec.status = "ready"
            save_spec(new_spec)

            # Wake the main loop if it's waiting
            if "_orchestrator_wake" in state.wake_events:
                state.wake_events["_orchestrator_wake"].set()

            log(f"Hot-added root spec: {new_spec.name}", "INFO")

            return {
                "content": [{
                    "type": "text",
                    "text": f"Successfully added root spec '{new_spec.name}' from {spec_path}. It will be processed in the next cycle."
                }]
            }
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Error adding spec: {e}"}],
                "error": True
            }

    # Create the server
    server = create_sdk_mcp_server(
        name="orchestrator",
        version="1.0.0",
        tools=[
            send_message,
            hibernate,
            signal_complete,
            check_dependency,
            request_parent_decision,
            get_my_messages,
            respond_to_message,
            # Spec manipulation tools
            update_spec_structure,
            set_research_findings,
            submit_critique,
            report_verification,
            get_pipeline_status,
            # Hot-add specs
            add_root_spec,
        ]
    )

    return server


# =============================================================================
# LOGGING
# =============================================================================

def log(msg: str, level: str = "INFO", spec: str = "", depth: int = 0):
    timestamp = datetime.now().strftime("%H:%M:%S")
    indent = "  " * depth
    prefix = {
        "INFO": "->",
        "WARN": "!",
        "ERROR": "X",
        "SUCCESS": "*",
        "SPAWN": "+",
        "HIBERNATE": "zzz",
        "WAKE": "^",
        "COMPLETE": "OK",
        "RESEARCH": "?",
        "ARCH": "#",
        "IMPL": ">",
        "VERIFY": "v",
        "INTEGRATE": "&",
        "BLOCKED": "!X",
        "WORKTREE": "wt",
    }.get(level, "-")

    spec_str = f"[{spec}] " if spec else ""
    print(f"{timestamp} {indent}{prefix} {spec_str}{msg}")


# =============================================================================
# AGENT PROMPTS & CONTEXT
# =============================================================================

def load_agent_prompt(agent_type: str) -> str:
    """Load system prompt for an agent type."""
    agent_file = Path(__file__).parent.parent / "agents" / f"{agent_type}.md"
    if agent_file.exists():
        return agent_file.read_text(encoding='utf-8')

    # Fallback prompts
    fallbacks = {
        "researcher": """You are a Researcher agent. Your job is to research libraries, patterns, and best practices for implementing a spec. Output a research.json file with your findings.""",
        "proposer": """You are a Proposer agent (architect). Analyze the spec and propose a structure (is_leaf, children, classes, interfaces). Output your proposal as JSON.""",
        "critic": """You are a Critic agent. Review the proposal and either approve it or provide specific critiques. Output {"approved": true/false, "critiques": [...]}""",
        "implementer": """You are an Implementer agent. Write the code to satisfy the spec. Use the research.json if available. Follow the style guide.""",
        "verifier": """You are a Verifier agent. Run tests and report structured results as JSON with verdict: pass/fail_compilation/fail_tests.""",
    }

    return fallbacks.get(agent_type, f"You are a {agent_type} agent.")


def load_style_guide() -> str:
    """Load STYLE.md if it exists."""
    for p in [Path.cwd(), Path.cwd().parent, Path.cwd().parent.parent]:
        style = p / "STYLE.md"
        if style.exists():
            return style.read_text(encoding='utf-8')
    return ""


def build_agent_context(
    agent_type: str,
    spec: Spec,
    extra: dict = None
) -> str:
    """Build user prompt for an agent."""
    extra = extra or {}

    spec_json = json.dumps(spec_to_dict(spec), indent=2)
    spec_dir = spec.path.parent if spec.path else Path.cwd()

    ctx = f"""# Task Context

**Spec:** {spec.name}
**Directory:** {spec_dir}
**Type:** {"Leaf" if spec.is_leaf else "Non-leaf" if spec.is_leaf is False else "Undecided"}
**Status:** {spec.status}
**Depth:** {spec.depth}

## spec.json

```json
{spec_json}
```
"""

    # Add hibernation context if waking up
    if "hibernation_context" in extra:
        hib = extra["hibernation_context"]
        ctx += f"""
## Restored Context (You were hibernating)

**Phase when hibernated:** {hib.phase.value}
**Resume trigger:** {hib.resume_trigger}
**Instructions:** {hib.instructions}

**Preserved state:**
```json
{json.dumps(hib.state, indent=2)}
```
"""

    # Add wake messages
    if "wake_messages" in extra:
        ctx += "\n## Messages That Woke You\n\n"
        for msg in extra["wake_messages"]:
            ctx += f"- **{msg.type}** from `{msg.from_spec}` (priority: {msg.priority}):\n"
            ctx += f"  ```json\n  {json.dumps(msg.payload, indent=2)}\n  ```\n"

    # Add research for implementer
    if agent_type == "implementer":
        research_path = spec_dir / "research.json"
        if research_path.exists():
            ctx += f"\n## Research Brief\n\n```json\n{research_path.read_text(encoding='utf-8')}\n```\n"

    # Add style guide
    if agent_type in ["researcher", "proposer", "critic", "implementer"]:
        style = load_style_guide()
        if style:
            ctx += f"\n## Project Style Guide\n\n{style}\n"

    # Add errors for implementer
    if agent_type == "implementer" and spec.errors:
        ctx += f"\n## Previous Errors (Iteration {spec.errors.iteration})\n"
        if spec.errors.compilation_errors:
            ctx += "Compilation:\n```\n" + "\n".join(spec.errors.compilation_errors) + "\n```\n"
        if spec.errors.test_failures:
            ctx += "Test failures:\n"
            for f in spec.errors.test_failures:
                ctx += f"- {f.get('test_name')}: {f.get('message')}\n"

    # Add proposal for critic
    if "proposal" in extra:
        ctx += f"\n## Proposal to Review\n\n```json\n{json.dumps(extra['proposal'], indent=2)}\n```\n"

    # Add critique for proposer
    if "critique" in extra:
        ctx += f"\n## Previous Critique to Address\n\n```json\n{json.dumps(extra['critique'], indent=2)}\n```\n"

    # Add children status for integration
    if "children_status" in extra:
        ctx += "\n## Children Status\n\n"
        for name, status in extra["children_status"].items():
            ctx += f"- **{name}**: {status}\n"

    ctx += f"\n---\n\nProceed with your role as {agent_type}. Output structured JSON where applicable.\n"

    return ctx


# =============================================================================
# AGENT CONFIGURATION
# =============================================================================

def load_agent_config(agent_type: str) -> dict:
    """Load agent configuration from JSON file."""
    config_path = Path(__file__).parent.parent / "agents" / "configs" / f"{agent_type}.json"

    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            log(f"Loaded config for {agent_type}: {config.get('mode')} mode, {len(config.get('allowed_tools', []))} tools", "INFO")
            return config

    # Fallback to hardcoded defaults if no config file
    log(f"No config file for {agent_type}, using defaults", "WARN")
    return FALLBACK_AGENT_CONFIG.get(agent_type, {
        "name": agent_type,
        "allowed_tools": ["Read", "Glob"],
        "forbidden_tools": [],
        "mode": "read_only",
    })


def get_agent_tools(config: dict) -> list[str]:
    """Get the full list of tools for an agent, including MCP tools."""
    base_tools = config.get("allowed_tools", ["Read", "Glob"])
    return base_tools + MCP_TOOL_NAMES


# Fallback configs if JSON not found
FALLBACK_AGENT_CONFIG = {
    "researcher": {
        "name": "researcher",
        "allowed_tools": ["Read", "Glob", "WebSearch", "WebFetch", "Write"],
        "mode": "read_write"
    },
    "proposer": {
        "name": "proposer",
        "allowed_tools": ["Read", "Glob", "Bash", "Write"],
        "mode": "read_write"
    },
    "critic": {
        "name": "critic",
        "allowed_tools": ["Read", "Glob", "Bash"],
        "mode": "read_only"
    },
    "implementer": {
        "name": "implementer",
        "allowed_tools": ["Read", "Write", "Edit", "Bash", "Glob"],
        "mode": "implement"
    },
    "verifier": {
        "name": "verifier",
        "allowed_tools": ["Read", "Bash", "Glob"],
        "mode": "verify"
    },
}

# Legacy alias for backwards compatibility
AGENT_TOOLS = {k: v["allowed_tools"] for k, v in FALLBACK_AGENT_CONFIG.items()}

MCP_TOOL_NAMES = [
    "mcp__orchestrator__send_message",
    "mcp__orchestrator__hibernate",
    "mcp__orchestrator__signal_complete",
    "mcp__orchestrator__check_dependency",
    "mcp__orchestrator__request_parent_decision",
    "mcp__orchestrator__get_my_messages",
    "mcp__orchestrator__respond_to_message",
    # Spec manipulation tools
    "mcp__orchestrator__update_spec_structure",
    "mcp__orchestrator__set_research_findings",
    "mcp__orchestrator__submit_critique",
    "mcp__orchestrator__report_verification",
    "mcp__orchestrator__get_pipeline_status",
]


# =============================================================================
# AGENT SPAWNING
# =============================================================================

def extract_json_blocks(text: str) -> list[dict]:
    """Extract JSON blocks from agent response."""
    blocks = []
    for match in re.findall(r'```json\s*([\s\S]*?)\s*```', text):
        try:
            blocks.append(json.loads(match))
        except Exception:
            continue
    return blocks


async def spawn_agent(
    agent_type: str,
    spec: Spec,
    mcp_server,
    extra_context: dict = None,
    worktree_path: Optional[Path] = None
) -> dict:
    """
    Spawn an agent and return its result.

    Args:
        agent_type: Type of agent to spawn
        spec: The spec being processed
        mcp_server: MCP server for agent communication
        extra_context: Additional context for the agent
        worktree_path: Optional path to worktree (used for implementer)

    Returns:
        {
            "success": bool,
            "response": str,
            "json_blocks": list[dict],
            "hibernation_request": optional dict,
            "completion_signal": optional dict,
        }
    """
    extra_context = extra_context or {}
    state = get_state()

    # Check agent limit via DB
    summary = state.db.get_pipeline_summary()
    total_runs = len(state.db.get_events(type="agent_spawned"))

    if total_runs >= CONFIG.max_total_agents:
        return {"success": False, "error": "Max agents exceeded"}

    # Log agent spawn
    status = state.get_spec_status(spec.name)
    if status:
        run_id = state.start_agent(spec.name, agent_type, status.iteration)
        state.db.log_event(status.spec_id, "agent_spawned", {
            "agent_type": agent_type,
            "run_id": run_id,
            "worktree_path": str(worktree_path) if worktree_path else None
        })
    else:
        run_id = -1

    log(f"Spawning {agent_type} (run #{run_id})", "SPAWN", spec.name, spec.depth)

    # Update spec status
    if status:
        status.current_agent = agent_type

    # === DRY RUN ===
    if CONFIG.dry_run:
        log(f"[DRY RUN] Would run {agent_type}", "INFO", spec.name, spec.depth)
        if run_id > 0:
            state.complete_agent(run_id, True, {"dry_run": True})
        return {"success": True, "response": "", "json_blocks": [], "dry_run": True}

    # === SIMULATED ===
    if not CONFIG.live:
        log(f"[SIMULATED] {agent_type} completed", "INFO", spec.name, spec.depth)
        if run_id > 0:
            state.complete_agent(run_id, True, {"simulated": True})
        return {"success": True, "response": "", "json_blocks": [], "simulated": True}

    # === LIVE ===
    try:
        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, AssistantMessage, TextBlock, ToolResultBlock, ResultMessage
    except ImportError:
        return {"success": False, "error": "pip install claude-agent-sdk"}

    # Determine working directory
    # For implementer, use worktree if available; otherwise use spec directory
    if agent_type == "implementer" and worktree_path:
        cwd = worktree_path
        log(f"Using worktree: {worktree_path}", "WORKTREE", spec.name, spec.depth)
    else:
        cwd = spec.path.parent if spec.path else Path.cwd()

    # Load agent configuration from JSON
    agent_config = load_agent_config(agent_type)

    system_prompt = load_agent_prompt(agent_type)
    user_prompt = build_agent_context(agent_type, spec, extra_context)

    # Inject caller spec and config info into prompt
    user_prompt += f"\n\n[SYSTEM: Your spec name for MCP calls is '{spec.name}']\n"
    user_prompt += f"[SYSTEM: You are running in {agent_config.get('mode', 'unknown')} mode]\n"
    user_prompt += f"[SYSTEM: Available tools: {', '.join(agent_config.get('allowed_tools', []))}]\n"
    if worktree_path:
        user_prompt += f"[SYSTEM: Working in isolated worktree: {worktree_path}]\n"

    # Get tools from config
    tools = get_agent_tools(agent_config)

    # Build options with hooks for enforcement
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        allowed_tools=tools,
        mcp_servers={"orchestrator": mcp_server},
        permission_mode="bypassPermissions",
        cwd=str(cwd),
        setting_sources=["project", "user"],  # Include user MCP servers (e.g., unityMCP)
        model=CONFIG.model,
    )

    # Add enforcement and message delivery hooks if available
    try:
        from hooks import create_enforcement_hooks
        from message_hooks import create_message_delivery_hooks, merge_hooks

        enforcement_hooks = create_enforcement_hooks(
            agent_config,
            log_func=lambda msg: log(msg, "INFO", spec.name, spec.depth)
        )
        message_hooks = create_message_delivery_hooks(
            spec_id=spec.name,
            log_func=lambda msg: log(msg, "INFO", spec.name, spec.depth)
        )

        # Merge both hook sets
        if enforcement_hooks and message_hooks:
            options.hooks = merge_hooks(enforcement_hooks, message_hooks)
        elif enforcement_hooks:
            options.hooks = enforcement_hooks
        elif message_hooks:
            options.hooks = message_hooks
    except ImportError as e:
        log(f"Hooks not available: {e}", "WARN", spec.name, spec.depth)

    result = {
        "success": False,
        "response": "",
        "json_blocks": [],
        "hibernation_request": None,
        "completion_signal": None,
    }

    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(user_prompt)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            result["response"] += block.text
                        elif hasattr(block, 'input'):
                            # Tool use - check for special signals
                            pass

                elif isinstance(message, ToolResultBlock):
                    # Check for hibernation/completion signals in tool results
                    if hasattr(message, 'content'):
                        try:
                            content = json.loads(message.content) if isinstance(message.content, str) else message.content
                            if isinstance(content, dict):
                                if "_hibernation_request" in content:
                                    result["hibernation_request"] = content["_hibernation_request"]
                                if "_completion_signal" in content:
                                    result["completion_signal"] = content["_completion_signal"]
                        except Exception:
                            pass

                elif isinstance(message, ResultMessage):
                    result["success"] = not message.is_error

        result["json_blocks"] = extract_json_blocks(result["response"])

    except Exception as e:
        log(f"Agent error: {e}", "ERROR", spec.name, spec.depth)
        result["error"] = str(e)
        traceback.print_exc()

    # Complete agent run tracking
    if run_id > 0:
        state.complete_agent(run_id, result["success"], {
            "response_length": len(result["response"]),
            "json_blocks_count": len(result["json_blocks"]),
            "hibernated": result["hibernation_request"] is not None
        })

    if status:
        status.current_agent = None

    return result


# =============================================================================
# SPEC PROCESSING
# =============================================================================

async def run_researcher(spec: Spec, mcp_server) -> bool:
    """Run researcher to gather context before implementation."""
    log("Running researcher", "RESEARCH", spec.name, spec.depth)

    state = get_state()
    status = state.get_spec_status(spec.name)
    if status:
        state.update_phase(spec.name, Phase.RESEARCH)

    result = await spawn_agent("researcher", spec, mcp_server)

    if not result.get("success"):
        log(f"Researcher failed: {result.get('error')}", "ERROR", spec.name, spec.depth)
        return False

    # Check for research output
    spec_dir = spec.path.parent if spec.path else Path.cwd()
    research_path = spec_dir / "research.json"

    # In live mode, researcher should have written research.json
    # In simulated mode, create a stub
    if not CONFIG.live and not research_path.exists():
        research_path.write_text(json.dumps({
            "spec_name": spec.name,
            "researched_at": datetime.now(timezone.utc).isoformat(),
            "topics": [],
            "recommendations": ["[Simulated research]"]
        }, indent=2), encoding='utf-8')

    log("Research complete", "SUCCESS", spec.name, spec.depth)
    return True


async def run_architecture_loop(spec: Spec, mcp_server) -> tuple[bool, Optional[dict]]:
    """Run Proposer <-> Critic loop."""
    log("Starting architecture loop", "ARCH", spec.name, spec.depth)

    state = get_state()
    status = state.get_spec_status(spec.name)
    if status:
        state.update_phase(spec.name, Phase.ARCHITECTURE)

    proposal = None
    critique = None

    for iteration in range(1, CONFIG.max_arch_iterations + 1):
        log(f"Architecture iteration {iteration}/{CONFIG.max_arch_iterations}", "ARCH", spec.name, spec.depth)

        # Proposer
        extra = {}
        if critique:
            extra["critique"] = critique

        result = await spawn_agent("proposer", spec, mcp_server, extra)
        if not result.get("success"):
            return False, None

        # Extract proposal
        for block in result.get("json_blocks", []):
            if "structure" in block or "is_leaf" in block:
                proposal = block
                break

        if not proposal and (CONFIG.dry_run or not CONFIG.live):
            proposal = {"structure": {"is_leaf": True}, "rationale": "Simulated"}

        if not proposal:
            log("No proposal extracted", "WARN", spec.name, spec.depth)
            continue

        # Critic
        result = await spawn_agent("critic", spec, mcp_server, {"proposal": proposal})
        if not result.get("success"):
            return False, None

        # Extract critique
        for block in result.get("json_blocks", []):
            if "approved" in block:
                critique = block
                break

        if not critique and (CONFIG.dry_run or not CONFIG.live):
            critique = {"approved": iteration >= 2, "critiques": []}

        if critique and critique.get("approved"):
            log("Architecture approved", "SUCCESS", spec.name, spec.depth)
            return True, proposal

    log("Architecture loop exhausted", "WARN", spec.name, spec.depth)
    return True, proposal


async def run_scaffold_phase(spec: Spec, mcp_server) -> str:
    """Run scaffold phase - generate stubs and await approval.

    Returns:
        "skipped" - No classes to scaffold
        "approved" - Stubs already approved, continue to implementation
        "hibernating" - Awaiting stub approval
        "failed" - Scaffold generation failed
    """
    state = get_state()

    # Skip scaffold only if spec has no classes defined
    has_classes = spec.classes and len(spec.classes) > 0
    if not has_classes:
        log("No classes to scaffold, skipping", "SCAFFOLD", spec.name, spec.depth)
        return "skipped"

    # Check if stubs already approved
    if getattr(spec, 'stubs_approved', False):
        log("Stubs already approved", "SCAFFOLD", spec.name, spec.depth)
        return "approved"

    state.update_phase(spec.name, Phase.SCAFFOLD)
    log("Running scaffold phase", "SCAFFOLD", spec.name, spec.depth)

    try:
        # Import here to avoid circular imports
        import sys
        lib_path = str(Path(__file__).parent.parent / "lib")
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)

        from scaffold_phase import run_scaffold, await_stub_approval

        # Generate stubs
        result = await run_scaffold(str(spec.path))

        if not result.success:
            log(f"Scaffold failed: {result.error}", "ERROR", spec.name, spec.depth)
            return "failed"

        if result.generated_files:
            log(f"Generated {len(result.generated_files)} stub files", "SCAFFOLD", spec.name, spec.depth)
            for f in result.generated_files:
                log(f"  - {f}", "SCAFFOLD", spec.name, spec.depth)

        # Check approval status
        approval = await_stub_approval(str(spec.path))

        if hasattr(approval, 'reason'):  # HibernationRequest
            log(f"Awaiting stub approval: {approval.reason}", "SCAFFOLD", spec.name, spec.depth)
            state.flag_for_review(spec.name, "awaiting_stub_approval", {
                "generated_files": list(result.generated_files),
                "message": "Review generated stubs and run /approve-stubs to continue"
            })
            return "hibernating"

        # Stubs approved
        return "approved"

    except Exception as e:
        log(f"Scaffold phase error: {e}", "ERROR", spec.name, spec.depth)
        return "failed"


async def run_implementation_loop(spec: Spec, mcp_server) -> bool:
    """Run Implementer <-> Verifier loop with worktree isolation."""
    log("Starting implementation loop", "IMPL", spec.name, spec.depth)

    state = get_state()
    status = state.get_spec_status(spec.name)

    # Create worktree for this spec if worktree management is available
    worktree_path = None
    if state.worktree_mgr and status:
        # Create worktree
        worktree_path = state.create_worktree_for_spec(
            str(spec.path),
            status.parent
        )

        if worktree_path:
            # Store worktree path in status
            status.worktree_path = worktree_path
            state.set_spec_status(spec.name, status)
            log(f"Created worktree at {worktree_path}", "WORKTREE", spec.name, spec.depth)

            # Claim files based on spec.classes
            claim_result = state.claim_files_for_spec(str(spec.path), spec)
            if not claim_result.success:
                log(f"File ownership conflict: {claim_result.message}", "ERROR", spec.name, spec.depth)
                # Flag for review with conflict details
                state.flag_for_review(spec.name, "file_ownership_conflict", {
                    "conflicts": claim_result.conflicts,
                    "message": claim_result.message
                })
                return False
            elif claim_result.patterns:
                log(f"Claimed files: {claim_result.patterns}", "INFO", spec.name, spec.depth)

    while (spec.ralph_iteration or 0) < CONFIG.max_iterations:
        spec.ralph_iteration += 1
        log(f"Implementation iteration {spec.ralph_iteration}/{CONFIG.max_iterations}", "IMPL", spec.name, spec.depth)

        if status:
            state.update_phase(spec.name, Phase.IMPLEMENTATION)
            status.iteration = spec.ralph_iteration

        # Implementer - pass worktree_path for isolated execution
        result = await spawn_agent("implementer", spec, mcp_server, worktree_path=worktree_path)

        # Check for hibernation
        if result.get("hibernation_request"):
            log("Implementer hibernating", "HIBERNATE", spec.name, spec.depth)
            ctx = HibernationContext(
                spec_name=spec.name,
                agent_type="implementer",
                phase=Phase.IMPLEMENTATION,
                state=result["hibernation_request"]["state"],
                resume_trigger=result["hibernation_request"]["resume_trigger"],
                instructions=result["hibernation_request"]["instructions"],
                exported_at=datetime.now(timezone.utc).isoformat()
            )
            state.hibernate_agent(ctx)
            return True  # Successfully hibernated, not failed

        if not result.get("success"):
            return False

        # Verifier
        if status:
            state.update_phase(spec.name, Phase.VERIFICATION)

        result = await spawn_agent("verifier", spec, mcp_server, worktree_path=worktree_path)
        if not result.get("success"):
            return False

        # Parse verification result
        verification = None
        for block in result.get("json_blocks", []):
            if "verdict" in block:
                verification = block
                break

        # Check for pass
        if verification and verification.get("verdict") == "pass":
            spec.all_tests_passed = True
            spec.status = "complete"
            save_spec(spec)
            log("All tests passed!", "SUCCESS", spec.name, spec.depth)
            return True

        # Simulated success
        if (CONFIG.dry_run or not CONFIG.live) and spec.ralph_iteration >= 2:
            spec.all_tests_passed = True
            spec.status = "complete"
            save_spec(spec)
            log("Tests passed (simulated)", "SUCCESS", spec.name, spec.depth)
            return True

        # Apply errors
        if verification:
            spec.errors = Errors(
                iteration=spec.ralph_iteration,
                timestamp=datetime.now(timezone.utc).isoformat(),
                compilation_success=verification.get("compilation", {}).get("success", True),
                compilation_errors=[e.get("message", str(e)) for e in verification.get("compilation", {}).get("errors", [])],
                test_failures=verification.get("tests", {}).get("failures", [])
            )

        save_spec(spec)

    log("Max iterations reached", "ERROR", spec.name, spec.depth)
    return False


async def run_integration_tests(spec: Spec, mcp_server) -> bool:
    """Run integration tests after all children complete."""
    log("Running integration tests", "INTEGRATE", spec.name, spec.depth)

    state = get_state()
    status = state.get_spec_status(spec.name)
    if status:
        state.update_phase(spec.name, Phase.INTEGRATION)

    # Gather children status
    children_status = {}
    for child_name in (status.children if status else []):
        child_status = state.get_spec_status(child_name)
        children_status[child_name] = child_status.phase.value if child_status else "unknown"

    result = await spawn_agent("verifier", spec, mcp_server, {
        "mode": "integration",
        "children_status": children_status
    })

    if not result.get("success"):
        return False

    # Parse result
    for block in result.get("json_blocks", []):
        if "verdict" in block:
            if block["verdict"] == "pass":
                spec.integration_tests_passed = True
                log("Integration tests passed", "SUCCESS", spec.name, spec.depth)
                return True
            else:
                log(f"Integration tests failed: {block.get('summary', 'unknown')}", "ERROR", spec.name, spec.depth)
                state.flag_for_review(spec.name, "integration_failed", block)
                return False

    # Simulated success
    if CONFIG.dry_run or not CONFIG.live:
        spec.integration_tests_passed = True
        log("Integration tests passed (simulated)", "SUCCESS", spec.name, spec.depth)
        return True

    return False


def apply_proposal_to_spec(spec: Spec, proposal: dict):
    """Apply architecture proposal to spec."""
    if not proposal:
        return

    struct = proposal.get("structure", proposal)

    if "is_leaf" in struct:
        spec.is_leaf = struct["is_leaf"]

    if "children" in struct:
        spec.children = [
            Child(**c) if isinstance(c, dict) else c
            for c in struct["children"]
        ]

    if "classes" in struct:
        spec.classes = [
            ClassDef(**c) if isinstance(c, dict) else c
            for c in struct["classes"]
        ]

    if "shared_types" in proposal.get("interfaces", {}):
        spec.shared_types = [
            SharedType(**s) if isinstance(s, dict) else s
            for s in proposal["interfaces"]["shared_types"]
        ]


def scaffold_children(spec: Spec) -> list[str]:
    """Create child spec directories."""
    if not spec.path:
        return []

    children_dir = spec.path.parent / "children"
    children_dir.mkdir(exist_ok=True)
    created = []

    # Shared types
    if spec.shared_types:
        shared_dir = children_dir / "shared"
        shared_dir.mkdir(exist_ok=True)
        shared_path = shared_dir / "spec.json"
        if not shared_path.exists():
            shared_spec = create_shared_spec(spec, shared_path)
            save_spec(shared_spec, shared_path)
            created.append("shared")
            log("Created shared/", "INFO", spec.name, spec.depth)

    # Children
    for child_def in spec.children:
        child_dir = children_dir / child_def.name
        child_dir.mkdir(exist_ok=True)
        child_path = child_dir / "spec.json"
        if not child_path.exists():
            child_spec = create_child_spec(spec, child_def, child_path)
            if spec.shared_types and "shared" not in child_spec.depends_on:
                child_spec.depends_on.insert(0, "shared")
            save_spec(child_spec, child_path)
            created.append(child_def.name)
            log(f"Created {child_def.name}/", "INFO", spec.name, spec.depth)

    return created


# =============================================================================
# MAIN PROCESSING LOGIC
# =============================================================================

async def process_leaf(spec_path: Path, mcp_server, depth: int) -> bool:
    """Process a leaf spec: Research -> Implement -> Verify"""
    spec = load_spec(spec_path)
    spec.depth = depth

    # Validate and optionally fix spec paths before processing
    path_warnings = validate_spec_paths(spec)
    if path_warnings:
        if CONFIG.auto_fix_paths:
            # Auto-fix protected paths by redirecting to src/
            changes = fix_protected_paths(spec)
            for change in changes:
                log(f"Auto-fixed path: {change['old_location']} -> {change['new_location']}",
                    "INFO", spec.name, depth)
            save_spec(spec)
        else:
            # Just warn about protected paths
            for warning in path_warnings:
                log(f"WARNING: {warning['message']}", "WARN", spec.name, depth)

    # Detect project type for later use (e.g., Unity test handling)
    project_type = detect_project_type(spec_path)
    if project_type != "unknown":
        log(f"Detected project type: {project_type}", "INFO", spec.name, depth)

    spec.status = "in_progress"
    save_spec(spec)

    state = get_state()
    spec_id = state.register_spec(
        name=spec.name,
        path=spec_path,
        depth=depth,
        depends_on=spec.depends_on,
        is_leaf=True
    )

    status = state.get_spec_status(spec.name)

    # Research first
    if not await run_researcher(spec, mcp_server):
        state.update_phase(spec.name, Phase.FAILED)
        return False

    # Scaffold phase (optional - generates stubs and awaits approval)
    scaffold_result = await run_scaffold_phase(spec, mcp_server)
    if scaffold_result == "hibernating":
        return True  # Awaiting stub approval
    elif scaffold_result == "failed":
        state.update_phase(spec.name, Phase.FAILED)
        return False
    # scaffold_result == "skipped" or "approved" -> continue to implementation

    # Implementation loop (with worktree isolation)
    success = await run_implementation_loop(spec, mcp_server)

    # Check if hibernated vs completed
    if state.is_hibernating(spec.name):
        return True  # Will resume later

    spec = load_spec(spec_path)

    if success:
        state.update_phase(spec.name, Phase.COMPLETE)
        spec.status = "complete"

        # Run completion hooks if defined
        hooks = load_hooks_from_spec(spec_path)
        if hooks:
            log("Running completion hooks", "HOOKS", spec.name, spec.depth)
            hook_results = run_hooks(
                spec_path,
                hooks,
                log_func=lambda msg: log(msg, "HOOKS", spec.name, spec.depth)
            )
            failed_hooks = [r for r in hook_results if not r.get("success")]
            if failed_hooks:
                log(f"Warning: {len(failed_hooks)} hook(s) failed", "WARN", spec.name, spec.depth)

        # Merge completed work into parent branch
        if status:
            merge_result = state.merge_completed_spec(str(spec_path), status.parent)
            if merge_result.conflict:
                # Merge conflict - flag for review
                state.flag_for_review(spec.name, "merge_conflict", {
                    "conflict_files": merge_result.conflict_files,
                    "message": merge_result.message
                })
                spec.status = "blocked"
                state.update_phase(spec.name, Phase.BLOCKED)
            else:
                # Clean up worktree and release file claims
                state.cleanup_spec_worktree(str(spec_path), release_files=True)
    else:
        state.update_phase(spec.name, Phase.FAILED)
        spec.status = "failed"
        state.flag_for_review(spec.name, "implementation_failed", {
            "iterations": spec.ralph_iteration,
            "errors": spec.errors.__dict__ if spec.errors else None
        })

        # Clean up worktree on failure but keep it for debugging (release file claims only)
        if status:
            state.cleanup_spec_worktree(str(spec_path), release_files=True)

    save_spec(spec)

    # Notify parent if we have one
    if status and status.parent:
        try:
            state.add_message(
                from_spec=spec.name,
                to_spec=status.parent,
                msg_type="child_complete",
                payload={"child": spec.name, "success": success},
                priority=Priority.NORMAL
            )
        except Exception as e:
            # Don't crash if parent notification fails (e.g., parent spec was deleted)
            log(f"Failed to notify parent '{status.parent}': {e}", "WARN", spec.name, spec.depth)

    return success


async def process_non_leaf(spec_path: Path, mcp_server, depth: int) -> bool:
    """Process a non-leaf spec: Architecture -> Scaffold -> Wait for children -> Integrate"""
    spec = load_spec(spec_path)
    spec.depth = depth
    spec.status = "in_progress"
    save_spec(spec)

    state = get_state()
    spec_id = state.register_spec(
        name=spec.name,
        path=spec_path,
        depth=depth,
        depends_on=spec.depends_on,
        is_leaf=False
    )

    status = state.get_spec_status(spec.name)

    # Check for existing hibernation
    if state.is_hibernating(spec.name):
        ctx = state.wake_agent(spec.name)
        log(f"Waking from hibernation", "WAKE", spec.name, depth)

        # Get wake messages
        wake_msgs = state.get_pending_messages(spec.name)

        # Process based on phase
        if ctx.phase == Phase.ARCHITECTURE:
            # Continue architecture somehow? Usually shouldn't happen
            pass

        # If waiting for children, check if all done
        if state.all_children_complete(spec.name):
            return await finalize_non_leaf(spec, mcp_server, status)

    # Architecture if needed
    if spec.is_leaf is None:
        success, proposal = await run_architecture_loop(spec, mcp_server)
        if not success:
            state.update_phase(spec.name, Phase.FAILED)
            return False

        apply_proposal_to_spec(spec, proposal)
        save_spec(spec)
        spec = load_spec(spec_path)

        # Did architecture decide this is actually a leaf?
        if spec.is_leaf is True:
            return await process_leaf(spec_path, mcp_server, depth)

    # Scaffold children
    created = scaffold_children(spec)
    status.children = created
    state.set_spec_status(spec.name, status)

    # Register children in state with parent linkage
    children_dir = spec_path.parent / "children"
    for child_name in created:
        child_path = children_dir / child_name / "spec.json"
        if child_path.exists():
            child_spec = load_spec(child_path)
            state.register_spec(
                name=child_name,
                path=child_path,
                depth=depth + 1,
                parent=spec.name,
                depends_on=child_spec.depends_on
            )

    log(f"Scaffolded {len(created)} children, hibernating", "HIBERNATE", spec.name, depth)

    # Hibernate
    ctx = HibernationContext(
        spec_name=spec.name,
        agent_type="coordinator",
        phase=Phase.PENDING,
        state={"children": created},
        resume_trigger="all_children_complete",
        instructions="Check if all children complete, then run integration",
        exported_at=datetime.now(timezone.utc).isoformat()
    )
    state.hibernate_agent(ctx)

    return True  # Successfully setup, children will be processed by main loop


async def finalize_non_leaf(spec: Spec, mcp_server, status: SpecStatus) -> bool:
    """Run integration tests and finalize a non-leaf after all children complete."""
    log("All children complete, running integration", "INTEGRATE", spec.name, spec.depth)

    state = get_state()
    success = await run_integration_tests(spec, mcp_server)

    if success:
        state.update_phase(spec.name, Phase.COMPLETE)
        spec.status = "complete"
        spec.integration_tests_passed = True

        # Run completion hooks if defined
        spec_path = Path(status.path) if status else None
        if spec_path:
            hooks = load_hooks_from_spec(spec_path)
            if hooks:
                log("Running completion hooks", "HOOKS", spec.name, spec.depth)
                hook_results = run_hooks(
                    spec_path,
                    hooks,
                    log_func=lambda msg: log(msg, "HOOKS", spec.name, spec.depth)
                )
                failed_hooks = [r for r in hook_results if not r.get("success")]
                if failed_hooks:
                    log(f"Warning: {len(failed_hooks)} hook(s) failed", "WARN", spec.name, spec.depth)
    else:
        state.update_phase(spec.name, Phase.BLOCKED)
        spec.status = "blocked"
        state.flag_for_review(spec.name, "integration_failed", {})

    save_spec(spec)

    # Notify parent
    if status.parent:
        try:
            state.add_message(
                from_spec=spec.name,
                to_spec=status.parent,
                msg_type="child_complete",
                payload={"child": spec.name, "success": success},
                priority=Priority.NORMAL
            )
        except Exception as e:
            # Don't crash if parent notification fails (e.g., parent spec was deleted)
            log(f"Failed to notify parent '{status.parent}': {e}", "WARN", spec.name, spec.depth)

    return success


async def process_spec(spec_path: Path, mcp_server, depth: int = 0) -> bool:
    """Determine spec type and process accordingly."""
    spec = load_spec(spec_path)

    if spec.is_leaf is True:
        return await process_leaf(spec_path, mcp_server, depth)
    elif spec.is_leaf is False:
        return await process_non_leaf(spec_path, mcp_server, depth)
    else:
        # Undecided - run architecture
        return await process_non_leaf(spec_path, mcp_server, depth)


# =============================================================================
# MAIN ORCHESTRATOR LOOP
# =============================================================================

async def orchestrator_main(root_spec_paths: list[Path]):
    """
    Main orchestration loop.

    1. Initialize root specs (supports multiple)
    2. Process specs in parallel (respecting dependencies)
    3. Handle hibernation/wake cycles
    4. Trigger integration when siblings complete
    5. Continue until all complete or blocked
    """
    if len(root_spec_paths) == 1:
        log(f"Starting orchestrator for {root_spec_paths[0]}", "INFO")
    else:
        log(f"Starting orchestrator for {len(root_spec_paths)} root specs", "INFO")

    # Initialize database and state
    db = get_db()
    global STATE
    STATE = OrchestratorState(db)

    log(f"Database initialized at {db.db_path}", "INFO")

    # Clean up stale agent runs from previous crashed sessions
    stale_cleanup = db.cleanup_stale_runs()
    if stale_cleanup["cleaned"] > 0:
        log(f"Cleaned up {stale_cleanup['cleaned']} stale agent runs", "INFO")

    # Initialize worktree management
    STATE.init_worktree_management()

    # Clean up orphaned worktrees from previous runs
    STATE.cleanup_orphaned_worktrees()

    # Create MCP server
    mcp_server = create_mcp_tools()

    # Initialize all root specs
    for root_spec_path in root_spec_paths:
        root_spec = load_spec(root_spec_path)
        STATE.register_spec(
            name=root_spec.name,
            path=root_spec_path,
            depth=0
        )
        log(f"Registered root spec: {root_spec.name}", "INFO")

    # Track root spec names for completion checking
    root_spec_names = []
    for root_spec_path in root_spec_paths:
        root_spec = load_spec(root_spec_path)
        root_spec_names.append(root_spec.name)

    # Start processing all roots
    for root_spec_path in root_spec_paths:
        await process_spec(root_spec_path, mcp_server, depth=0)

    # Create wake event for hot-adding specs
    STATE.wake_events["_orchestrator_wake"] = asyncio.Event()

    # Main loop
    iteration = 0
    max_iterations = 1000  # Safety limit

    while iteration < max_iterations:
        iteration += 1

        # Check for completion of ALL root specs (including hot-added ones)
        # Root specs are those with depth=0
        all_roots_terminal = True
        active_roots = 0
        for name, status in STATE._specs.items():
            if status.depth == 0:  # Root spec
                active_roots += 1
                if status.phase not in [Phase.COMPLETE, Phase.FAILED, Phase.BLOCKED]:
                    all_roots_terminal = False

        if all_roots_terminal and active_roots > 0:
            log("All root specs reached terminal state", "INFO")
            break

        # Get ready specs
        ready = STATE.get_ready_specs()

        if not ready:
            # Check for hibernating specs that can be woken
            for name in STATE.get_hibernating_specs():
                ctx = STATE.get_hibernation_context(name)
                if ctx and ctx.resume_trigger == "all_children_complete":
                    if STATE.all_children_complete(name):
                        status = STATE.get_spec_status(name)
                        if status:
                            spec = load_spec(status.path)
                            STATE.wake_agent(name)
                            await finalize_non_leaf(spec, mcp_server, status)
                            break
            else:
                # Nothing to do, check if stuck
                if not STATE.active_tasks and not STATE.get_hibernating_specs():
                    log("No work remaining and nothing hibernating", "WARN")
                    break

                # Wait a bit
                await asyncio.sleep(0.1)
                continue

        # Process ready specs in parallel (up to limit)
        batch = ready[:CONFIG.max_concurrent_agents - len(STATE.active_tasks)]

        if batch:
            tasks = []
            for name in batch:
                status = STATE.get_spec_status(name)
                if status and status.path:
                    task = asyncio.create_task(
                        process_spec(status.path, mcp_server, status.depth)
                    )
                    STATE.active_tasks[name] = task
                    tasks.append((name, task))

            # Wait for at least one to complete
            if tasks:
                done, pending = await asyncio.wait(
                    [t for _, t in tasks],
                    return_when=asyncio.FIRST_COMPLETED
                )

                # Clean up completed tasks
                for name, task in tasks:
                    if task in done:
                        del STATE.active_tasks[name]
                        try:
                            result = task.result()
                            if not result:
                                status = STATE.get_spec_status(name)
                                if status:
                                    STATE.update_phase(name, Phase.FAILED)
                        except Exception as e:
                            log(f"Task failed: {e}", "ERROR", name)
                            status = STATE.get_spec_status(name)
                            if status:
                                STATE.update_phase(name, Phase.FAILED)

    # Final status
    log("=" * 60, "INFO")
    log("ORCHESTRATION COMPLETE", "COMPLETE")

    summary = STATE.db.get_pipeline_summary()
    log(f"Total specs: {summary['total_specs']}", "INFO")
    log(f"By status: {summary['by_status']}", "INFO")

    complete_count = summary['by_status'].get('complete', 0)
    failed_count = summary['by_status'].get('failed', 0)
    blocked_count = summary['by_status'].get('blocked', 0)

    log(f"Complete: {complete_count}", "SUCCESS")
    if failed_count:
        log(f"Failed: {failed_count}", "ERROR")
    if blocked_count:
        log(f"Blocked (needs review): {blocked_count}", "BLOCKED")

    needs_review = STATE.get_needs_review()
    if needs_review:
        log(f"Items flagged for human review: {len(needs_review)}", "WARN")
        for item in needs_review:
            log(f"  - {item['spec']}: {item['reason']}", "WARN")

    return failed_count == 0 and blocked_count == 0


# =============================================================================
# STATUS ENDPOINT (for user-facing Claude)
# =============================================================================

def get_status_dict() -> dict:
    """Get current orchestrator status as a dict."""
    state = get_state()
    summary = state.db.get_pipeline_summary()

    specs_dict = {}
    for name, s in state._specs.items():
        specs_dict[name] = {
            "phase": s.phase.value,
            "depth": s.depth,
            "current_agent": s.current_agent,
            "iteration": s.iteration,
            "children": s.children,
            "worktree_path": str(s.worktree_path) if s.worktree_path else None,
        }

    return {
        "total_specs": summary['total_specs'],
        "specs": specs_dict,
        "active_tasks": list(state.active_tasks.keys()),
        "hibernating": state.get_hibernating_specs(),
        "needs_review": state.get_needs_review(),
        "summary": {
            "total": summary['total_specs'],
            "complete": summary['by_status'].get('complete', 0),
            "in_progress": summary['by_status'].get('in_progress', 0),
            "failed": summary['by_status'].get('failed', 0),
            "blocked": summary['by_status'].get('blocked', 0),
        }
    }


async def status_server(port: int = 8765):
    """Simple HTTP server for status queries."""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import threading

    class StatusHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/status":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(get_status_dict(), indent=2).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass  # Suppress logging

    server = HTTPServer(("localhost", port), StatusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log(f"Status server running on http://localhost:{port}/status", "INFO")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Ralph Orchestrator v4")
    parser.add_argument("--spec", action="append", required=True,
                        help="Path to root spec.json (can specify multiple)")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without executing")
    parser.add_argument("--live", action="store_true", help="Actually call Agent SDK")
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--max-arch-iterations", type=int, default=5)
    parser.add_argument("--max-agents", type=int, default=100)
    parser.add_argument("--max-concurrent", type=int, default=5)
    parser.add_argument("--model", default="claude-opus-4-5-20251101")
    parser.add_argument("--status-port", type=int, default=0, help="Port for status server (0=disabled)")
    parser.add_argument("--db-path", type=str, default=None, help="Path to database file")

    args = parser.parse_args()

    CONFIG.max_depth = args.max_depth
    CONFIG.max_iterations = args.max_iterations
    CONFIG.max_arch_iterations = args.max_arch_iterations
    CONFIG.max_total_agents = args.max_agents
    CONFIG.max_concurrent_agents = args.max_concurrent
    CONFIG.dry_run = args.dry_run
    CONFIG.live = args.live
    CONFIG.model = args.model

    # Validate all spec paths
    spec_paths = [Path(s) for s in args.spec]
    for spec_path in spec_paths:
        if not spec_path.exists():
            print(f"ERROR: Spec not found: {spec_path}")
            sys.exit(1)

    # Acquire singleton lock
    if not acquire_singleton_lock():
        print("ERROR: Another orchestrator instance is already running.")
        print("Check .orchestrator.pid for the running process ID.")
        print("Use /pipeline-status to check its progress, or kill it to start a new one.")
        sys.exit(1)

    # Initialize DB with custom path if provided
    if args.db_path:
        from ralph_db import RalphDB
        global STATE
        STATE = OrchestratorState(RalphDB(Path(args.db_path)))

    mode = "DRY RUN" if CONFIG.dry_run else ("LIVE" if CONFIG.live else "SIMULATED")

    print("=" * 60)
    print(f"RALPH ORCHESTRATOR v4 [{mode}]")
    print("=" * 60)
    if len(spec_paths) == 1:
        print(f"Root Spec:       {spec_paths[0]}")
    else:
        print(f"Root Specs:      {len(spec_paths)} specs")
        for sp in spec_paths:
            print(f"                 - {sp}")
    print(f"Max Depth:       {CONFIG.max_depth}")
    print(f"Max Concurrent:  {CONFIG.max_concurrent_agents}")
    print(f"Max Agents:      {CONFIG.max_total_agents}")
    print(f"Model:           {CONFIG.model}")
    print("=" * 60)

    async def run():
        if args.status_port > 0:
            await status_server(args.status_port)

        return await orchestrator_main(spec_paths)

    try:
        success = asyncio.run(run())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(130)
    except Exception as e:
        print(f"\nFATAL: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
