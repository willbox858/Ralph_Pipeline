"""
MCP Server for the Ralph pipeline.

Provides tools for the Interface Agent to interact with the orchestrator:
- Get pipeline status
- Submit specs
- Handle approvals
- Query spec details
"""

from typing import Dict, Any, Optional, List
from pathlib import Path
import json
import asyncio


class RalphMCPServer:
    """
    MCP Server for Interface Agent communication.
    
    This server is started by the orchestrator and provides tools
    for the Interface Agent to query status and submit commands.
    """
    
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self._tools = {}
        self._register_tools()
    
    def _register_tools(self) -> None:
        """Register all MCP tools."""
        self._tools = {
            "ralph_get_status": self.get_status,
            "ralph_get_pending_approvals": self.get_pending_approvals,
            "ralph_get_spec": self.get_spec,
            "ralph_submit_spec": self.submit_spec,
            "ralph_approve": self.approve,
            "ralph_reject": self.reject,
            "ralph_abort": self.abort,
        }
    
    async def get_status(self) -> Dict[str, Any]:
        """
        Get current pipeline status.
        
        Returns summary of all specs, their phases, and any pending approvals.
        """
        from ..orchestrator.engine import get_orchestrator
        
        try:
            orchestrator = get_orchestrator()
            return orchestrator.get_status_summary()
        except RuntimeError:
            return {"error": "Orchestrator not running"}
    
    async def get_pending_approvals(self) -> Dict[str, Any]:
        """
        Get list of specs awaiting user approval.
        
        Returns details needed for user to review and approve/reject.
        """
        from ..orchestrator.engine import get_orchestrator
        
        try:
            orchestrator = get_orchestrator()
            pending = orchestrator.get_pending_approvals()
            
            return {
                "count": len(pending),
                "approvals": [
                    {
                        "spec_id": p.spec_id,
                        "spec_name": p.spec_name,
                        "type": p.approval_type,
                        "summary": p.summary,
                        "files_to_review": p.files_to_review,
                    }
                    for p in pending
                ]
            }
        except RuntimeError:
            return {"error": "Orchestrator not running", "count": 0, "approvals": []}
    
    async def get_spec(self, spec_id: str) -> Dict[str, Any]:
        """
        Get details of a specific spec.
        
        Args:
            spec_id: The spec ID to retrieve
            
        Returns full spec data including structure, criteria, etc.
        """
        from ..orchestrator.engine import get_orchestrator
        
        try:
            orchestrator = get_orchestrator()
            spec = orchestrator.get_spec(spec_id)
            
            if not spec:
                return {"error": f"Spec not found: {spec_id}"}
            
            return {"spec": spec.to_dict()}
        except RuntimeError:
            return {"error": "Orchestrator not running"}
    
    async def submit_spec(self, spec_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submit a new spec to the pipeline.
        
        Args:
            spec_data: Spec data matching the spec schema
            
        Returns the created spec ID.
        """
        from ..orchestrator.engine import get_orchestrator
        
        try:
            orchestrator = get_orchestrator()
            spec_id = await orchestrator.submit_spec(spec_data)
            return {"success": True, "spec_id": spec_id}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def approve(
        self,
        spec_id: str,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Approve a pending architecture or implementation.
        
        Args:
            spec_id: The spec to approve
            feedback: Optional feedback to include
        """
        from ..orchestrator.engine import get_orchestrator
        
        try:
            orchestrator = get_orchestrator()
            success = await orchestrator.handle_approval(
                spec_id, approved=True, feedback=feedback or ""
            )
            return {
                "success": success,
                "message": f"Approved spec {spec_id}" if success else "Approval failed",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def reject(
        self,
        spec_id: str,
        feedback: str,
        requested_changes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Reject a pending architecture or implementation.
        
        Args:
            spec_id: The spec to reject
            feedback: Required feedback explaining why
            requested_changes: Optional list of specific changes needed
        """
        from ..orchestrator.engine import get_orchestrator
        
        try:
            orchestrator = get_orchestrator()
            full_feedback = feedback
            if requested_changes:
                full_feedback += f"\nRequested changes:\n" + "\n".join(f"- {c}" for c in requested_changes)
            
            success = await orchestrator.handle_approval(
                spec_id, approved=False, feedback=full_feedback
            )
            return {
                "success": success,
                "message": f"Rejected spec {spec_id}, restarting phase" if success else "Rejection failed",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def abort(self, reason: str) -> Dict[str, Any]:
        """
        Abort the current pipeline run.
        
        Args:
            reason: Why the pipeline is being aborted
        """
        from ..orchestrator.engine import get_orchestrator
        
        try:
            orchestrator = get_orchestrator()
            await orchestrator.abort(reason)
            return {"success": True, "message": "Pipeline aborted"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get MCP tool definitions for registration."""
        return [
            {
                "name": "ralph_get_status",
                "description": "Get current pipeline status including all specs and their phases",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "ralph_get_pending_approvals",
                "description": "Get list of specs awaiting user approval",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "ralph_get_spec",
                "description": "Get details of a specific spec by ID",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "spec_id": {"type": "string", "description": "The spec ID"}
                    },
                    "required": ["spec_id"],
                },
            },
            {
                "name": "ralph_submit_spec",
                "description": "Submit a new spec to the pipeline",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "spec_data": {"type": "object", "description": "The spec data"}
                    },
                    "required": ["spec_data"],
                },
            },
            {
                "name": "ralph_approve",
                "description": "Approve a pending architecture or implementation",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "spec_id": {"type": "string"},
                        "feedback": {"type": "string"},
                    },
                    "required": ["spec_id"],
                },
            },
            {
                "name": "ralph_reject",
                "description": "Reject a pending architecture or implementation",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "spec_id": {"type": "string"},
                        "feedback": {"type": "string"},
                        "requested_changes": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["spec_id", "feedback"],
                },
            },
            {
                "name": "ralph_abort",
                "description": "Abort the current pipeline run",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "reason": {"type": "string"},
                    },
                    "required": ["reason"],
                },
            },
        ]
    
    async def handle_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Handle an MCP tool call."""
        handler = self._tools.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}
        
        return await handler(**arguments)


def main():
    """Entry point for running as MCP server."""
    import sys
    
    # Simple stdin/stdout MCP protocol
    # Real implementation would use proper MCP library
    state_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".ralph/state")
    server = RalphMCPServer(state_dir)
    
    print(json.dumps({
        "type": "server_info",
        "name": "ralph",
        "version": "2.0.0",
        "tools": server.get_tool_definitions(),
    }))
    
    # Event loop for handling requests
    loop = asyncio.new_event_loop()
    
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request.get("type") == "tool_call":
                result = loop.run_until_complete(
                    server.handle_tool_call(
                        request["tool"],
                        request.get("arguments", {}),
                    )
                )
                print(json.dumps({"type": "tool_result", "result": result}))
        except json.JSONDecodeError:
            pass
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()
