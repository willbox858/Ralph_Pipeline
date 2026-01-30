"""
Message types for communication between agents and the orchestrator.

Messages flow through the MessageBus and are the primary mechanism for:
- Agent → Orchestrator communication (phase completion, errors)
- Agent → Parent communication (escalation, completion)
- Orchestrator → Interface Agent communication (approval requests)
- Interface Agent → Orchestrator communication (approvals, feedback)
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum
from datetime import datetime, timezone
import uuid


class MessageType(str, Enum):
    """Types of messages in the system."""
    
    # Agent → Orchestrator
    PHASE_COMPLETE = "phase_complete"         # Agent finished their work
    ERROR_REPORT = "error_report"             # Something went wrong
    NEED_SHARED_TYPE = "need_shared_type"     # Request cross-cutting type
    
    # Agent → Parent (via Orchestrator)
    WAKE_SUPERVISOR = "wake_supervisor"       # Child needs parent attention
    CHILD_COMPLETE = "child_complete"         # Child finished successfully
    ESCALATION = "escalation"                 # Problem child can't solve
    
    # Orchestrator → Agent (via hooks)
    CONTEXT_UPDATE = "context_update"         # Updated spec/state
    SIBLING_UPDATE = "sibling_update"         # Sibling status changed
    PARENT_DECISION = "parent_decision"       # Parent made a decision
    
    # Orchestrator → Interface Agent
    APPROVAL_REQUEST = "approval_request"     # Need user approval
    STATUS_UPDATE = "status_update"           # Pipeline status changed
    
    # Interface Agent → Orchestrator  
    APPROVAL_RESPONSE = "approval_response"   # User approved/rejected
    USER_FEEDBACK = "user_feedback"           # User provided guidance
    
    # Control messages
    ABORT = "abort"                           # Stop everything
    RESTART_PHASE = "restart_phase"           # Restart current phase


class MessagePriority(str, Enum):
    """Message priority levels."""
    NORMAL = "normal"      # Delivered on next check
    HIGH = "high"          # Delivered soon
    BLOCKING = "blocking"  # Wakes hibernating recipient


class MessageStatus(str, Enum):
    """Message delivery status."""
    PENDING = "pending"        # Not yet delivered
    DELIVERED = "delivered"    # In recipient's inbox
    PROCESSED = "processed"    # Recipient acknowledged
    EXPIRED = "expired"        # TTL exceeded


@dataclass
class Message:
    """A message between components."""
    
    # Identity
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    # Routing
    from_id: str = ""         # Sender (spec_id, "orchestrator", "interface")
    to_id: str = ""           # Recipient (spec_id, "orchestrator", "interface", "parent")
    spec_id: str = ""         # Related spec (for context)
    
    # Content
    type: MessageType = MessageType.STATUS_UPDATE
    payload: Dict[str, Any] = field(default_factory=dict)
    
    # Delivery
    priority: MessagePriority = MessagePriority.NORMAL
    status: MessageStatus = MessageStatus.PENDING
    
    # Timestamps
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    delivered_at: Optional[str] = None
    processed_at: Optional[str] = None
    
    # Response tracking
    reply_to: Optional[str] = None  # ID of message this replies to
    expects_reply: bool = False
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "from_id": self.from_id,
            "to_id": self.to_id,
            "spec_id": self.spec_id,
            "type": self.type.value,
            "payload": self.payload,
            "priority": self.priority.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "delivered_at": self.delivered_at,
            "processed_at": self.processed_at,
            "reply_to": self.reply_to,
            "expects_reply": self.expects_reply,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        """Create from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            from_id=data.get("from_id", ""),
            to_id=data.get("to_id", ""),
            spec_id=data.get("spec_id", ""),
            type=MessageType(data["type"]) if "type" in data else MessageType.STATUS_UPDATE,
            payload=data.get("payload", {}),
            priority=MessagePriority(data.get("priority", "normal")),
            status=MessageStatus(data.get("status", "pending")),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            delivered_at=data.get("delivered_at"),
            processed_at=data.get("processed_at"),
            reply_to=data.get("reply_to"),
            expects_reply=data.get("expects_reply", False),
        )
    
    def mark_delivered(self) -> None:
        """Mark message as delivered."""
        self.status = MessageStatus.DELIVERED
        self.delivered_at = datetime.now(timezone.utc).isoformat()
    
    def mark_processed(self) -> None:
        """Mark message as processed."""
        self.status = MessageStatus.PROCESSED
        self.processed_at = datetime.now(timezone.utc).isoformat()


# =============================================================================
# TYPED PAYLOADS
# =============================================================================

@dataclass
class PhaseCompletePayload:
    """Payload for PHASE_COMPLETE messages."""
    phase: str
    success: bool
    artifacts: List[str] = field(default_factory=list)
    summary: str = ""
    next_phase_ready: bool = True
    
    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "success": self.success,
            "artifacts": self.artifacts,
            "summary": self.summary,
            "next_phase_ready": self.next_phase_ready,
        }


@dataclass
class ApprovalRequestPayload:
    """Payload for APPROVAL_REQUEST messages."""
    spec_id: str
    spec_name: str
    approval_type: str  # "architecture", "implementation", "integration"
    summary: str
    files_to_review: List[str] = field(default_factory=list)
    decisions_made: List[Dict[str, str]] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "spec_id": self.spec_id,
            "spec_name": self.spec_name,
            "approval_type": self.approval_type,
            "summary": self.summary,
            "files_to_review": self.files_to_review,
            "decisions_made": self.decisions_made,
        }


@dataclass
class ApprovalResponsePayload:
    """Payload for APPROVAL_RESPONSE messages."""
    spec_id: str
    approved: bool
    feedback: str = ""
    requested_changes: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "spec_id": self.spec_id,
            "approved": self.approved,
            "feedback": self.feedback,
            "requested_changes": self.requested_changes,
        }


@dataclass
class ErrorReportPayload:
    """Payload for ERROR_REPORT messages."""
    error_type: str  # "compilation", "test", "validation", "agent", "blocked"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    recoverable: bool = True
    suggested_action: str = ""
    
    def to_dict(self) -> dict:
        return {
            "error_type": self.error_type,
            "message": self.message,
            "details": self.details,
            "recoverable": self.recoverable,
            "suggested_action": self.suggested_action,
        }


@dataclass
class NeedSharedTypePayload:
    """Payload for NEED_SHARED_TYPE messages."""
    type_name: str
    type_kind: str  # "class", "interface", "enum", "record"
    reason: str
    suggested_fields: List[Dict[str, str]] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "type_name": self.type_name,
            "type_kind": self.type_kind,
            "reason": self.reason,
            "suggested_fields": self.suggested_fields,
        }


# =============================================================================
# MESSAGE FACTORIES
# =============================================================================

def create_phase_complete_message(
    from_spec_id: str,
    phase: str,
    success: bool,
    artifacts: Optional[List[str]] = None,
    summary: str = "",
) -> Message:
    """Create a phase completion message."""
    payload = PhaseCompletePayload(
        phase=phase,
        success=success,
        artifacts=artifacts or [],
        summary=summary,
    )
    return Message(
        from_id=from_spec_id,
        to_id="orchestrator",
        spec_id=from_spec_id,
        type=MessageType.PHASE_COMPLETE,
        payload=payload.to_dict(),
    )


def create_approval_request(
    spec_id: str,
    spec_name: str,
    approval_type: str,
    summary: str,
    files: Optional[List[str]] = None,
) -> Message:
    """Create an approval request message."""
    payload = ApprovalRequestPayload(
        spec_id=spec_id,
        spec_name=spec_name,
        approval_type=approval_type,
        summary=summary,
        files_to_review=files or [],
    )
    return Message(
        from_id="orchestrator",
        to_id="interface",
        spec_id=spec_id,
        type=MessageType.APPROVAL_REQUEST,
        payload=payload.to_dict(),
        expects_reply=True,
    )


def create_error_report(
    from_spec_id: str,
    error_type: str,
    message: str,
    details: Optional[Dict] = None,
    recoverable: bool = True,
) -> Message:
    """Create an error report message."""
    payload = ErrorReportPayload(
        error_type=error_type,
        message=message,
        details=details or {},
        recoverable=recoverable,
    )
    return Message(
        from_id=from_spec_id,
        to_id="orchestrator",
        spec_id=from_spec_id,
        type=MessageType.ERROR_REPORT,
        payload=payload.to_dict(),
        priority=MessagePriority.HIGH,
    )
