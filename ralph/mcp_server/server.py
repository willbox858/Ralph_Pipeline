"""
MCP Server for the Ralph pipeline.

Uses the official MCP Python SDK (FastMCP) to provide tools
for the Interface Agent to interact with the orchestrator.

This server is a thin frontend that:
1. Receives MCP tool calls
2. Translates them to Orchestrator method calls
3. Returns results

All orchestration logic lives in the Orchestrator.
"""

from typing import Dict, Any, List, Optional
from pathlib import Path
import sys
import logging

# Configure logging to stderr (stdout breaks MCP protocol)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("ralph")

# Try to import the official MCP SDK
try:
    from mcp.server.fastmcp import FastMCP
    HAS_MCP_SDK = True
except ImportError:
    HAS_MCP_SDK = False


def find_project_root() -> Path:
    """Find the project root by looking for ralph.config.json."""
    cwd = Path.cwd()

    # Check current dir and parents
    for path in [cwd, *cwd.parents]:
        if (path / "ralph.config.json").exists():
            return path
        if path == path.parent:
            break

    return cwd


# =============================================================================
# ORCHESTRATOR SINGLETON
# =============================================================================

_orchestrator: Optional["Orchestrator"] = None


def get_orchestrator() -> "Orchestrator":
    """Get or create the singleton Orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        from ..orchestrator import Orchestrator, PipelineConfig

        project_root = find_project_root()
        config = PipelineConfig()
        _orchestrator = Orchestrator(project_root, config=config)
        logger.info(f"Initialized Orchestrator for project: {project_root}")

    return _orchestrator


# =============================================================================
# MCP SERVER
# =============================================================================

if HAS_MCP_SDK:
    mcp = FastMCP("ralph")

    @mcp.tool()
    def get_status() -> Dict[str, Any]:
        """Get current pipeline status including all specs and their phases."""
        orch = get_orchestrator()
        return orch.get_status_summary()

    @mcp.tool()
    def get_pending_approvals() -> Dict[str, Any]:
        """Get list of specs awaiting user approval."""
        orch = get_orchestrator()
        pending = orch.get_pending_approvals()

        return {
            "count": len(pending),
            "specs": [
                {
                    "id": p.spec_id,
                    "name": p.spec_name,
                    "approval_type": p.approval_type,
                    "summary": p.summary,
                    "files_to_review": p.files_to_review,
                }
                for p in pending
            ],
        }

    @mcp.tool()
    def get_spec(spec_id: str) -> Dict[str, Any]:
        """Get details of a specific spec by ID."""
        orch = get_orchestrator()
        spec = orch.get_spec(spec_id)

        if spec is None:
            return {"error": f"Spec '{spec_id}' not found"}

        return spec.to_dict()

    @mcp.tool()
    async def submit_spec(
        spec_data: Dict[str, Any],
        auto_start: bool = True,
    ) -> Dict[str, Any]:
        """
        Submit a new spec to the pipeline.

        Args:
            spec_data: The spec data including id, name, problem, etc.
            auto_start: If True, automatically start processing (default: True)
        """
        spec_id = spec_data.get("id")

        if not spec_id:
            return {"error": "Spec must have an 'id' field"}

        orch = get_orchestrator()

        # Check if spec already exists
        existing = orch.get_spec(spec_id)
        if existing:
            return {"error": f"Spec '{spec_id}' already exists"}

        try:
            # Submit to orchestrator - this handles all processing
            returned_id = await orch.submit_spec(spec_data)
            spec = orch.get_spec(returned_id)

            return {
                "success": True,
                "spec_id": returned_id,
                "phase": spec.phase.value if spec else "unknown",
                "message": f"Spec '{returned_id}' submitted and processing started",
            }
        except Exception as e:
            logger.exception(f"Error submitting spec {spec_id}")
            return {
                "success": False,
                "error": str(e),
            }

    @mcp.tool()
    async def approve(spec_id: str, feedback: str = "") -> Dict[str, Any]:
        """Approve a pending architecture or implementation."""
        orch = get_orchestrator()
        spec = orch.get_spec(spec_id)

        if spec is None:
            return {"error": f"Spec '{spec_id}' not found"}

        previous_phase = spec.phase.value

        try:
            success = await orch.handle_approval(spec_id, approved=True, feedback=feedback)

            if not success:
                return {
                    "success": False,
                    "error": f"Spec '{spec_id}' is not pending approval (phase: {previous_phase})",
                }

            # Get updated spec
            spec = orch.get_spec(spec_id)
            new_phase = spec.phase.value if spec else "unknown"

            return {
                "success": True,
                "spec_id": spec_id,
                "previous_phase": previous_phase,
                "new_phase": new_phase,
                "message": f"Spec approved and transitioned to {new_phase}",
            }
        except Exception as e:
            logger.exception(f"Error approving spec {spec_id}")
            return {
                "success": False,
                "error": str(e),
            }

    @mcp.tool()
    async def reject(
        spec_id: str,
        feedback: str,
        requested_changes: List[str] = None
    ) -> Dict[str, Any]:
        """Reject a pending architecture or implementation with feedback."""
        orch = get_orchestrator()
        spec = orch.get_spec(spec_id)

        if spec is None:
            return {"error": f"Spec '{spec_id}' not found"}

        previous_phase = spec.phase.value

        # Combine feedback with requested changes
        full_feedback = feedback
        if requested_changes:
            full_feedback += "\n\nRequested changes:\n" + "\n".join(f"- {c}" for c in requested_changes)

        try:
            success = await orch.handle_approval(spec_id, approved=False, feedback=full_feedback)

            if not success:
                return {
                    "success": False,
                    "error": f"Spec '{spec_id}' is not pending approval (phase: {previous_phase})",
                }

            # Get updated spec
            spec = orch.get_spec(spec_id)
            new_phase = spec.phase.value if spec else "unknown"

            return {
                "success": True,
                "spec_id": spec_id,
                "previous_phase": previous_phase,
                "new_phase": new_phase,
                "iteration": spec.iteration if spec else 0,
                "message": f"Spec rejected. Iteration {spec.iteration if spec else '?'} starting.",
            }
        except Exception as e:
            logger.exception(f"Error rejecting spec {spec_id}")
            return {
                "success": False,
                "error": str(e),
            }

    @mcp.tool()
    async def abort(reason: str) -> Dict[str, Any]:
        """Abort all active pipeline runs."""
        orch = get_orchestrator()

        try:
            await orch.abort(reason)

            return {
                "success": True,
                "message": f"Pipeline aborted: {reason}",
            }
        except Exception as e:
            logger.exception("Error aborting pipeline")
            return {
                "success": False,
                "error": str(e),
            }

    # =========================================================================
    # RESTART TOOLS
    # =========================================================================

    @mcp.tool()
    async def restart_spec(
        spec_id: str,
        target_phase: str = "",
        reset_iteration: bool = True,
        clear_errors: bool = False,
        reason: str = "",
    ) -> Dict[str, Any]:
        """
        Restart a FAILED or BLOCKED spec from a specified phase.

        Use this to recover specs that have hit max iterations, encountered
        unrecoverable errors, or are blocked waiting for intervention.

        Args:
            spec_id: The ID of the spec to restart
            target_phase: Phase to restart from. Options:
                - "architecture": Restart architecture design (full redo)
                - "implementation": Restart implementation (keep architecture)
                - "integration": Restart integration (for non-leaf specs)
                If empty, auto-selects based on spec.is_leaf.
            reset_iteration: If True (default), reset iteration counter to 0.
            clear_errors: If True, clear accumulated errors before restart.
                Default False preserves error history for context.
            reason: Explanation of why restarting (logged in transition history).
        """
        orch = get_orchestrator()
        spec = orch.get_spec(spec_id)

        if spec is None:
            return {"error": f"Spec '{spec_id}' not found"}

        # Validate target_phase if provided
        valid_phases = {"", "architecture", "implementation", "integration"}
        if target_phase not in valid_phases:
            return {
                "error": f"Invalid target_phase '{target_phase}'. "
                         f"Valid options: architecture, implementation, integration"
            }

        try:
            result = await orch.restart_spec(
                spec_id=spec_id,
                target_phase=target_phase or None,
                reset_iteration=reset_iteration,
                clear_errors=clear_errors,
                reason=reason,
            )
            return result

        except Exception as e:
            logger.exception(f"Error restarting spec {spec_id}")
            return {
                "success": False,
                "error": str(e),
            }

    @mcp.tool()
    def get_restartable_specs() -> Dict[str, Any]:
        """
        Get list of specs that can be restarted (FAILED or BLOCKED).

        Returns specs in FAILED or BLOCKED phase with context about why
        they are in that state and what restart options are available.
        """
        from ..core.phase import Phase, PHASE_TRANSITIONS

        orch = get_orchestrator()

        restartable = []

        for spec in orch.spec_store.list_all():
            if spec.phase not in (Phase.FAILED, Phase.BLOCKED):
                continue

            # Determine valid restart options
            valid_transitions = PHASE_TRANSITIONS.get(spec.phase, set())
            restart_options = [p.value for p in valid_transitions]

            # Filter based on is_leaf
            if spec.is_leaf:
                restart_options = [p for p in restart_options if p != "integration"]
            elif spec.is_leaf is False:
                restart_options = [p for p in restart_options if p != "implementation"]

            # Get last error summary
            last_error = spec.get_latest_error() if spec.errors else None
            error_summary = last_error.message[:200] if last_error else "No error details"

            restartable.append({
                "id": spec.id,
                "name": spec.name,
                "phase": spec.phase.value,
                "is_leaf": spec.is_leaf,
                "iteration": spec.iteration,
                "max_iterations": spec.max_iterations,
                "error_count": len(spec.errors),
                "error_summary": error_summary,
                "restart_options": restart_options,
            })

        return {
            "count": len(restartable),
            "specs": restartable,
        }

    # =========================================================================
    # AGENT-FACING TOOLS (for Proposer, Implementer, Verifier, etc.)
    # =========================================================================

    @mcp.tool()
    def update_spec(
        spec_id: str,
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Update a spec with new information (used by Proposer/SpecWriter).

        Args:
            spec_id: The spec to update
            updates: Fields to update (is_leaf, classes, children, shared_types, etc.)
        """
        orch = get_orchestrator()
        spec = orch.get_spec(spec_id)

        if spec is None:
            return {"error": f"Spec '{spec_id}' not found"}

        # Apply updates to spec object
        allowed_fields = {
            "is_leaf", "classes", "children", "shared_types",
            "provides", "requires", "dependencies",
            "acceptance_criteria", "edge_cases",
            "problem", "success_criteria", "context",
        }

        applied = []
        for key, value in updates.items():
            if key in allowed_fields and hasattr(spec, key):
                setattr(spec, key, value)
                applied.append(key)

        # Save via spec store
        orch.spec_store.save(spec)

        return {
            "success": True,
            "spec_id": spec_id,
            "updated_fields": applied,
        }

    @mcp.tool()
    async def send_message(
        spec_id: str,
        message_type: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Send a message from an agent (phase_complete, approval, error, etc.).

        Args:
            spec_id: The spec this message relates to
            message_type: Type of message (phase_complete, approval_response, error_report)
            payload: Message payload with details
        """
        from ..core.message import Message, MessageType

        orch = get_orchestrator()
        spec = orch.get_spec(spec_id)

        if spec is None:
            return {"error": f"Spec '{spec_id}' not found"}

        # Map string message types to enum
        type_map = {
            "phase_complete": MessageType.PHASE_COMPLETE,
            "approval_response": MessageType.APPROVAL_RESPONSE,
            "error_report": MessageType.ERROR_REPORT,
            "status_update": MessageType.STATUS_UPDATE,
            "context_update": MessageType.CONTEXT_UPDATE,
        }

        msg_type = type_map.get(message_type)
        if msg_type is None:
            return {"error": f"Unknown message type: {message_type}"}

        message = Message(
            from_id=spec_id,
            to_id="orchestrator",
            spec_id=spec_id,
            type=msg_type,
            payload=payload,
        )

        await orch.message_bus.send(message)

        return {"success": True}

    @mcp.tool()
    def report_error(
        spec_id: str,
        category: str,
        message: str,
        details: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Report an error during verification (used by Verifier).

        Args:
            spec_id: The spec with the error
            category: Error category (compilation, test, runtime, etc.)
            message: Human-readable error message
            details: Additional details (file, line, stack trace, etc.)
        """
        from ..core.errors import ErrorReport, ErrorCategory, ErrorSeverity

        orch = get_orchestrator()
        spec = orch.get_spec(spec_id)

        if spec is None:
            return {"error": f"Spec '{spec_id}' not found"}

        # Map string category to enum
        try:
            error_cat = ErrorCategory(category)
        except ValueError:
            error_cat = ErrorCategory.AGENT

        error = ErrorReport(
            iteration=spec.iteration,
            category=error_cat,
            severity=ErrorSeverity.ERROR,
            message=message,
            details=details or {},
            recoverable=True,
        )

        spec.add_error(error)
        orch.spec_store.save(spec)

        return {
            "success": True,
            "error_count": len(spec.errors),
        }

    @mcp.tool()
    def get_sibling_status(spec_id: str) -> Dict[str, Any]:
        """
        Get status of sibling specs (for coordination).

        Args:
            spec_id: The spec asking about its siblings
        """
        from ..core.phase import Phase

        orch = get_orchestrator()
        spec = orch.get_spec(spec_id)

        if spec is None:
            return {"error": f"Spec '{spec_id}' not found"}

        if not spec.parent_id:
            return {"siblings": [], "message": "No parent - this is a root spec"}

        # Get siblings via spec store
        siblings_specs = orch.spec_store.list_children(spec.parent_id)

        siblings = [
            {
                "id": s.id,
                "name": s.name,
                "phase": s.phase.value,
                "is_complete": s.phase == Phase.COMPLETE,
            }
            for s in siblings_specs
            if s.id != spec_id
        ]

        return {
            "spec_id": spec_id,
            "parent_id": spec.parent_id,
            "siblings": siblings,
            "all_complete": all(s["is_complete"] for s in siblings) if siblings else True,
        }


def main():
    """Run the MCP server."""
    if not HAS_MCP_SDK:
        print(
            "Error: MCP SDK not installed. Run: pip install mcp",
            file=sys.stderr
        )
        sys.exit(1)

    logger.info("Ralph MCP Server starting...")
    mcp.run()


if __name__ == "__main__":
    main()
