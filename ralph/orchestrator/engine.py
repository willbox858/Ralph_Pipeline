"""
Orchestrator Engine for the Ralph pipeline.

The central coordinator that:
- Manages the pipeline lifecycle
- Deploys agents at the right times
- Handles messages and approvals
- Tracks overall progress
"""

from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timezone
import asyncio
import json

from ..core.spec import Spec
from ..core.phase import Phase, is_approval_phase
from ..core.message import (
    Message,
    MessageType,
    MessagePriority,
    ApprovalRequestPayload,
    create_approval_request,
)
from ..core.errors import (
    ErrorReport,
    ErrorCategory,
    ErrorSeverity,
)
from ..messaging.bus import MessageBus, get_message_bus
from ..tools.registry import get_tool_registry
from ..agents.invoker import AgentInvoker, AgentResult
from ..agents.roles import AgentRole
from .state_machine import StateMachine
from .spec_store import SpecStore


@dataclass
class PipelineConfig:
    """Configuration for the pipeline."""
    max_iterations: int = 15
    max_arch_iterations: int = 5
    max_concurrent_agents: int = 3
    dry_run: bool = False
    auto_approve: bool = False  # Dangerous! Only for testing


@dataclass
class PipelineStatus:
    """Current status of the pipeline."""
    running: bool = False
    specs_total: int = 0
    specs_complete: int = 0
    specs_failed: int = 0
    specs_blocked: int = 0
    current_phase: Optional[str] = None
    pending_approvals: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "specs_total": self.specs_total,
            "specs_complete": self.specs_complete,
            "specs_failed": self.specs_failed,
            "specs_blocked": self.specs_blocked,
            "current_phase": self.current_phase,
            "pending_approvals": self.pending_approvals,
        }


class Orchestrator:
    """
    Main orchestrator for the Ralph pipeline.
    
    Coordinates the entire pipeline:
    - Receives specs from Interface Agent
    - Deploys Architecture team for design
    - Handles user approvals
    - Deploys Implementation team for coding
    - Manages parent/child relationships
    - Routes messages between components
    """
    
    def __init__(
        self,
        project_root: Path,
        specs_dir: Optional[Path] = None,
        config: Optional[PipelineConfig] = None,
    ):
        self.project_root = project_root
        self.specs_dir = specs_dir or project_root / "Specs" / "Active"
        self.config = config or PipelineConfig()
        
        # State directory
        self.state_dir = project_root / ".ralph" / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # Components
        self.spec_store = SpecStore(self.specs_dir)
        self.state_machine = StateMachine()
        self.message_bus = get_message_bus(self.state_dir)
        self.tool_registry = get_tool_registry()
        self.agent_invoker = AgentInvoker(
            project_root=project_root,
            dry_run=self.config.dry_run,
        )
        
        # Runtime state
        self._status = PipelineStatus()
        self._running_agents: Dict[str, asyncio.Task] = {}
        self._shutdown_event = asyncio.Event()
        
        # Setup handlers
        self._setup_message_handlers()
        self._setup_side_effect_handlers()
    
    def _setup_message_handlers(self) -> None:
        """Set up handlers for incoming messages."""
        self.message_bus.register_handler(
            "orchestrator",
            self._handle_orchestrator_message,
        )
    
    def _setup_side_effect_handlers(self) -> None:
        """Set up handlers for state machine side effects."""
        handlers = {
            "deploy_architecture_team": self._deploy_architecture_team,
            "deploy_implementation_team": self._deploy_implementation_team,
            "deploy_integration_team": self._deploy_integration_team,
            "create_child_specs": self._create_child_specs,
            "monitor_children": self._monitor_children,
            "send_approval_request:architecture": lambda s, e: self._send_approval_request(s, "architecture"),
            "send_approval_request:implementation": lambda s, e: self._send_approval_request(s, "implementation"),
            "send_approval_request:integration": lambda s, e: self._send_approval_request(s, "integration"),
            "send_approval_request:blocked": lambda s, e: self._send_approval_request(s, "blocked"),
            "notify_parent_complete": self._notify_parent_complete,
            "notify_failure": self._notify_failure,
            "log_completion": self._log_completion,
            "log_failure": self._log_failure,
        }
        
        for name, handler in handlers.items():
            self.state_machine.register_side_effect_handler(name, handler)
    
    # =========================================================================
    # PUBLIC API
    # =========================================================================
    
    async def submit_spec(self, spec_data: Dict[str, Any]) -> str:
        """Submit a new spec to the pipeline."""
        spec = Spec.from_dict(spec_data)
        spec.phase = Phase.READY
        
        if spec.max_iterations == 15:
            spec.max_iterations = self.config.max_iterations
        
        self.spec_store.save(spec)
        await self._process_spec(spec)
        
        return spec.id
    
    async def handle_approval(
        self,
        spec_id: str,
        approved: bool,
        feedback: str = "",
    ) -> bool:
        """Handle user approval/rejection."""
        spec = self.spec_store.get(spec_id)
        if not spec or not is_approval_phase(spec.phase):
            return False
        
        result = self.state_machine.handle_approval(
            spec, approved, triggered_by="user", reason=feedback,
        )
        
        if result.success:
            self.spec_store.save(spec)
            await self.state_machine.execute_side_effects(spec, result.side_effects)
            
            if spec_id in self._status.pending_approvals:
                self._status.pending_approvals.remove(spec_id)
        
        return result.success
    
    def get_status(self) -> PipelineStatus:
        """Get current pipeline status."""
        specs = self.spec_store.list_all()
        self._status.specs_total = len(specs)
        self._status.specs_complete = len([s for s in specs if s.phase == Phase.COMPLETE])
        self._status.specs_failed = len([s for s in specs if s.phase == Phase.FAILED])
        self._status.specs_blocked = len([s for s in specs if s.phase == Phase.BLOCKED])
        return self._status
    
    def get_status_summary(self) -> Dict[str, Any]:
        """Get detailed status summary."""
        status = self.get_status()
        specs = self.spec_store.list_all()
        
        return {
            "status": status.to_dict(),
            "specs": [
                {
                    "id": s.id,
                    "name": s.name,
                    "phase": s.phase.value,
                    "is_leaf": s.is_leaf,
                    "iteration": s.iteration,
                    "parent_id": s.parent_id,
                }
                for s in specs
            ],
        }
    
    def get_pending_approvals(self) -> List[ApprovalRequestPayload]:
        """Get list of specs awaiting approval."""
        pending = []
        
        for spec_id in self._status.pending_approvals:
            spec = self.spec_store.get(spec_id)
            if spec and is_approval_phase(spec.phase):
                approval_type = {
                    Phase.AWAITING_ARCH_APPROVAL: "architecture",
                    Phase.AWAITING_IMPL_APPROVAL: "implementation",
                    Phase.AWAITING_INTEG_APPROVAL: "integration",
                }.get(spec.phase, "unknown")
                
                pending.append(ApprovalRequestPayload(
                    spec_id=spec.id,
                    spec_name=spec.name,
                    approval_type=approval_type,
                    summary=f"{spec.problem[:100]}...",
                    files_to_review=self._get_files_for_review(spec),
                ))
        
        return pending
    
    def get_spec(self, spec_id: str) -> Optional[Spec]:
        """Get a spec by ID."""
        return self.spec_store.get(spec_id)
    
    async def abort(self, reason: str = "") -> None:
        """Abort the pipeline."""
        self._shutdown_event.set()
        for task in self._running_agents.values():
            task.cancel()
        self._status.running = False
    
    # =========================================================================
    # INTERNAL PROCESSING
    # =========================================================================
    
    async def _process_spec(self, spec: Spec) -> None:
        """Process a spec through its lifecycle."""
        if spec.phase == Phase.READY:
            result = self.state_machine.transition(
                spec, Phase.ARCHITECTURE,
                triggered_by="orchestrator",
                reason="Starting architecture phase",
            )
            
            if result.success:
                self.spec_store.save(spec)
                await self.state_machine.execute_side_effects(spec, result.side_effects)
    
    async def _handle_orchestrator_message(self, message: Message) -> None:
        """Handle messages sent to the orchestrator."""
        msg_type = message.type
        spec_id = message.spec_id or message.from_id
        
        if msg_type == MessageType.PHASE_COMPLETE:
            await self._handle_phase_complete(spec_id, message.payload)
        elif msg_type == MessageType.ERROR_REPORT:
            await self._handle_error_report(spec_id, message.payload)
        elif msg_type == MessageType.APPROVAL_RESPONSE:
            payload = message.payload
            await self.handle_approval(
                payload.get("spec_id", spec_id),
                payload.get("approved", False),
                payload.get("feedback", ""),
            )
        elif msg_type == MessageType.CHILD_COMPLETE:
            await self._handle_child_complete(spec_id, message.payload)
        elif msg_type == MessageType.WAKE_SUPERVISOR:
            await self._handle_wake_supervisor(spec_id, message.payload)
    
    async def _handle_phase_complete(self, spec_id: str, payload: Dict[str, Any]) -> None:
        """Handle phase completion from an agent."""
        spec = self.spec_store.get(spec_id)
        if not spec:
            return
        
        success = payload.get("success", False)
        next_phase_map = {
            Phase.ARCHITECTURE: Phase.AWAITING_ARCH_APPROVAL,
            Phase.IMPLEMENTATION: Phase.AWAITING_IMPL_APPROVAL,
            Phase.INTEGRATION: Phase.AWAITING_INTEG_APPROVAL,
        }
        
        if success and spec.phase in next_phase_map:
            result = self.state_machine.transition(
                spec, next_phase_map[spec.phase],
                triggered_by=f"agent:{spec.phase.value}",
                reason=f"{spec.phase.value} complete",
            )
            if result.success:
                self.spec_store.save(spec)
                await self.state_machine.execute_side_effects(spec, result.side_effects)
    
    async def _handle_error_report(self, spec_id: str, payload: Dict[str, Any]) -> None:
        """Handle error report from an agent."""
        spec = self.spec_store.get(spec_id)
        if not spec:
            return
        
        error = ErrorReport(
            iteration=spec.iteration,
            category=ErrorCategory(payload.get("error_type", "agent")),
            severity=ErrorSeverity.ERROR,
            message=payload.get("message", "Unknown error"),
            details=payload.get("details", {}),
            recoverable=payload.get("recoverable", True),
        )
        spec.add_error(error)
        
        if error.recoverable and spec.can_iterate():
            spec.increment_iteration()
            self.spec_store.save(spec)
            
            if spec.phase == Phase.IMPLEMENTATION:
                await self._deploy_implementation_team(spec, "retry")
            elif spec.phase == Phase.INTEGRATION:
                await self._deploy_integration_team(spec, "retry")
        else:
            result = self.state_machine.transition(
                spec,
                Phase.BLOCKED if error.recoverable else Phase.FAILED,
                triggered_by="orchestrator",
                reason=f"Error: {error.message}",
            )
            if result.success:
                self.spec_store.save(spec)
                await self.state_machine.execute_side_effects(spec, result.side_effects)
    
    async def _handle_child_complete(self, parent_id: str, payload: Dict[str, Any]) -> None:
        """Handle notification that a child completed."""
        parent = self.spec_store.get(parent_id)
        if not parent:
            return
        
        children = self.spec_store.list_children(parent_id)
        all_complete = all(c.phase == Phase.COMPLETE for c in children)
        
        if all_complete and parent.phase == Phase.AWAITING_CHILDREN:
            result = self.state_machine.transition(
                parent, Phase.INTEGRATION,
                triggered_by="orchestrator",
                reason="All children complete",
            )
            if result.success:
                self.spec_store.save(parent)
                await self.state_machine.execute_side_effects(parent, result.side_effects)
    
    async def _handle_wake_supervisor(self, spec_id: str, payload: Dict[str, Any]) -> None:
        """Handle wake request from child."""
        spec = self.spec_store.get(spec_id)
        if not spec or not spec.parent_id:
            return
        
        parent_message = Message(
            from_id=spec_id,
            to_id=spec.parent_id,
            spec_id=spec.parent_id,
            type=MessageType.CONTEXT_UPDATE,
            payload=payload,
            priority=MessagePriority.BLOCKING,
        )
        await self.message_bus.send(parent_message)
    
    # =========================================================================
    # SIDE EFFECT HANDLERS
    # =========================================================================
    
    async def _deploy_architecture_team(self, spec: Spec, effect: str) -> None:
        """Deploy the architecture team for a spec."""
        tech_stack = spec.get_effective_tech_stack()
        
        for i in range(self.config.max_arch_iterations):
            # Proposer designs
            proposer_result = await self.agent_invoker.invoke(
                role=AgentRole.PROPOSER,
                spec=spec,
                tech_stack=tech_stack,
                iteration=i + 1,
            )
            
            if not proposer_result.success:
                continue
            
            spec = self.spec_store.get(spec.id) or spec
            
            # Critic reviews
            critic_result = await self.agent_invoker.invoke(
                role=AgentRole.CRITIC,
                spec=spec,
                tech_stack=tech_stack,
                iteration=i + 1,
            )
            
            if self._critic_approved(critic_result):
                break
        
        complete_msg = Message(
            from_id=spec.id,
            to_id="orchestrator",
            spec_id=spec.id,
            type=MessageType.PHASE_COMPLETE,
            payload={"phase": "architecture", "success": True},
        )
        await self.message_bus.send(complete_msg)
    
    async def _deploy_implementation_team(self, spec: Spec, effect: str) -> None:
        """Deploy the implementation team for a spec."""
        tech_stack = spec.get_effective_tech_stack()
        previous_errors = spec.errors if spec.iteration > 1 else []
        
        impl_result = await self.agent_invoker.invoke(
            role=AgentRole.IMPLEMENTER,
            spec=spec,
            tech_stack=tech_stack,
            iteration=spec.iteration,
            previous_errors=previous_errors,
        )
        
        if not impl_result.success:
            error_msg = Message(
                from_id=spec.id,
                to_id="orchestrator",
                spec_id=spec.id,
                type=MessageType.ERROR_REPORT,
                payload={
                    "error_type": "agent",
                    "message": impl_result.error or "Implementer failed",
                    "recoverable": True,
                },
            )
            await self.message_bus.send(error_msg)
            return
        
        verify_result = await self.agent_invoker.invoke(
            role=AgentRole.VERIFIER,
            spec=spec,
            tech_stack=tech_stack,
            iteration=spec.iteration,
        )
        
        if verify_result.success and self._verification_passed(verify_result):
            complete_msg = Message(
                from_id=spec.id,
                to_id="orchestrator",
                spec_id=spec.id,
                type=MessageType.PHASE_COMPLETE,
                payload={"phase": "implementation", "success": True},
            )
            await self.message_bus.send(complete_msg)
        else:
            error_msg = Message(
                from_id=spec.id,
                to_id="orchestrator",
                spec_id=spec.id,
                type=MessageType.ERROR_REPORT,
                payload={
                    "error_type": "test",
                    "message": "Verification failed",
                    "details": {"output": verify_result.output[:1000]},
                    "recoverable": True,
                },
            )
            await self.message_bus.send(error_msg)
    
    async def _deploy_integration_team(self, spec: Spec, effect: str) -> None:
        """Deploy implementation team for integration."""
        tech_stack = spec.get_effective_tech_stack()
        children = self.spec_store.list_children(spec.id)
        
        impl_result = await self.agent_invoker.invoke(
            role=AgentRole.IMPLEMENTER,
            spec=spec,
            tech_stack=tech_stack,
            iteration=spec.iteration,
            siblings=children,
        )
        
        if impl_result.success:
            verify_result = await self.agent_invoker.invoke(
                role=AgentRole.VERIFIER,
                spec=spec,
                tech_stack=tech_stack,
                iteration=spec.iteration,
            )
            
            if verify_result.success and self._verification_passed(verify_result):
                complete_msg = Message(
                    from_id=spec.id,
                    to_id="orchestrator",
                    spec_id=spec.id,
                    type=MessageType.PHASE_COMPLETE,
                    payload={"phase": "integration", "success": True},
                )
                await self.message_bus.send(complete_msg)
                return
        
        error_msg = Message(
            from_id=spec.id,
            to_id="orchestrator",
            spec_id=spec.id,
            type=MessageType.ERROR_REPORT,
            payload={
                "error_type": "integration",
                "message": "Integration failed",
                "recoverable": True,
            },
        )
        await self.message_bus.send(error_msg)
    
    async def _create_child_specs(self, spec: Spec, effect: str) -> None:
        """Create child specs from parent's children list."""
        children = self.spec_store.create_children(spec)
        
        result = self.state_machine.transition(
            spec, Phase.AWAITING_CHILDREN,
            triggered_by="orchestrator",
            reason=f"Created {len(children)} child specs",
        )
        if result.success:
            self.spec_store.save(spec)
        
        for child in children:
            child.phase = Phase.READY
            self.spec_store.save(child)
            await self._process_spec(child)
    
    async def _monitor_children(self, spec: Spec, effect: str) -> None:
        """Start monitoring children for completion."""
        pass  # Handled by _handle_child_complete
    
    async def _send_approval_request(self, spec: Spec, approval_type: str) -> None:
        """Send approval request to Interface Agent."""
        message = create_approval_request(
            spec_id=spec.id,
            spec_name=spec.name,
            approval_type=approval_type,
            summary=spec.problem[:200],
            files=self._get_files_for_review(spec),
        )
        
        await self.message_bus.send(message)
        
        if spec.id not in self._status.pending_approvals:
            self._status.pending_approvals.append(spec.id)
        
        if self.config.auto_approve:
            await self.handle_approval(spec.id, True, "Auto-approved")
    
    async def _notify_parent_complete(self, spec: Spec, effect: str) -> None:
        """Notify parent that this spec is complete."""
        if spec.parent_id:
            message = Message(
                from_id=spec.id,
                to_id="orchestrator",
                spec_id=spec.parent_id,
                type=MessageType.CHILD_COMPLETE,
                payload={"child_id": spec.id, "child_name": spec.name},
            )
            await self.message_bus.send(message)
    
    async def _notify_failure(self, spec: Spec, effect: str) -> None:
        """Notify of spec failure."""
        message = Message(
            from_id="orchestrator",
            to_id="interface",
            spec_id=spec.id,
            type=MessageType.STATUS_UPDATE,
            payload={
                "event": "spec_failed",
                "spec_id": spec.id,
                "spec_name": spec.name,
                "errors": [e.to_dict() for e in spec.errors[-3:]],
            },
        )
        await self.message_bus.send(message)
    
    async def _log_completion(self, spec: Spec, effect: str) -> None:
        """Log spec completion."""
        log_file = self.state_dir / "completions.jsonl"
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "spec_id": spec.id,
            "spec_name": spec.name,
            "iterations": spec.iteration,
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    
    async def _log_failure(self, spec: Spec, effect: str) -> None:
        """Log spec failure."""
        log_file = self.state_dir / "failures.jsonl"
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "spec_id": spec.id,
            "spec_name": spec.name,
            "iterations": spec.iteration,
            "errors": [e.to_dict() for e in spec.errors],
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    
    # =========================================================================
    # HELPERS
    # =========================================================================
    
    def _get_files_for_review(self, spec: Spec) -> List[str]:
        """Get list of files for user to review."""
        files = []
        if spec.spec_dir:
            spec_file = Path(spec.spec_dir) / "spec.json"
            if spec_file.exists():
                files.append(str(spec_file))
        for cls in spec.classes:
            if cls.location:
                files.append(cls.location)
        return files
    
    def _critic_approved(self, result: AgentResult) -> bool:
        """Check if critic approved the architecture."""
        output = result.output.lower()
        return ("approved" in output or "lgtm" in output) and "reject" not in output
    
    def _verification_passed(self, result: AgentResult) -> bool:
        """Check if verification passed."""
        output = result.output.lower()
        return (
            ("all tests pass" in output or "verification passed" in output) and
            "fail" not in output and "error" not in output
        )


# Singleton management
_orchestrator: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    """Get the global orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        raise RuntimeError("Orchestrator not initialized")
    return _orchestrator


def init_orchestrator(project_root: Path, **kwargs) -> Orchestrator:
    """Initialize the global orchestrator."""
    global _orchestrator
    _orchestrator = Orchestrator(project_root, **kwargs)
    return _orchestrator


def reset_orchestrator() -> None:
    """Reset the orchestrator (for testing)."""
    global _orchestrator
    _orchestrator = None
