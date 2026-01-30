"""
MCP Server for the Ralph pipeline.

Uses the official MCP Python SDK (FastMCP) to provide tools
for the Interface Agent to interact with the orchestrator.
"""

from typing import Dict, Any, List
from pathlib import Path
import json
import sys

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
        # Stop at filesystem root
        if path == path.parent:
            break
    
    # Default to current directory
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


# Create FastMCP server if SDK is available
if HAS_MCP_SDK:
    mcp = FastMCP("ralph")
    
    @mcp.tool()
    def ralph_get_status() -> Dict[str, Any]:
        """Get current pipeline status including all specs and their phases."""
        specs = load_specs()
        
        # Count specs by phase
        phase_counts: Dict[str, int] = {}
        for spec in specs:
            phase = spec.get("phase", "UNKNOWN")
            phase_counts[phase] = phase_counts.get(phase, 0) + 1
        
        # Find pending approvals
        pending = [
            s for s in specs 
            if s.get("phase", "").startswith("AWAITING_")
        ]
        
        return {
            "total_specs": len(specs),
            "phase_counts": phase_counts,
            "pending_approvals": len(pending),
            "specs": [
                {
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "phase": s.get("phase"),
                    "iteration": s.get("iteration", 1),
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
    def ralph_submit_spec(spec_data: Dict[str, Any]) -> Dict[str, Any]:
        """Submit a new spec to the pipeline."""
        spec_id = spec_data.get("id")
        
        if not spec_id:
            return {"error": "Spec must have an 'id' field"}
        
        # Check if spec already exists
        existing = load_spec(spec_id)
        if existing:
            return {"error": f"Spec '{spec_id}' already exists"}
        
        # Initialize spec state
        spec_data["phase"] = "ARCHITECTURE"
        spec_data["iteration"] = 1
        
        # Save spec
        save_spec(spec_id, spec_data)
        
        return {
            "success": True,
            "spec_id": spec_id,
            "phase": "ARCHITECTURE",
            "message": f"Spec '{spec_id}' submitted and queued for architecture phase",
        }
    
    @mcp.tool()
    def ralph_approve(spec_id: str, feedback: str = "") -> Dict[str, Any]:
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
        
        # Transition to next phase
        new_phase = transitions[phase]
        spec["phase"] = new_phase
        
        # Record approval
        if "approvals" not in spec:
            spec["approvals"] = []
        spec["approvals"].append({
            "from_phase": phase,
            "to_phase": new_phase,
            "feedback": feedback,
        })
        
        save_spec(spec_id, spec)
        
        return {
            "success": True,
            "spec_id": spec_id,
            "previous_phase": phase,
            "new_phase": new_phase,
            "message": f"Spec approved and transitioned to {new_phase}",
        }
    
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
        
        # Define phase transitions on rejection (go back to work phase)
        transitions = {
            "AWAITING_ARCH_APPROVAL": "ARCHITECTURE",
            "AWAITING_IMPL_APPROVAL": "IMPLEMENTATION",
            "AWAITING_INTEG_APPROVAL": "INTEGRATION",
        }
        
        if phase not in transitions:
            return {
                "error": f"Spec '{spec_id}' is not pending approval (phase: {phase})"
            }
        
        # Increment iteration
        spec["iteration"] = spec.get("iteration", 1) + 1
        
        # Check max iterations
        max_iter = 15  # Default
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
        
        # Transition back to work phase
        new_phase = transitions[phase]
        spec["phase"] = new_phase
        
        # Record rejection
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


def main():
    """Run the MCP server."""
    if not HAS_MCP_SDK:
        print(
            "Error: MCP SDK not installed. Run: pip install mcp",
            file=sys.stderr
        )
        sys.exit(1)
    
    # Run the FastMCP server (stdio transport by default)
    mcp.run()


if __name__ == "__main__":
    main()
