"""
Message Bus for the Ralph pipeline.

Routes messages between agents and the orchestrator.
Handles delivery, wake triggers, and persistence.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Awaitable
from datetime import datetime, timezone
from pathlib import Path
import json
import asyncio
from collections import defaultdict

from ..core.message import (
    Message,
    MessageType,
    MessagePriority,
    MessageStatus,
)


# Type alias for message handlers
MessageHandler = Callable[[Message], Awaitable[None]]


@dataclass
class Inbox:
    """Per-recipient message inbox."""
    recipient_id: str
    messages: List[Message] = field(default_factory=list)
    
    def add(self, message: Message) -> None:
        """Add a message to the inbox."""
        self.messages.append(message)
    
    def get_pending(self) -> List[Message]:
        """Get all pending messages."""
        return [m for m in self.messages if m.status == MessageStatus.PENDING]
    
    def get_by_type(self, msg_type: MessageType) -> List[Message]:
        """Get messages of a specific type."""
        return [m for m in self.messages if m.type == msg_type]
    
    def mark_all_delivered(self) -> List[Message]:
        """Mark all pending messages as delivered and return them."""
        pending = self.get_pending()
        for msg in pending:
            msg.mark_delivered()
        return pending
    
    def clear_processed(self) -> int:
        """Remove processed messages and return count removed."""
        original_count = len(self.messages)
        self.messages = [m for m in self.messages if m.status != MessageStatus.PROCESSED]
        return original_count - len(self.messages)


class MessageBus:
    """
    Central message bus for the Ralph pipeline.
    
    Responsibilities:
    - Route messages to recipients
    - Maintain per-recipient inboxes
    - Trigger wake events for blocking messages
    - Persist messages for recovery
    """
    
    def __init__(self, state_dir: Optional[Path] = None):
        self._inboxes: Dict[str, Inbox] = defaultdict(lambda: Inbox(recipient_id=""))
        self._handlers: Dict[str, List[MessageHandler]] = defaultdict(list)
        self._wake_events: Dict[str, asyncio.Event] = {}
        self._state_dir = state_dir
        self._message_log: List[Message] = []
        
        # Load persisted state if available
        if state_dir:
            self._load_state()
    
    def _get_inbox(self, recipient_id: str) -> Inbox:
        """Get or create inbox for recipient."""
        if recipient_id not in self._inboxes:
            self._inboxes[recipient_id] = Inbox(recipient_id=recipient_id)
        return self._inboxes[recipient_id]
    
    def _get_wake_event(self, recipient_id: str) -> asyncio.Event:
        """Get or create wake event for recipient."""
        if recipient_id not in self._wake_events:
            self._wake_events[recipient_id] = asyncio.Event()
        return self._wake_events[recipient_id]
    
    async def send(self, message: Message) -> str:
        """
        Send a message.
        
        Args:
            message: The message to send
            
        Returns:
            Message ID
        """
        # Resolve "parent" to actual parent ID
        to_id = message.to_id
        if to_id == "parent":
            # This should be resolved by the caller or via spec lookup
            # For now, we'll keep it as-is and let the orchestrator handle it
            pass
        
        # Add to recipient's inbox
        inbox = self._get_inbox(to_id)
        inbox.add(message)
        
        # Log for persistence
        self._message_log.append(message)
        
        # Trigger wake event for blocking messages
        if message.priority == MessagePriority.BLOCKING:
            event = self._get_wake_event(to_id)
            event.set()
        
        # Call registered handlers
        for handler in self._handlers.get(to_id, []):
            try:
                await handler(message)
            except Exception as e:
                # Log but don't fail
                print(f"Handler error for {to_id}: {e}")
        
        # Call global handlers (registered for "*")
        for handler in self._handlers.get("*", []):
            try:
                await handler(message)
            except Exception as e:
                print(f"Global handler error: {e}")
        
        # Persist if state_dir configured
        if self._state_dir:
            self._save_state()
        
        return message.id
    
    def send_sync(self, message: Message) -> str:
        """Synchronous send (for non-async contexts)."""
        to_id = message.to_id
        
        inbox = self._get_inbox(to_id)
        inbox.add(message)
        self._message_log.append(message)
        
        if message.priority == MessagePriority.BLOCKING:
            event = self._get_wake_event(to_id)
            event.set()
        
        if self._state_dir:
            self._save_state()
        
        return message.id
    
    def get_pending(self, recipient_id: str) -> List[Message]:
        """Get pending messages for a recipient."""
        inbox = self._get_inbox(recipient_id)
        return inbox.get_pending()
    
    def get_pending_by_type(
        self,
        recipient_id: str,
        msg_type: MessageType,
    ) -> List[Message]:
        """Get pending messages of a specific type."""
        inbox = self._get_inbox(recipient_id)
        return [
            m for m in inbox.get_pending()
            if m.type == msg_type
        ]
    
    def deliver(self, recipient_id: str) -> List[Message]:
        """
        Deliver all pending messages to recipient.
        
        Marks messages as delivered and returns them.
        """
        inbox = self._get_inbox(recipient_id)
        delivered = inbox.mark_all_delivered()
        
        if self._state_dir:
            self._save_state()
        
        return delivered
    
    def mark_processed(self, message_id: str) -> bool:
        """Mark a message as processed."""
        for inbox in self._inboxes.values():
            for msg in inbox.messages:
                if msg.id == message_id:
                    msg.mark_processed()
                    if self._state_dir:
                        self._save_state()
                    return True
        return False
    
    def register_handler(
        self,
        recipient_id: str,
        handler: MessageHandler,
    ) -> None:
        """
        Register a message handler for a recipient.
        
        Use "*" as recipient_id for a global handler.
        """
        self._handlers[recipient_id].append(handler)
    
    def unregister_handler(
        self,
        recipient_id: str,
        handler: MessageHandler,
    ) -> bool:
        """Unregister a message handler."""
        handlers = self._handlers.get(recipient_id, [])
        if handler in handlers:
            handlers.remove(handler)
            return True
        return False
    
    async def wait_for_message(
        self,
        recipient_id: str,
        timeout: Optional[float] = None,
    ) -> bool:
        """
        Wait for a blocking message.
        
        Returns True if woken by message, False if timeout.
        """
        event = self._get_wake_event(recipient_id)
        event.clear()  # Reset event
        
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
    
    def has_pending(self, recipient_id: str) -> bool:
        """Check if recipient has pending messages."""
        inbox = self._get_inbox(recipient_id)
        return len(inbox.get_pending()) > 0
    
    def get_message(self, message_id: str) -> Optional[Message]:
        """Get a message by ID."""
        for msg in self._message_log:
            if msg.id == message_id:
                return msg
        return None
    
    def get_conversation(
        self,
        spec_id: str,
        limit: int = 100,
    ) -> List[Message]:
        """Get all messages related to a spec."""
        return [
            m for m in self._message_log
            if m.spec_id == spec_id
        ][-limit:]
    
    def clear_inbox(self, recipient_id: str) -> int:
        """Clear all messages for a recipient."""
        if recipient_id in self._inboxes:
            count = len(self._inboxes[recipient_id].messages)
            self._inboxes[recipient_id].messages.clear()
            return count
        return 0
    
    def get_stats(self) -> Dict[str, any]:
        """Get message bus statistics."""
        pending_count = sum(
            len(inbox.get_pending())
            for inbox in self._inboxes.values()
        )
        
        by_type = defaultdict(int)
        for msg in self._message_log:
            by_type[msg.type.value] += 1
        
        return {
            "total_messages": len(self._message_log),
            "pending_messages": pending_count,
            "inboxes": len(self._inboxes),
            "by_type": dict(by_type),
        }
    
    # =========================================================================
    # PERSISTENCE
    # =========================================================================
    
    def _save_state(self) -> None:
        """Save state to disk."""
        if not self._state_dir:
            return
        
        self._state_dir.mkdir(parents=True, exist_ok=True)
        state_file = self._state_dir / "message_bus.json"
        
        state = {
            "messages": [m.to_dict() for m in self._message_log],
            "inboxes": {
                rid: [m.to_dict() for m in inbox.messages]
                for rid, inbox in self._inboxes.items()
            },
        }
        
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    
    def _load_state(self) -> None:
        """Load state from disk."""
        if not self._state_dir:
            return
        
        state_file = self._state_dir / "message_bus.json"
        if not state_file.exists():
            return
        
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
            
            self._message_log = [
                Message.from_dict(m) for m in state.get("messages", [])
            ]
            
            for rid, messages in state.get("inboxes", {}).items():
                inbox = self._get_inbox(rid)
                inbox.messages = [Message.from_dict(m) for m in messages]
        
        except Exception as e:
            print(f"Failed to load message bus state: {e}")


# =============================================================================
# SINGLETON
# =============================================================================

_bus: Optional[MessageBus] = None


def get_message_bus(state_dir: Optional[Path] = None) -> MessageBus:
    """Get the global message bus singleton."""
    global _bus
    if _bus is None:
        _bus = MessageBus(state_dir)
    return _bus


def reset_message_bus() -> None:
    """Reset the message bus (for testing)."""
    global _bus
    _bus = None
