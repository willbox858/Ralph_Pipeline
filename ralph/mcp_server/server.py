"""
MCP Server for the Ralph pipeline.

Uses the official MCP Python SDK (FastMCP) to provide tools
for the Interface Agent to interact with the orchestrator.

This server:
1. Manages spec state (submit, approve, reject)
2. Actually RUNS the orchestrator to process specs
3. Invokes Claude agents via the Agent SDK
"""

from typing import Dict, Any, List, Optional
from pathlib import Path
import json
import sys
import asyncio
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


def get_state_dir() -> Path:
    """Get the Ralph state directory."""
    project_root = find_project_root()
    state_dir = project_root / ".ralph" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def load_specs() -> List[Dict[str, Any]]:
    """Load all specs from state directory."""
    state_dir = get_state_dir()
    specs_dir = state_dir / "specs"
    
    if not specs_dir.exists():
        return []
    
    specs = []
    for spec_file in specs_dir.glob("*.json"):
        try:
            with open(spec_file) as f:
                specs.append(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass
    
    return specs


def load_spec(spec_id: str) -> Dict[str, Any] | None:
    """Load a specific spec by ID."""
    state_dir = get_state_dir()
    spec_file = state_dir / "specs" / f"{spec_id}.json"
    
    if spec_file.exists():
        try:
            with open(spec_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    
    return None


def save_spec(spec_id: str, spec_data: Dict[str, Any]) -> None:
    """Save a spec to the state directory."""
    state_dir = get_state_dir()
    specs_dir = state_dir / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    
    spec_file = specs_dir / f"{spec_id}.json"
    with open(spec_file, "w") as f:
        json.dump(spec_data, f, indent=2)


# =============================================================================
# ORCHESTRATOR INTEGRATION
# =============================================================================

# Track running processing tasks
_processing_tasks: Dict[str, asyncio.Task] = {}


async def process_spec_async(spec_id: str, spec_data: Dict[str, Any]) -> None:
    """
    Process a spec through the pipeline until it needs approval.
    
    This runs the architecture team (Proposer → Critic loop) and
    transitions the spec to AWAITING_ARCH_APPROVAL when ready.
    """
    logger.info(f"Starting processing for spec: {spec_id}")
    
    project_root = find_project_root()
    max_iterations = spec_data.get("max_iterations", 5)
    
    # Try to use the full orchestrator if available
    try:
        from ..orchestrator.engine import Orchestrator, PipelineConfig
        from ..core.spec import Spec
        from ..core.phase import Phase
        from ..agents.invoker import AgentInvoker
        from ..agents.roles import AgentRole
        
        config = PipelineConfig(
            max_arch_iterations=max_iterations,
            max_iterations=15,
        )
        
        orchestrator = Orchestrator(project_root, config=config)
        
        # Convert dict to Spec object
        spec = Spec.from_dict(spec_data)
        spec.phase = Phase.ARCHITECTURE
        
        # Run architecture loop
        for iteration in range(1, max_iterations + 1):
            logger.info(f"[{spec_id}] Architecture iteration {iteration}/{max_iterations}")
            
            # Update state
            spec.iteration = iteration
            spec_data["iteration"] = iteration
            spec_data["phase"] = "ARCHITECTURE"
            save_spec(spec_id, spec_data)
            
            tech_stack = spec.get_effective_tech_stack()
            
            # Invoke Proposer
            logger.info(f"[{spec_id}] Invoking Proposer...")
            proposer_result = await orchestrator.agent_invoker.invoke(
                role=AgentRole.PROPOSER,
                spec=spec,
                tech_stack=tech_stack,
                iteration=iteration,
            )
            
            if not proposer_result.success:
                logger.error(f"[{spec_id}] Proposer failed: {proposer_result.error}")
                spec_data["phase"] = "BLOCKED"
                spec_data["error"] = proposer_result.error
                save_spec(spec_id, spec_data)
                return
            
            # Track artifacts
            spec_data["artifacts"] = proposer_result.artifacts
            save_spec(spec_id, spec_data)
            
            # Invoke Critic
            logger.info(f"[{spec_id}] Invoking Critic...")
            critic_result = await orchestrator.agent_invoker.invoke(
                role=AgentRole.CRITIC,
                spec=spec,
                tech_stack=tech_stack,
                iteration=iteration,
            )
            
            if not critic_result.success:
                logger.error(f"[{spec_id}] Critic failed: {critic_result.error}")
                continue  # Try again
            
            # Check if critic approved
            output_lower = critic_result.output.lower()
            if "approved" in output_lower or "lgtm" in output_lower:
                if "reject" not in output_lower:
                    logger.info(f"[{spec_id}] Architecture approved by Critic!")
                    spec_data["phase"] = "AWAITING_ARCH_APPROVAL"
                    spec_data["critic_feedback"] = critic_result.output
                    save_spec(spec_id, spec_data)
                    return
            
            # Critic rejected, continue loop
            logger.info(f"[{spec_id}] Critic requested changes, continuing...")
            spec_data["critic_feedback"] = critic_result.output
            save_spec(spec_id, spec_data)
        
        # Exceeded max iterations
        logger.warning(f"[{spec_id}] Exceeded max architecture iterations")
        spec_data["phase"] = "BLOCKED"
        spec_data["error"] = f"Exceeded max architecture iterations ({max_iterations})"
        save_spec(spec_id, spec_data)
        
    except ImportError as e:
        logger.error(f"Missing dependency: {e}")
        # Fallback: just mark as awaiting approval for manual processing
        spec_data["phase"] = "AWAITING_ARCH_APPROVAL"
        spec_data["error"] = f"Auto-processing unavailable: {e}"
        save_spec(spec_id, spec_data)
    
    except Exception as e:
        logger.exception(f"Error processing spec {spec_id}")
        spec_data["phase"] = "BLOCKED"
        spec_data["error"] = str(e)
        save_spec(spec_id, spec_data)


async def process_implementation_async(spec_id: str, spec_data: Dict[str, Any]) -> None:
    """
    Process implementation phase for a spec.
    
    Runs Implementer → Verifier loop until tests pass.
    """
    logger.info(f"Starting implementation for spec: {spec_id}")
    
    project_root = find_project_root()
    max_iterations = spec_data.get("max_iterations", 15)
    
    try:
        from ..orchestrator.engine import Orchestrator, PipelineConfig
        from ..core.spec import Spec
        from ..core.phase import Phase
        from ..agents.invoker import AgentInvoker
        from ..agents.roles import AgentRole
        
        config = PipelineConfig(max_iterations=max_iterations)
        orchestrator = Orchestrator(project_root, config=config)
        
        spec = Spec.from_dict(spec_data)
        spec.phase = Phase.IMPLEMENTATION
        
        start_iteration = spec_data.get("iteration", 1)
        
        for iteration in range(start_iteration, max_iterations + 1):
            logger.info(f"[{spec_id}] Implementation iteration {iteration}/{max_iterations}")
            
            spec.iteration = iteration
            spec_data["iteration"] = iteration
            spec_data["phase"] = "IMPLEMENTATION"
            save_spec(spec_id, spec_data)
            
            tech_stack = spec.get_effective_tech_stack()
            
            # Invoke Implementer
            logger.info(f"[{spec_id}] Invoking Implementer...")
            impl_result = await orchestrator.agent_invoker.invoke(
                role=AgentRole.IMPLEMENTER,
                spec=spec,
                tech_stack=tech_stack,
                iteration=iteration,
            )
            
            if not impl_result.success:
                logger.error(f"[{spec_id}] Implementer failed: {impl_result.error}")
                continue
            
            spec_data["artifacts"] = impl_result.artifacts
            save_spec(spec_id, spec_data)
            
            # Invoke Verifier
            logger.info(f"[{spec_id}] Invoking Verifier...")
            verify_result = await orchestrator.agent_invoker.invoke(
                role=AgentRole.VERIFIER,
                spec=spec,
                tech_stack=tech_stack,
                iteration=iteration,
            )
            
            if not verify_result.success:
                logger.error(f"[{spec_id}] Verifier failed: {verify_result.error}")
                continue
            
            # Check if tests passed
            output_lower = verify_result.output.lower()
            if "all tests pass" in output_lower or "verification passed" in output_lower:
                if "fail" not in output_lower and "error" not in output_lower:
                    logger.info(f"[{spec_id}] Implementation verified!")
                    spec_data["phase"] = "AWAITING_IMPL_APPROVAL"
                    spec_data["verifier_output"] = verify_result.output
                    save_spec(spec_id, spec_data)
                    return
            
            logger.info(f"[{spec_id}] Verification failed, continuing...")
            spec_data["verifier_output"] = verify_result.output
            save_spec(spec_id, spec_data)
        
        # Exceeded iterations
        spec_data["phase"] = "FAILED"
        spec_data["error"] = f"Exceeded max implementation iterations ({max_iterations})"
        save_spec(spec_id, spec_data)
        
    except ImportError as e:
        logger.error(f"Missing dependency: {e}")
        spec_data["phase"] = "AWAITING_IMPL_APPROVAL"
        spec_data["error"] = f"Auto-processing unavailable: {e}"
        save_spec(spec_id, spec_data)
    
    except Exception as e:
        logger.exception(f"Error during implementation {spec_id}")
        spec_data["phase"] = "BLOCKED"
        spec_data["error"] = str(e)
        save_spec(spec_id, spec_data)


# =============================================================================
# MCP SERVER
# =============================================================================

if HAS_MCP_SDK:
    mcp = FastMCP("ralph")
    
    @mcp.tool()
    def ralph_get_status() -> Dict[str, Any]:
        """Get current pipeline status including all specs and their phases."""
        specs = load_specs()
        
        phase_counts: Dict[str, int] = {}
        for spec in specs:
            phase = spec.get("phase", "UNKNOWN")
            phase_counts[phase] = phase_counts.get(phase, 0) + 1
        
        pending = [
            s for s in specs 
            if s.get("phase", "").startswith("AWAITING_")
        ]
        
        # Check which specs are actively processing
        processing = list(_processing_tasks.keys())
        
        return {
            "total_specs": len(specs),
            "phase_counts": phase_counts,
            "pending_approvals": len(pending),
            "actively_processing": processing,
            "specs": [
                {
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "phase": s.get("phase"),
                    "iteration": s.get("iteration", 1),
                    "processing": s.get("id") in _processing_tasks,
                }
                for s in specs
            ],
        }
    
    @mcp.tool()
    def ralph_get_pending_approvals() -> Dict[str, Any]:
        """Get list of specs awaiting user approval."""
        specs = load_specs()
        
        pending = [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "phase": s.get("phase"),
                "iteration": s.get("iteration", 1),
                "description": s.get("description", ""),
            }
            for s in specs
            if s.get("phase", "").startswith("AWAITING_")
        ]
        
        return {
            "count": len(pending),
            "specs": pending,
        }
    
    @mcp.tool()
    def ralph_get_spec(spec_id: str) -> Dict[str, Any]:
        """Get details of a specific spec by ID."""
        spec = load_spec(spec_id)
        
        if spec is None:
            return {"error": f"Spec '{spec_id}' not found"}
        
        return spec
    
    @mcp.tool()
    async def ralph_submit_spec(
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
        
        existing = load_spec(spec_id)
        if existing:
            return {"error": f"Spec '{spec_id}' already exists"}
        
        # Initialize spec state
        spec_data["phase"] = "ARCHITECTURE"
        spec_data["iteration"] = 1
        
        save_spec(spec_id, spec_data)
        
        result = {
            "success": True,
            "spec_id": spec_id,
            "phase": "ARCHITECTURE",
            "message": f"Spec '{spec_id}' submitted",
        }
        
        # Auto-start processing
        if auto_start:
            start_result = await ralph_start_processing(spec_id)
            result["processing_started"] = start_result.get("success", False)
            if not start_result.get("success"):
                result["processing_error"] = start_result.get("error")
        
        return result
    
    @mcp.tool()
    async def ralph_start_processing(spec_id: str) -> Dict[str, Any]:
        """
        Start processing a spec through the pipeline.
        
        This kicks off the agent invocation loop (Proposer → Critic for
        architecture, Implementer → Verifier for implementation).
        
        Processing runs in the background until the spec reaches an
        approval state or fails.
        """
        spec = load_spec(spec_id)
        
        if spec is None:
            return {"error": f"Spec '{spec_id}' not found"}
        
        # Check if already processing
        if spec_id in _processing_tasks:
            task = _processing_tasks[spec_id]
            if not task.done():
                return {
                    "success": False,
                    "error": f"Spec '{spec_id}' is already being processed",
                    "phase": spec.get("phase"),
                }
        
        phase = spec.get("phase", "")
        
        # Determine what processing to do
        if phase == "ARCHITECTURE":
            task = asyncio.create_task(process_spec_async(spec_id, spec))
            _processing_tasks[spec_id] = task
            return {
                "success": True,
                "spec_id": spec_id,
                "phase": phase,
                "message": "Architecture processing started",
            }
        
        elif phase == "IMPLEMENTATION":
            task = asyncio.create_task(process_implementation_async(spec_id, spec))
            _processing_tasks[spec_id] = task
            return {
                "success": True,
                "spec_id": spec_id,
                "phase": phase,
                "message": "Implementation processing started",
            }
        
        elif phase.startswith("AWAITING_"):
            return {
                "success": False,
                "error": f"Spec '{spec_id}' is awaiting approval ({phase})",
                "phase": phase,
            }
        
        elif phase in ("COMPLETE", "FAILED", "BLOCKED"):
            return {
                "success": False,
                "error": f"Spec '{spec_id}' is in terminal state ({phase})",
                "phase": phase,
            }
        
        else:
            return {
                "success": False,
                "error": f"Unknown phase: {phase}",
                "phase": phase,
            }
    
    @mcp.tool()
    async def ralph_approve(spec_id: str, feedback: str = "") -> Dict[str, Any]:
        """Approve a pending architecture or implementation."""
        spec = load_spec(spec_id)
        
        if spec is None:
            return {"error": f"Spec '{spec_id}' not found"}
        
        phase = spec.get("phase", "")
        
        # Define phase transitions on approval
        transitions = {
            "AWAITING_ARCH_APPROVAL": "IMPLEMENTATION",
            "AWAITING_IMPL_APPROVAL": "INTEGRATION",
            "AWAITING_INTEG_APPROVAL": "COMPLETE",
        }
        
        if phase not in transitions:
            return {
                "error": f"Spec '{spec_id}' is not pending approval (phase: {phase})"
            }
        
        new_phase = transitions[phase]
        spec["phase"] = new_phase
        
        if "approvals" not in spec:
            spec["approvals"] = []
        spec["approvals"].append({
            "from_phase": phase,
            "to_phase": new_phase,
            "feedback": feedback,
        })
        
        save_spec(spec_id, spec)
        
        result = {
            "success": True,
            "spec_id": spec_id,
            "previous_phase": phase,
            "new_phase": new_phase,
            "message": f"Spec approved and transitioned to {new_phase}",
        }
        
        # Auto-start next phase processing
        if new_phase in ("IMPLEMENTATION", "INTEGRATION"):
            start_result = await ralph_start_processing(spec_id)
            result["processing_started"] = start_result.get("success", False)
        
        return result
    
    @mcp.tool()
    def ralph_reject(
        spec_id: str, 
        feedback: str, 
        requested_changes: List[str] = None
    ) -> Dict[str, Any]:
        """Reject a pending architecture or implementation with feedback."""
        spec = load_spec(spec_id)
        
        if spec is None:
            return {"error": f"Spec '{spec_id}' not found"}
        
        phase = spec.get("phase", "")
        
        transitions = {
            "AWAITING_ARCH_APPROVAL": "ARCHITECTURE",
            "AWAITING_IMPL_APPROVAL": "IMPLEMENTATION",
            "AWAITING_INTEG_APPROVAL": "INTEGRATION",
        }
        
        if phase not in transitions:
            return {
                "error": f"Spec '{spec_id}' is not pending approval (phase: {phase})"
            }
        
        spec["iteration"] = spec.get("iteration", 1) + 1
        
        max_iter = spec.get("max_iterations", 15)
        if spec["iteration"] > max_iter:
            spec["phase"] = "FAILED"
            spec["failure_reason"] = f"Exceeded max iterations ({max_iter})"
            save_spec(spec_id, spec)
            return {
                "success": False,
                "spec_id": spec_id,
                "phase": "FAILED",
                "message": f"Spec failed: exceeded max iterations",
            }
        
        new_phase = transitions[phase]
        spec["phase"] = new_phase
        
        if "rejections" not in spec:
            spec["rejections"] = []
        spec["rejections"].append({
            "from_phase": phase,
            "to_phase": new_phase,
            "feedback": feedback,
            "requested_changes": requested_changes or [],
            "iteration": spec["iteration"],
        })
        
        save_spec(spec_id, spec)
        
        return {
            "success": True,
            "spec_id": spec_id,
            "previous_phase": phase,
            "new_phase": new_phase,
            "iteration": spec["iteration"],
            "message": f"Spec rejected. Iteration {spec['iteration']} starting.",
        }
    
    @mcp.tool()
    def ralph_abort(reason: str) -> Dict[str, Any]:
        """Abort all active pipeline runs."""
        specs = load_specs()
        
        # Cancel running tasks
        for spec_id, task in list(_processing_tasks.items()):
            if not task.done():
                task.cancel()
            del _processing_tasks[spec_id]
        
        aborted = []
        for spec in specs:
            phase = spec.get("phase", "")
            if phase not in ("COMPLETE", "FAILED", "BLOCKED"):
                spec["phase"] = "BLOCKED"
                spec["block_reason"] = reason
                save_spec(spec["id"], spec)
                aborted.append(spec["id"])
        
        return {
            "success": True,
            "aborted_count": len(aborted),
            "aborted_specs": aborted,
            "reason": reason,
        }
    
    @mcp.tool()
    def ralph_check_processing(spec_id: str) -> Dict[str, Any]:
        """Check if a spec is actively being processed."""
        if spec_id not in _processing_tasks:
            return {
                "processing": False,
                "spec_id": spec_id,
            }
        
        task = _processing_tasks[spec_id]
        
        if task.done():
            # Clean up finished task
            del _processing_tasks[spec_id]
            
            # Check for exceptions
            try:
                task.result()
                error = None
            except Exception as e:
                error = str(e)
            
            return {
                "processing": False,
                "completed": True,
                "spec_id": spec_id,
                "error": error,
            }
        
        return {
            "processing": True,
            "spec_id": spec_id,
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
