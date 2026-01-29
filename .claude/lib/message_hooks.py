"""
Ralph Message Delivery Hooks

Hooks that deliver inter-agent messages by injecting them into the
conversation context at tool boundaries.

Instead of agents polling for messages, these hooks:
1. Check for pending messages on PreToolUse
2. Inject messages via additionalContext
3. Mark messages as delivered

This provides seamless, proactive message delivery without
agents needing to explicitly check for messages.

Usage with Agent SDK:
    from message_hooks import create_message_delivery_hooks

    hooks = create_message_delivery_hooks(spec_id="my-spec")
    options = ClaudeAgentOptions(hooks=hooks, ...)
"""

import json
from typing import Optional, Callable


def format_message_for_context(message) -> str:
    """Format a message for injection into conversation context."""
    priority_prefix = ""
    if message.priority == "blocking":
        priority_prefix = "[!] BLOCKING: "
    elif message.priority == "high":
        priority_prefix = "[!] HIGH PRIORITY: "

    payload_str = json.dumps(message.payload, indent=2)

    return f"""
---
{priority_prefix}MESSAGE FROM: {message.from_spec}
Type: {message.type}
Sent: {message.created_at}

{payload_str}
---
"""


def format_messages_for_context(messages: list) -> str:
    """Format multiple messages for injection."""
    if not messages:
        return ""

    header = f"\n[INBOX] You have {len(messages)} pending message(s):\n"
    formatted = [format_message_for_context(m) for m in messages]
    return header + "\n".join(formatted)


def create_message_delivery_hook(spec_id: str, db=None, log_func: Optional[Callable] = None):
    """
    Create a PreToolUse hook that delivers pending messages.

    Args:
        spec_id: The spec ID to check messages for
        db: RalphDB instance (will import if not provided)
        log_func: Optional logging function
    """

    async def deliver_messages(input_data: dict, tool_use_id: Optional[str], context) -> dict:
        if input_data.get('hook_event_name') != 'PreToolUse':
            return {}

        # Lazy import to avoid circular dependencies
        if db is None:
            try:
                from ralph_db import get_db
                _db = get_db()
            except ImportError:
                return {}
        else:
            _db = db

        # Get pending messages
        messages = _db.get_pending_messages(spec_id)

        if not messages:
            return {}

        # Format messages for context injection
        context_text = format_messages_for_context(messages)

        # Mark messages as delivered
        for msg in messages:
            _db.mark_message_delivered(msg.id)
            if log_func:
                log_func(f"Delivered message {msg.id} ({msg.type}) from {msg.from_spec}")

        # Inject into conversation
        return {
            'additionalContext': context_text
        }

    return deliver_messages


def create_blocking_message_hook(spec_id: str, db=None, log_func: Optional[Callable] = None):
    """
    Create a hook that pauses execution if there are blocking messages
    that require a response.

    This hook checks for messages marked as 'blocking' priority and
    injects them with instructions to respond before continuing.
    """

    async def check_blocking_messages(input_data: dict, tool_use_id: Optional[str], context) -> dict:
        if input_data.get('hook_event_name') != 'PreToolUse':
            return {}

        # Lazy import
        if db is None:
            try:
                from ralph_db import get_db
                _db = get_db()
            except ImportError:
                return {}
        else:
            _db = db

        # Get only blocking messages
        all_messages = _db.get_pending_messages(spec_id)
        blocking = [m for m in all_messages if m.priority == 'blocking']

        if not blocking:
            return {}

        # Format with response instructions
        context_text = f"""
🔴 BLOCKING MESSAGE(S) REQUIRE YOUR RESPONSE

You have {len(blocking)} blocking message(s) that require a response
before you can continue with your current task.

Please use the `respond_to_message` MCP tool to respond to each blocking
message before proceeding.
"""
        for msg in blocking:
            context_text += f"""
---
MESSAGE ID: {msg.id}
FROM: {msg.from_spec}
TYPE: {msg.type}

{json.dumps(msg.payload, indent=2)}

To respond, call:
  mcp__orchestrator__respond_to_message(message_id="{msg.id}", response={{...}})
---
"""

        # Mark as delivered but not processed
        for msg in blocking:
            _db.mark_message_delivered(msg.id)
            if log_func:
                log_func(f"Delivered BLOCKING message {msg.id} from {msg.from_spec}")

        return {
            'additionalContext': context_text,
            'systemMessage': 'IMPORTANT: You have blocking messages that require responses. Address them before continuing.'
        }

    return check_blocking_messages


def create_message_response_hook(spec_id: str, db=None, log_func: Optional[Callable] = None):
    """
    Create a PostToolUse hook that processes message responses.

    When an agent calls respond_to_message, this hook:
    1. Verifies the response was recorded
    2. Notifies the sender (if they're hibernating)
    """

    async def process_response(input_data: dict, tool_use_id: Optional[str], context) -> dict:
        if input_data.get('hook_event_name') != 'PostToolUse':
            return {}

        tool_name = input_data.get('tool_name', '')
        if 'respond_to_message' not in tool_name:
            return {}

        # Could add notification logic here
        if log_func:
            log_func(f"Message response processed by {spec_id}")

        return {}

    return process_response


def create_message_delivery_hooks(
    spec_id: str,
    db=None,
    log_func: Optional[Callable] = None,
    include_blocking: bool = True
) -> dict:
    """
    Create all message delivery hooks for an agent.

    Returns a hooks dict suitable for ClaudeAgentOptions.

    Args:
        spec_id: The spec ID to deliver messages for
        db: RalphDB instance (optional, will use singleton)
        log_func: Optional logging function
        include_blocking: Whether to include blocking message handler

    Usage:
        hooks = create_message_delivery_hooks("my-spec")
        options = ClaudeAgentOptions(hooks=hooks, ...)
    """
    try:
        from claude_agent_sdk import HookMatcher
    except ImportError:
        # Return empty if SDK not available
        return {}

    pre_hooks = []

    # Blocking messages first (highest priority)
    if include_blocking:
        pre_hooks.append(
            HookMatcher(hooks=[create_blocking_message_hook(spec_id, db, log_func)])
        )

    # Regular message delivery
    pre_hooks.append(
        HookMatcher(hooks=[create_message_delivery_hook(spec_id, db, log_func)])
    )

    return {
        'PreToolUse': pre_hooks,
        'PostToolUse': [
            HookMatcher(hooks=[create_message_response_hook(spec_id, db, log_func)])
        ]
    }


def merge_hooks(*hook_dicts: dict) -> dict:
    """
    Merge multiple hook dictionaries together.

    Useful for combining message hooks with enforcement hooks.

    Usage:
        from hooks import create_enforcement_hooks
        from message_hooks import create_message_delivery_hooks, merge_hooks

        enforcement = create_enforcement_hooks(agent_config)
        messages = create_message_delivery_hooks(spec_id)
        combined = merge_hooks(enforcement, messages)

        options = ClaudeAgentOptions(hooks=combined, ...)
    """
    result = {}

    for hooks in hook_dicts:
        for event_type, matchers in hooks.items():
            if event_type not in result:
                result[event_type] = []
            result[event_type].extend(matchers)

    return result
