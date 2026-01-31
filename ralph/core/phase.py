"""
Phase definitions and transition rules for the Ralph pipeline.

The pipeline is a state machine where specs move through phases.
This module defines valid phases and which transitions are allowed.
"""

from enum import Enum
from typing import Set, Dict, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime, timezone


class Phase(str, Enum):
    """Pipeline phases for a spec."""

    # Initial states
    DRAFT = "draft"                           # User/Interface Agent refining
    READY = "ready"                           # Spec complete, queued for processing

    # Architecture phase
    ARCHITECTURE = "architecture"             # Architecture team working
    AWAITING_ARCH_APPROVAL = "awaiting_arch_approval"  # Waiting for user

    # Decomposition (non-leaf only)
    DECOMPOSING = "decomposing"               # Creating child specs

    # Implementation phase (leaf only)
    IMPLEMENTATION = "implementation"         # Implementation team working
    AWAITING_IMPL_APPROVAL = "awaiting_impl_approval"  # Waiting for user

    # Integration phase (non-leaf only)
    AWAITING_CHILDREN = "awaiting_children"   # Waiting for children to complete
    INTEGRATION = "integration"               # Integrating children
    AWAITING_INTEG_APPROVAL = "awaiting_integ_approval"  # Waiting for user

    # Terminal states
    COMPLETE = "complete"                     # Successfully finished
    FAILED = "failed"                         # Unrecoverable failure
    BLOCKED = "blocked"                       # Needs human intervention


# Valid phase transitions - defines the state machine
PHASE_TRANSITIONS: Dict[Phase, Set[Phase]] = {
    Phase.DRAFT: {Phase.READY},
    Phase.READY: {Phase.ARCHITECTURE},
    Phase.ARCHITECTURE: {Phase.AWAITING_ARCH_APPROVAL, Phase.FAILED, Phase.BLOCKED},
    Phase.AWAITING_ARCH_APPROVAL: {Phase.DECOMPOSING, Phase.IMPLEMENTATION, Phase.ARCHITECTURE},
    Phase.DECOMPOSING: {Phase.AWAITING_CHILDREN, Phase.FAILED, Phase.BLOCKED},
    Phase.AWAITING_CHILDREN: {Phase.INTEGRATION, Phase.FAILED, Phase.BLOCKED},
    Phase.IMPLEMENTATION: {Phase.AWAITING_IMPL_APPROVAL, Phase.FAILED, Phase.BLOCKED},
    Phase.AWAITING_IMPL_APPROVAL: {Phase.COMPLETE, Phase.IMPLEMENTATION},
    Phase.INTEGRATION: {Phase.AWAITING_INTEG_APPROVAL, Phase.FAILED, Phase.BLOCKED},
    Phase.AWAITING_INTEG_APPROVAL: {Phase.COMPLETE, Phase.INTEGRATION},
    Phase.COMPLETE: set(),  # Terminal - no transitions out
    Phase.FAILED: {Phase.ARCHITECTURE, Phase.IMPLEMENTATION},  # Can retry
    Phase.BLOCKED: {Phase.ARCHITECTURE, Phase.IMPLEMENTATION, Phase.INTEGRATION},
}

# Phases that require user approval to exit
APPROVAL_PHASES: Set[Phase] = {
    Phase.AWAITING_ARCH_APPROVAL,
    Phase.AWAITING_IMPL_APPROVAL,
    Phase.AWAITING_INTEG_APPROVAL,
}

# Phases where agents are actively working
ACTIVE_PHASES: Set[Phase] = {
    Phase.ARCHITECTURE,
    Phase.IMPLEMENTATION,
    Phase.INTEGRATION,
}

# Terminal phases
TERMINAL_PHASES: Set[Phase] = {
    Phase.COMPLETE,
    Phase.FAILED,
}


@dataclass(frozen=True)
class PhaseTransition:
    """Represents a recorded phase transition."""

    spec_id: str
    from_phase: Phase
    to_phase: Phase
    reason: str
    triggered_by: str  # "orchestrator", "user", "agent:{role}"
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "spec_id": self.spec_id,
            "from_phase": self.from_phase.value,
            "to_phase": self.to_phase.value,
            "reason": self.reason,
            "triggered_by": self.triggered_by,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PhaseTransition":
        """Create from dictionary."""
        return cls(
            spec_id=data["spec_id"],
            from_phase=Phase(data["from_phase"]),
            to_phase=Phase(data["to_phase"]),
            reason=data["reason"],
            triggered_by=data["triggered_by"],
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        )


def can_transition(from_phase: Union[Phase, str], to_phase: Union[Phase, str]) -> bool:
    """Check if a phase transition is valid."""
    from_p = normalize_phase(from_phase)
    to_p = normalize_phase(to_phase)
    if from_p is None or to_p is None:
        return False
    valid_targets = PHASE_TRANSITIONS.get(from_p, set())
    return to_p in valid_targets


def get_valid_transitions(phase: Union[Phase, str]) -> Set[Phase]:
    """Get all valid transitions from a phase."""
    p = normalize_phase(phase)
    if p is None:
        return set()
    return PHASE_TRANSITIONS.get(p, set())


def is_approval_phase(phase: Union[Phase, str]) -> bool:
    """Check if this phase requires user approval to exit."""
    p = normalize_phase(phase)
    return p is not None and p in APPROVAL_PHASES


def is_active_phase(phase: Union[Phase, str]) -> bool:
    """Check if agents are actively working in this phase."""
    p = normalize_phase(phase)
    return p is not None and p in ACTIVE_PHASES


def is_terminal_phase(phase: Union[Phase, str]) -> bool:
    """Check if this is a terminal phase."""
    p = normalize_phase(phase)
    return p is not None and p in TERMINAL_PHASES


def normalize_phase(value: Union[Phase, str, None]) -> Optional[Phase]:
    """
    Safely convert a value to a Phase enum.

    Args:
        value: Phase enum, string phase name, or None

    Returns:
        Phase enum if valid, None otherwise
    """
    if value is None:
        return None
    if isinstance(value, Phase):
        return value
    if isinstance(value, str):
        try:
            return Phase(value)
        except ValueError:
            return None
    return None


def get_next_phase_after_approval(phase: Phase, approved: bool, is_leaf: bool) -> Optional[Phase]:
    """
    Determine the next phase after an approval decision.

    Args:
        phase: Current approval phase
        approved: Whether user approved
        is_leaf: Whether spec is a leaf (for arch approval)

    Returns:
        Next phase, or None if invalid
    """
    if phase == Phase.AWAITING_ARCH_APPROVAL:
        if approved:
            return Phase.IMPLEMENTATION if is_leaf else Phase.DECOMPOSING
        else:
            return Phase.ARCHITECTURE  # Restart architecture

    elif phase == Phase.AWAITING_IMPL_APPROVAL:
        if approved:
            return Phase.COMPLETE
        else:
            return Phase.IMPLEMENTATION  # Restart implementation

    elif phase == Phase.AWAITING_INTEG_APPROVAL:
        if approved:
            return Phase.COMPLETE
        else:
            return Phase.INTEGRATION  # Restart integration

    elif phase == Phase.BLOCKED:
        # BLOCKED is context-dependent - the caller should track
        # which phase the spec was in before becoming blocked
        # and restart at the appropriate active phase
        return None

    return None
