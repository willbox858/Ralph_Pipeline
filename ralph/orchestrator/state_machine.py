"""
State Machine for the Ralph pipeline.

Manages phase transitions for specs with validation and side effects.
"""

from typing import Optional, List, Dict, Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..core.phase import (
    Phase,
    PhaseTransition,
    can_transition,
    get_next_phase_after_approval,
)
from ..core.spec import Spec
from ..core.errors import InvalidTransitionError


@dataclass
class TransitionResult:
    """Result of attempting a phase transition."""
    success: bool
    new_phase: Optional[Phase] = None
    error: Optional[str] = None
    side_effects: List[str] = field(default_factory=list)


# Type for side effect handlers
SideEffectHandler = Callable[[Spec, str], Awaitable[None]]


class StateMachine:
    """
    Manages phase transitions for specs.
    
    Validates transitions and triggers appropriate side effects.
    """
    
    def __init__(self):
        self._history: List[PhaseTransition] = []
        self._side_effect_handlers: Dict[str, SideEffectHandler] = {}
    
    def register_side_effect_handler(
        self,
        effect_name: str,
        handler: SideEffectHandler,
    ) -> None:
        """Register a handler for a side effect."""
        self._side_effect_handlers[effect_name] = handler
    
    def transition(
        self,
        spec: Spec,
        to_phase: Phase,
        triggered_by: str,
        reason: str = "",
    ) -> TransitionResult:
        """
        Attempt to transition a spec to a new phase.
        
        Args:
            spec: The spec to transition
            to_phase: Target phase
            triggered_by: Who triggered this ("orchestrator", "user", "agent:role")
            reason: Why this transition is happening
            
        Returns:
            TransitionResult with success status and any side effects
        """
        from_phase = spec.phase
        
        # Validate transition
        if not can_transition(from_phase, to_phase):
            return TransitionResult(
                success=False,
                error=f"Invalid transition: {from_phase.value} -> {to_phase.value}"
            )
        
        # Additional validation
        validation_error = self._validate_transition(spec, to_phase)
        if validation_error:
            return TransitionResult(success=False, error=validation_error)
        
        # Determine side effects
        side_effects = self._get_side_effects(spec, from_phase, to_phase)
        
        # Record transition
        transition = PhaseTransition(
            spec_id=spec.id,
            from_phase=from_phase,
            to_phase=to_phase,
            reason=reason,
            triggered_by=triggered_by,
        )
        self._history.append(transition)
        
        # Update spec
        spec.phase = to_phase
        spec.touch()
        
        return TransitionResult(
            success=True,
            new_phase=to_phase,
            side_effects=side_effects,
        )
    
    def _validate_transition(self, spec: Spec, to_phase: Phase) -> Optional[str]:
        """Additional validation for specific transitions."""
        
        if to_phase == Phase.IMPLEMENTATION:
            if spec.is_leaf is not True:
                return "Cannot enter IMPLEMENTATION: spec must be a leaf (is_leaf=true)"
            if not spec.classes:
                return "Cannot enter IMPLEMENTATION: no classes defined"
        
        if to_phase == Phase.DECOMPOSING:
            if spec.is_leaf is True:
                return "Cannot enter DECOMPOSING: spec is a leaf"
            if not spec.children:
                return "Cannot enter DECOMPOSING: no children defined"
        
        return None
    
    def _get_side_effects(
        self,
        spec: Spec,
        from_phase: Phase,
        to_phase: Phase,
    ) -> List[str]:
        """Determine side effects for a transition."""
        effects = []
        
        if to_phase == Phase.ARCHITECTURE:
            effects.append("deploy_architecture_team")
        
        elif to_phase == Phase.AWAITING_ARCH_APPROVAL:
            effects.append("send_approval_request:architecture")
        
        elif to_phase == Phase.DECOMPOSING:
            effects.append("create_child_specs")
        
        elif to_phase == Phase.IMPLEMENTATION:
            effects.append("deploy_implementation_team")
        
        elif to_phase == Phase.AWAITING_IMPL_APPROVAL:
            effects.append("send_approval_request:implementation")
        
        elif to_phase == Phase.AWAITING_CHILDREN:
            effects.append("monitor_children")
        
        elif to_phase == Phase.INTEGRATION:
            effects.append("deploy_integration_team")
        
        elif to_phase == Phase.AWAITING_INTEG_APPROVAL:
            effects.append("send_approval_request:integration")
        
        elif to_phase == Phase.COMPLETE:
            effects.append("notify_parent_complete")
            effects.append("log_completion")
        
        elif to_phase == Phase.FAILED:
            effects.append("notify_failure")
            effects.append("log_failure")
        
        elif to_phase == Phase.BLOCKED:
            effects.append("send_approval_request:blocked")
        
        return effects
    
    async def execute_side_effects(
        self,
        spec: Spec,
        side_effects: List[str],
    ) -> Dict[str, bool]:
        """
        Execute side effects from a transition.
        
        Returns dict of effect_name -> success.
        """
        results = {}
        
        for effect in side_effects:
            handler = self._side_effect_handlers.get(effect)
            if handler:
                try:
                    await handler(spec, effect)
                    results[effect] = True
                except Exception as e:
                    results[effect] = False
                    print(f"Side effect {effect} failed: {e}")
            else:
                # No handler registered - log but don't fail
                results[effect] = True
        
        return results
    
    def handle_approval(
        self,
        spec: Spec,
        approved: bool,
        triggered_by: str = "user",
        reason: str = "",
    ) -> TransitionResult:
        """
        Handle an approval decision.
        
        Args:
            spec: The spec being approved/rejected
            approved: Whether user approved
            triggered_by: Who made the decision
            reason: Feedback or reason
        """
        next_phase = get_next_phase_after_approval(
            spec.phase,
            approved,
            spec.is_leaf or False,
        )
        
        if next_phase is None:
            return TransitionResult(
                success=False,
                error=f"Cannot handle approval in phase {spec.phase.value}"
            )
        
        return self.transition(
            spec,
            next_phase,
            triggered_by=triggered_by,
            reason=f"{'Approved' if approved else 'Rejected'}: {reason}",
        )
    
    def get_history(self, spec_id: Optional[str] = None) -> List[PhaseTransition]:
        """Get transition history, optionally filtered by spec."""
        if spec_id:
            return [t for t in self._history if t.spec_id == spec_id]
        return list(self._history)
    
    def clear_history(self) -> None:
        """Clear transition history."""
        self._history.clear()
