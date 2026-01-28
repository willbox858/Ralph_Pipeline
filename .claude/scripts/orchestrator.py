#!/usr/bin/env python3
"""
Ralph Orchestrator v4: Parallel Execution with Hibernation

The orchestrator is a Python process that:
1. Manages a work queue of specs to process
2. Tracks dependencies between specs
3. Spawns agents in parallel (respecting dependencies)
4. Provides MCP tools for agent communication
5. Handles hibernation/wake cycles for any agent
6. Triggers integration tests when siblings complete
7. Exposes status for user-facing Claude to query

Architecture:
    User <-> Claude Code -> runs orchestrator.py
                              |
                         Orchestrator
                              |
              +---------------+---------------+
              |               |               |
          Agent A         Agent B         Agent C
              +---------------+---------------+
                              |
                    MCP Server (in-process)
                    - send_message
                    - hibernate  
                    - signal_complete
                    - check_dependency
                    - request_parent_decision

Requirements:
    pip install claude-agent-sdk

Usage:
    python orchestrator.py --spec path/to/spec.json [--dry-run] [--live]
"""

import argparse
import asyncio
import json
import os
import sys
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any, Callable, Awaitable
from enum import Enum
import traceback

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from spec import (
    Spec, load_spec, save_spec, is_leaf, is_ready,
    create_child_spec, create_shared_spec, Child, spec_to_dict,
    ClassDef, Criterion, Errors, SharedType
)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class Config:
    max_depth: int = 3
    max_iterations: int = 10
    max_arch_iterations: int = 5
    max_total_agents: int = 100
    max_concurrent_agents: int = 5
    dry_run: bool = False
    live: bool = False
    model: str = "claude-opus-4-5-20251101"


CONFIG = Config()


class Phase(str, Enum):
    PENDING = "pending"
    RESEARCH = "research"
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"
    INTEGRATION = "integration"
    COMPLETE = "complete"
    FAILED = "failed"
    BLOCKED = "blocked"


class Priority(str, Enum):
    NORMAL = "normal"
    BLOCKING = "blocking"
    URGENT = "urgent"


# =============================================================================
# SHARED ORCHESTRATOR STATE
# =============================================================================

@dataclass
class Message:
    id: str
    from_spec: str
    to_spec: str
    type: str
    payload: dict
    priority: Priority
    timestamp: str
    status: str = "pending"  # pending, processed
    response: Optional[dict] = None


@dataclass 
class HibernationContext:
    spec_name: str
    agent_type: str
    phase: Phase
    state: dict
    resume_trigger: str  # e.g., "message_response:msg-001", "dependency:shared"
    instructions: str
    exported_at: str


@dataclass
class SpecStatus:
    name: str
    path: Path
    phase: Phase
    depth: int
    parent: Optional[str] = None
    children: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    current_agent: Optional[str] = None
    iteration: int = 0
    error: Optional[str] = None


class OrchestratorState:
    """
    Shared state accessed by MCP tools and orchestrator logic.
    Thread-safe for asyncio (single-threaded but concurrent).
    """
    
    def __init__(self):
        # Spec tracking
        self.specs: dict[str, SpecStatus] = {}
        
        # Message queues per spec
        self.messages: dict[str, list[Message]] = {}
        self.message_counter: int = 0
        
        # Hibernation contexts
        self.hibernating: dict[str, HibernationContext] = {}
        
        # Wake signals (spec_name -> Event)
        self.wake_events: dict[str, asyncio.Event] = {}
        
        # Response futures for blocking requests
        self.pending_responses: dict[str, asyncio.Future] = {}
        
        # Active agent tasks
        self.active_tasks: dict[str, asyncio.Task] = {}
        
        # Completion tracking
        self.agents_spawned: int = 0
        
        # Human review queue
        self.needs_review: list[dict] = []
    
    def get_spec_status(self, name: str) -> Optional[SpecStatus]:
        return self.specs.get(name)
    
    def set_spec_status(self, name: str, status: SpecStatus):
        self.specs[name] = status
    
    def add_message(self, msg: Message):
        if msg.to_spec not in self.messages:
            self.messages[msg.to_spec] = []
        self.messages[msg.to_spec].append(msg)
        
        # Set wake event if blocking
        if msg.priority == Priority.BLOCKING:
            if msg.to_spec in self.wake_events:
                self.wake_events[msg.to_spec].set()
    
    def get_pending_messages(self, spec_name: str) -> list[Message]:
        return [m for m in self.messages.get(spec_name, []) if m.status == "pending"]
    
    def mark_message_processed(self, msg_id: str):
        for msgs in self.messages.values():
            for m in msgs:
                if m.id == msg_id:
                    m.status = "processed"
                    return
    
    def hibernate_agent(self, ctx: HibernationContext):
        self.hibernating[ctx.spec_name] = ctx
        # Create wake event
        self.wake_events[ctx.spec_name] = asyncio.Event()
    
    def wake_agent(self, spec_name: str) -> Optional[HibernationContext]:
        ctx = self.hibernating.pop(spec_name, None)
        if spec_name in self.wake_events:
            del self.wake_events[spec_name]
        return ctx
    
    def is_hibernating(self, spec_name: str) -> bool:
        return spec_name in self.hibernating
    
    def get_ready_specs(self) -> list[str]:
        """Get specs whose dependencies are satisfied and aren't blocked."""
        ready = []
        for name, status in self.specs.items():
            if status.phase in [Phase.COMPLETE, Phase.FAILED, Phase.BLOCKED]:
                continue
            if name in self.active_tasks:
                continue
            if self.is_hibernating(name):
                continue
            
            # Check dependencies
            deps_satisfied = all(
                self.specs.get(dep, SpecStatus(dep, Path(), Phase.PENDING, 0)).phase == Phase.COMPLETE
                for dep in status.depends_on
            )
            
            if deps_satisfied:
                ready.append(name)
        
        return ready
    
    def all_children_complete(self, parent_name: str) -> bool:
        """Check if all children of a parent are complete."""
        parent = self.specs.get(parent_name)
        if not parent:
            return False
        
        for child_name in parent.children:
            child = self.specs.get(child_name)
            if not child or child.phase != Phase.COMPLETE:
                return False
        
        return len(parent.children) > 0
    
    def flag_for_review(self, spec_name: str, reason: str, details: dict):
        self.needs_review.append({
            "spec": spec_name,
            "reason": reason,
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })


# Global state instance
STATE = OrchestratorState()


# =============================================================================
# MCP TOOLS
# =============================================================================

def create_mcp_tools():
    """Create MCP tools that access the global STATE."""
    
    try:
        from claude_agent_sdk import tool, create_sdk_mcp_server
    except ImportError:
        print("ERROR: pip install claude-agent-sdk")
        sys.exit(1)
    
    @tool("send_message", "Send a message to another spec (parent or sibling)", {
        "to": str,
        "type": str,
        "payload": dict,
        "priority": str,
        "needs_response": bool
    })
    async def send_message(args: dict) -> dict:
        msg_id = f"msg-{STATE.message_counter:04d}"
        STATE.message_counter += 1
        
        msg = Message(
            id=msg_id,
            from_spec=args.get("_caller_spec", "unknown"),
            to_spec=args["to"],
            type=args["type"],
            payload=args["payload"],
            priority=Priority(args.get("priority", "normal")),
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        STATE.add_message(msg)
        
        return {
            "content": [{
                "type": "text",
                "text": f"Message {msg_id} sent to {args['to']} (type: {args['type']}, priority: {args['priority']})"
            }]
        }
    
    @tool("hibernate", "Save state and gracefully terminate, to be woken later", {
        "resume_trigger": str,
        "state": dict,
        "instructions": str
    })
    async def hibernate(args: dict) -> dict:
        # The actual hibernation is handled by the orchestrator when it sees this response
        # We just signal the intent here
        return {
            "content": [{
                "type": "text",
                "text": "Hibernation requested. Saving state..."
            }],
            # Special field the orchestrator looks for
            "_hibernation_request": {
                "resume_trigger": args["resume_trigger"],
                "state": args["state"],
                "instructions": args["instructions"]
            }
        }
    
    @tool("signal_complete", "Signal that this spec's work is complete", {
        "success": bool,
        "summary": str
    })
    async def signal_complete(args: dict) -> dict:
        return {
            "content": [{
                "type": "text",
                "text": f"Completion signaled: {'success' if args['success'] else 'failure'}"
            }],
            "_completion_signal": {
                "success": args["success"],
                "summary": args["summary"]
            }
        }
    
    @tool("check_dependency", "Check if a dependency spec is complete", {
        "name": str
    })
    async def check_dependency(args: dict) -> dict:
        status = STATE.get_spec_status(args["name"])
        if not status:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Dependency '{args['name']}' not found"
                }],
                "ready": False,
                "status": "unknown"
            }
        
        ready = status.phase == Phase.COMPLETE
        return {
            "content": [{
                "type": "text",
                "text": f"Dependency '{args['name']}': {status.phase.value}"
            }],
            "ready": ready,
            "status": status.phase.value
        }
    
    @tool("request_parent_decision", "Request a decision from parent (blocks until response)", {
        "question": str,
        "context": dict
    })
    async def request_parent_decision(args: dict) -> dict:
        caller = args.get("_caller_spec", "unknown")
        caller_status = STATE.get_spec_status(caller)
        
        if not caller_status or not caller_status.parent:
            return {
                "content": [{
                    "type": "text",
                    "text": "Error: No parent to request decision from"
                }],
                "error": True
            }
        
        # Send blocking message to parent
        msg_id = f"msg-{STATE.message_counter:04d}"
        STATE.message_counter += 1
        
        msg = Message(
            id=msg_id,
            from_spec=caller,
            to_spec=caller_status.parent,
            type="decision_request",
            payload={
                "question": args["question"],
                "context": args["context"]
            },
            priority=Priority.BLOCKING,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        STATE.add_message(msg)
        
        # Create future for response
        future = asyncio.get_event_loop().create_future()
        STATE.pending_responses[msg_id] = future
        
        # Signal hibernation with trigger being the response
        return {
            "content": [{
                "type": "text",
                "text": f"Decision requested from parent. Request ID: {msg_id}. Hibernating until response..."
            }],
            "_hibernation_request": {
                "resume_trigger": f"message_response:{msg_id}",
                "state": {},
                "instructions": f"Waiting for parent decision on: {args['question']}"
            }
        }
    
    @tool("get_my_messages", "Get pending messages for this spec", {})
    async def get_my_messages(args: dict) -> dict:
        caller = args.get("_caller_spec", "unknown")
        messages = STATE.get_pending_messages(caller)
        
        return {
            "content": [{
                "type": "text",
                "text": json.dumps([{
                    "id": m.id,
                    "from": m.from_spec,
                    "type": m.type,
                    "payload": m.payload,
                    "priority": m.priority.value
                } for m in messages], indent=2)
            }],
            "messages": messages
        }
    
    @tool("respond_to_message", "Respond to a message (for decision requests)", {
        "message_id": str,
        "response": dict
    })
    async def respond_to_message(args: dict) -> dict:
        msg_id = args["message_id"]
        
        # Find the message and add response
        for msgs in STATE.messages.values():
            for m in msgs:
                if m.id == msg_id:
                    m.response = args["response"]
                    m.status = "processed"
                    
                    # Resolve the future if exists
                    if msg_id in STATE.pending_responses:
                        STATE.pending_responses[msg_id].set_result(args["response"])
                    
                    return {
                        "content": [{
                            "type": "text",
                            "text": f"Response sent for {msg_id}"
                        }]
                    }
        
        return {
            "content": [{
                "type": "text",
                "text": f"Message {msg_id} not found"
            }],
            "error": True
        }
    
    # Create the server
    server = create_sdk_mcp_server(
        name="orchestrator",
        version="1.0.0",
        tools=[
            send_message,
            hibernate,
            signal_complete,
            check_dependency,
            request_parent_decision,
            get_my_messages,
            respond_to_message
        ]
    )
    
    return server


# =============================================================================
# LOGGING
# =============================================================================

def log(msg: str, level: str = "INFO", spec: str = "", depth: int = 0):
    timestamp = datetime.now().strftime("%H:%M:%S")
    indent = "  " * depth
    prefix = {
        "INFO": "->",
        "WARN": "!",
        "ERROR": "X",
        "SUCCESS": "*",
        "SPAWN": "+",
        "HIBERNATE": "zzz",
        "WAKE": "^",
        "COMPLETE": "OK",
        "RESEARCH": "?",
        "ARCH": "#",
        "IMPL": ">",
        "VERIFY": "v",
        "INTEGRATE": "&",
        "BLOCKED": "!X",
    }.get(level, "-")
    
    spec_str = f"[{spec}] " if spec else ""
    print(f"{timestamp} {indent}{prefix} {spec_str}{msg}")


# =============================================================================
# AGENT PROMPTS & CONTEXT
# =============================================================================

def load_agent_prompt(agent_type: str) -> str:
    """Load system prompt for an agent type."""
    agent_file = Path(__file__).parent.parent / "agents" / f"{agent_type}.md"
    if agent_file.exists():
        return agent_file.read_text(encoding='utf-8')
    
    # Fallback prompts
    fallbacks = {
        "researcher": """You are a Researcher agent. Your job is to research libraries, patterns, and best practices for implementing a spec. Output a research.json file with your findings.""",
        "proposer": """You are a Proposer agent (architect). Analyze the spec and propose a structure (is_leaf, children, classes, interfaces). Output your proposal as JSON.""",
        "critic": """You are a Critic agent. Review the proposal and either approve it or provide specific critiques. Output {"approved": true/false, "critiques": [...]}""",
        "implementer": """You are an Implementer agent. Write the code to satisfy the spec. Use the research.json if available. Follow the style guide.""",
        "verifier": """You are a Verifier agent. Run tests and report structured results as JSON with verdict: pass/fail_compilation/fail_tests.""",
    }
    
    return fallbacks.get(agent_type, f"You are a {agent_type} agent.")


def load_style_guide() -> str:
    """Load STYLE.md if it exists."""
    for p in [Path.cwd(), Path.cwd().parent, Path.cwd().parent.parent]:
        style = p / "STYLE.md"
        if style.exists():
            return style.read_text(encoding='utf-8')
    return ""


def build_agent_context(
    agent_type: str,
    spec: Spec,
    extra: dict = None
) -> str:
    """Build user prompt for an agent."""
    extra = extra or {}
    
    spec_json = json.dumps(spec_to_dict(spec), indent=2)
    spec_dir = spec.path.parent if spec.path else Path.cwd()
    
    ctx = f"""# Task Context

**Spec:** {spec.name}
**Directory:** {spec_dir}
**Type:** {"Leaf" if spec.is_leaf else "Non-leaf" if spec.is_leaf is False else "Undecided"}
**Status:** {spec.status}
**Depth:** {spec.depth}

## spec.json

```json
{spec_json}
```
"""
    
    # Add hibernation context if waking up
    if "hibernation_context" in extra:
        hib = extra["hibernation_context"]
        ctx += f"""
## Restored Context (You were hibernating)

**Phase when hibernated:** {hib.phase.value}
**Resume trigger:** {hib.resume_trigger}
**Instructions:** {hib.instructions}

**Preserved state:**
```json
{json.dumps(hib.state, indent=2)}
```
"""
    
    # Add wake messages
    if "wake_messages" in extra:
        ctx += "\n## Messages That Woke You\n\n"
        for msg in extra["wake_messages"]:
            ctx += f"- **{msg.type}** from `{msg.from_spec}` (priority: {msg.priority.value}):\n"
            ctx += f"  ```json\n  {json.dumps(msg.payload, indent=2)}\n  ```\n"
    
    # Add research for implementer
    if agent_type == "implementer":
        research_path = spec_dir / "research.json"
        if research_path.exists():
            ctx += f"\n## Research Brief\n\n```json\n{research_path.read_text(encoding='utf-8')}\n```\n"
    
    # Add style guide
    if agent_type in ["researcher", "proposer", "critic", "implementer"]:
        style = load_style_guide()
        if style:
            ctx += f"\n## Project Style Guide\n\n{style}\n"
    
    # Add errors for implementer
    if agent_type == "implementer" and spec.errors:
        ctx += f"\n## Previous Errors (Iteration {spec.errors.iteration})\n"
        if spec.errors.compilation_errors:
            ctx += "Compilation:\n```\n" + "\n".join(spec.errors.compilation_errors) + "\n```\n"
        if spec.errors.test_failures:
            ctx += "Test failures:\n"
            for f in spec.errors.test_failures:
                ctx += f"- {f.get('test_name')}: {f.get('message')}\n"
    
    # Add proposal for critic
    if "proposal" in extra:
        ctx += f"\n## Proposal to Review\n\n```json\n{json.dumps(extra['proposal'], indent=2)}\n```\n"
    
    # Add critique for proposer
    if "critique" in extra:
        ctx += f"\n## Previous Critique to Address\n\n```json\n{json.dumps(extra['critique'], indent=2)}\n```\n"
    
    # Add children status for integration
    if "children_status" in extra:
        ctx += "\n## Children Status\n\n"
        for name, status in extra["children_status"].items():
            ctx += f"- **{name}**: {status}\n"
    
    ctx += f"\n---\n\nProceed with your role as {agent_type}. Output structured JSON where applicable.\n"
    
    return ctx


# =============================================================================
# AGENT TOOLS
# =============================================================================

AGENT_TOOLS = {
    "researcher": ["Read", "Glob", "WebSearch", "WebFetch", "Write"],
    "proposer": ["Read", "Glob", "Bash", "Write"],
    "critic": ["Read", "Glob", "Bash"],
    "implementer": ["Read", "Write", "Edit", "Bash", "Glob"],
    "verifier": ["Read", "Bash", "Glob"],
}

MCP_TOOL_NAMES = [
    "mcp__orchestrator__send_message",
    "mcp__orchestrator__hibernate",
    "mcp__orchestrator__signal_complete",
    "mcp__orchestrator__check_dependency",
    "mcp__orchestrator__request_parent_decision",
    "mcp__orchestrator__get_my_messages",
    "mcp__orchestrator__respond_to_message",
]


# =============================================================================
# AGENT SPAWNING
# =============================================================================

def extract_json_blocks(text: str) -> list[dict]:
    """Extract JSON blocks from agent response."""
    blocks = []
    for match in re.findall(r'```json\s*([\s\S]*?)\s*```', text):
        try:
            blocks.append(json.loads(match))
        except:
            continue
    return blocks


async def spawn_agent(
    agent_type: str,
    spec: Spec,
    mcp_server,
    extra_context: dict = None
) -> dict:
    """
    Spawn an agent and return its result.
    
    Returns:
        {
            "success": bool,
            "response": str,
            "json_blocks": list[dict],
            "hibernation_request": optional dict,
            "completion_signal": optional dict,
        }
    """
    extra_context = extra_context or {}
    
    if STATE.agents_spawned >= CONFIG.max_total_agents:
        return {"success": False, "error": "Max agents exceeded"}
    
    STATE.agents_spawned += 1
    log(f"Spawning {agent_type} (#{STATE.agents_spawned})", "SPAWN", spec.name, spec.depth)
    
    # Update spec status
    status = STATE.get_spec_status(spec.name)
    if status:
        status.current_agent = agent_type
    
    # === DRY RUN ===
    if CONFIG.dry_run:
        log(f"[DRY RUN] Would run {agent_type}", "INFO", spec.name, spec.depth)
        return {"success": True, "response": "", "json_blocks": [], "dry_run": True}
    
    # === SIMULATED ===
    if not CONFIG.live:
        log(f"[SIMULATED] {agent_type} completed", "INFO", spec.name, spec.depth)
        return {"success": True, "response": "", "json_blocks": [], "simulated": True}
    
    # === LIVE ===
    try:
        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, AssistantMessage, TextBlock, ToolResultBlock, ResultMessage
    except ImportError:
        return {"success": False, "error": "pip install claude-agent-sdk"}
    
    spec_dir = spec.path.parent if spec.path else Path.cwd()
    
    system_prompt = load_agent_prompt(agent_type)
    user_prompt = build_agent_context(agent_type, spec, extra_context)
    
    # Inject caller spec into tool calls
    user_prompt += f"\n\n[SYSTEM: Your spec name for MCP calls is '{spec.name}']\n"
    
    tools = AGENT_TOOLS.get(agent_type, ["Read"]) + MCP_TOOL_NAMES
    
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        allowed_tools=tools,
        mcp_servers={"orchestrator": mcp_server},
        permission_mode="bypassPermissions",
        cwd=str(spec_dir),
        setting_sources=["project"],
        model=CONFIG.model,
    )
    
    result = {
        "success": False,
        "response": "",
        "json_blocks": [],
        "hibernation_request": None,
        "completion_signal": None,
    }
    
    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(user_prompt)
            
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            result["response"] += block.text
                        elif hasattr(block, 'input'):
                            # Tool use - check for special signals
                            pass
                
                elif isinstance(message, ToolResultBlock):
                    # Check for hibernation/completion signals in tool results
                    if hasattr(message, 'content'):
                        try:
                            content = json.loads(message.content) if isinstance(message.content, str) else message.content
                            if isinstance(content, dict):
                                if "_hibernation_request" in content:
                                    result["hibernation_request"] = content["_hibernation_request"]
                                if "_completion_signal" in content:
                                    result["completion_signal"] = content["_completion_signal"]
                        except:
                            pass
                
                elif isinstance(message, ResultMessage):
                    result["success"] = not message.is_error
        
        result["json_blocks"] = extract_json_blocks(result["response"])
        
    except Exception as e:
        log(f"Agent error: {e}", "ERROR", spec.name, spec.depth)
        result["error"] = str(e)
        traceback.print_exc()
    
    if status:
        status.current_agent = None
    
    return result


# =============================================================================
# SPEC PROCESSING
# =============================================================================

async def run_researcher(spec: Spec, mcp_server) -> bool:
    """Run researcher to gather context before implementation."""
    log("Running researcher", "RESEARCH", spec.name, spec.depth)
    
    status = STATE.get_spec_status(spec.name)
    if status:
        status.phase = Phase.RESEARCH
    
    result = await spawn_agent("researcher", spec, mcp_server)
    
    if not result.get("success"):
        log(f"Researcher failed: {result.get('error')}", "ERROR", spec.name, spec.depth)
        return False
    
    # Check for research output
    spec_dir = spec.path.parent if spec.path else Path.cwd()
    research_path = spec_dir / "research.json"
    
    # In live mode, researcher should have written research.json
    # In simulated mode, create a stub
    if not CONFIG.live and not research_path.exists():
        research_path.write_text(json.dumps({
            "spec_name": spec.name,
            "researched_at": datetime.now(timezone.utc).isoformat(),
            "topics": [],
            "recommendations": ["[Simulated research]"]
        }, indent=2), encoding='utf-8')
    
    log("Research complete", "SUCCESS", spec.name, spec.depth)
    return True


async def run_architecture_loop(spec: Spec, mcp_server) -> tuple[bool, Optional[dict]]:
    """Run Proposer <-> Critic loop."""
    log("Starting architecture loop", "ARCH", spec.name, spec.depth)
    
    status = STATE.get_spec_status(spec.name)
    if status:
        status.phase = Phase.ARCHITECTURE
    
    proposal = None
    critique = None
    
    for iteration in range(1, CONFIG.max_arch_iterations + 1):
        log(f"Architecture iteration {iteration}/{CONFIG.max_arch_iterations}", "ARCH", spec.name, spec.depth)
        
        # Proposer
        extra = {}
        if critique:
            extra["critique"] = critique
        
        result = await spawn_agent("proposer", spec, mcp_server, extra)
        if not result.get("success"):
            return False, None
        
        # Extract proposal
        for block in result.get("json_blocks", []):
            if "structure" in block or "is_leaf" in block:
                proposal = block
                break
        
        if not proposal and (CONFIG.dry_run or not CONFIG.live):
            proposal = {"structure": {"is_leaf": True}, "rationale": "Simulated"}
        
        if not proposal:
            log("No proposal extracted", "WARN", spec.name, spec.depth)
            continue
        
        # Critic
        result = await spawn_agent("critic", spec, mcp_server, {"proposal": proposal})
        if not result.get("success"):
            return False, None
        
        # Extract critique
        for block in result.get("json_blocks", []):
            if "approved" in block:
                critique = block
                break
        
        if not critique and (CONFIG.dry_run or not CONFIG.live):
            critique = {"approved": iteration >= 2, "critiques": []}
        
        if critique and critique.get("approved"):
            log("Architecture approved", "SUCCESS", spec.name, spec.depth)
            return True, proposal
    
    log("Architecture loop exhausted", "WARN", spec.name, spec.depth)
    return True, proposal


async def run_implementation_loop(spec: Spec, mcp_server) -> bool:
    """Run Implementer <-> Verifier loop."""
    log("Starting implementation loop", "IMPL", spec.name, spec.depth)
    
    status = STATE.get_spec_status(spec.name)
    
    while spec.ralph_iteration < CONFIG.max_iterations:
        spec.ralph_iteration += 1
        log(f"Implementation iteration {spec.ralph_iteration}/{CONFIG.max_iterations}", "IMPL", spec.name, spec.depth)
        
        if status:
            status.phase = Phase.IMPLEMENTATION
            status.iteration = spec.ralph_iteration
        
        # Implementer
        result = await spawn_agent("implementer", spec, mcp_server)
        
        # Check for hibernation
        if result.get("hibernation_request"):
            log("Implementer hibernating", "HIBERNATE", spec.name, spec.depth)
            ctx = HibernationContext(
                spec_name=spec.name,
                agent_type="implementer",
                phase=Phase.IMPLEMENTATION,
                state=result["hibernation_request"]["state"],
                resume_trigger=result["hibernation_request"]["resume_trigger"],
                instructions=result["hibernation_request"]["instructions"],
                exported_at=datetime.now(timezone.utc).isoformat()
            )
            STATE.hibernate_agent(ctx)
            return True  # Successfully hibernated, not failed
        
        if not result.get("success"):
            return False
        
        # Verifier
        if status:
            status.phase = Phase.VERIFICATION
        
        result = await spawn_agent("verifier", spec, mcp_server)
        if not result.get("success"):
            return False
        
        # Parse verification result
        verification = None
        for block in result.get("json_blocks", []):
            if "verdict" in block:
                verification = block
                break
        
        # Check for pass
        if verification and verification.get("verdict") == "pass":
            spec.all_tests_passed = True
            spec.status = "complete"
            save_spec(spec)
            log("All tests passed!", "SUCCESS", spec.name, spec.depth)
            return True
        
        # Simulated success
        if (CONFIG.dry_run or not CONFIG.live) and spec.ralph_iteration >= 2:
            spec.all_tests_passed = True
            spec.status = "complete"
            save_spec(spec)
            log("Tests passed (simulated)", "SUCCESS", spec.name, spec.depth)
            return True
        
        # Apply errors
        if verification:
            spec.errors = Errors(
                iteration=spec.ralph_iteration,
                timestamp=datetime.now(timezone.utc).isoformat(),
                compilation_success=verification.get("compilation", {}).get("success", True),
                compilation_errors=[e.get("message", str(e)) for e in verification.get("compilation", {}).get("errors", [])],
                test_failures=verification.get("tests", {}).get("failures", [])
            )
        
        save_spec(spec)
    
    log("Max iterations reached", "ERROR", spec.name, spec.depth)
    return False


async def run_integration_tests(spec: Spec, mcp_server) -> bool:
    """Run integration tests after all children complete."""
    log("Running integration tests", "INTEGRATE", spec.name, spec.depth)
    
    status = STATE.get_spec_status(spec.name)
    if status:
        status.phase = Phase.INTEGRATION
    
    # Gather children status
    children_status = {}
    for child_name in (status.children if status else []):
        child_status = STATE.get_spec_status(child_name)
        children_status[child_name] = child_status.phase.value if child_status else "unknown"
    
    result = await spawn_agent("verifier", spec, mcp_server, {
        "mode": "integration",
        "children_status": children_status
    })
    
    if not result.get("success"):
        return False
    
    # Parse result
    for block in result.get("json_blocks", []):
        if "verdict" in block:
            if block["verdict"] == "pass":
                spec.integration_tests_passed = True
                log("Integration tests passed", "SUCCESS", spec.name, spec.depth)
                return True
            else:
                log(f"Integration tests failed: {block.get('summary', 'unknown')}", "ERROR", spec.name, spec.depth)
                STATE.flag_for_review(spec.name, "integration_failed", block)
                return False
    
    # Simulated success
    if CONFIG.dry_run or not CONFIG.live:
        spec.integration_tests_passed = True
        log("Integration tests passed (simulated)", "SUCCESS", spec.name, spec.depth)
        return True
    
    return False


def apply_proposal_to_spec(spec: Spec, proposal: dict):
    """Apply architecture proposal to spec."""
    if not proposal:
        return
    
    struct = proposal.get("structure", proposal)
    
    if "is_leaf" in struct:
        spec.is_leaf = struct["is_leaf"]
    
    if "children" in struct:
        spec.children = [
            Child(**c) if isinstance(c, dict) else c
            for c in struct["children"]
        ]
    
    if "classes" in struct:
        spec.classes = [
            ClassDef(**c) if isinstance(c, dict) else c
            for c in struct["classes"]
        ]
    
    if "shared_types" in proposal.get("interfaces", {}):
        spec.shared_types = [
            SharedType(**s) if isinstance(s, dict) else s
            for s in proposal["interfaces"]["shared_types"]
        ]


def scaffold_children(spec: Spec) -> list[str]:
    """Create child spec directories."""
    if not spec.path:
        return []
    
    children_dir = spec.path.parent / "children"
    children_dir.mkdir(exist_ok=True)
    created = []
    
    # Shared types
    if spec.shared_types:
        shared_dir = children_dir / "shared"
        shared_dir.mkdir(exist_ok=True)
        shared_path = shared_dir / "spec.json"
        if not shared_path.exists():
            shared_spec = create_shared_spec(spec, shared_path)
            save_spec(shared_spec, shared_path)
            created.append("shared")
            log("Created shared/", "INFO", spec.name, spec.depth)
    
    # Children
    for child_def in spec.children:
        child_dir = children_dir / child_def.name
        child_dir.mkdir(exist_ok=True)
        child_path = child_dir / "spec.json"
        if not child_path.exists():
            child_spec = create_child_spec(spec, child_def, child_path)
            if spec.shared_types and "shared" not in child_spec.depends_on:
                child_spec.depends_on.insert(0, "shared")
            save_spec(child_spec, child_path)
            created.append(child_def.name)
            log(f"Created {child_def.name}/", "INFO", spec.name, spec.depth)
    
    return created


# =============================================================================
# MAIN PROCESSING LOGIC
# =============================================================================

async def process_leaf(spec_path: Path, mcp_server, depth: int) -> bool:
    """Process a leaf spec: Research -> Implement -> Verify"""
    spec = load_spec(spec_path)
    spec.depth = depth
    spec.status = "in_progress"
    save_spec(spec)
    
    status = SpecStatus(
        name=spec.name,
        path=spec_path,
        phase=Phase.PENDING,
        depth=depth,
        depends_on=spec.depends_on
    )
    STATE.set_spec_status(spec.name, status)
    
    # Research first
    if not await run_researcher(spec, mcp_server):
        status.phase = Phase.FAILED
        return False
    
    # Implementation loop
    success = await run_implementation_loop(spec, mcp_server)
    
    # Check if hibernated vs completed
    if STATE.is_hibernating(spec.name):
        return True  # Will resume later
    
    spec = load_spec(spec_path)
    
    if success:
        status.phase = Phase.COMPLETE
        spec.status = "complete"
    else:
        status.phase = Phase.FAILED
        spec.status = "failed"
        STATE.flag_for_review(spec.name, "implementation_failed", {
            "iterations": spec.ralph_iteration,
            "errors": spec.errors.__dict__ if spec.errors else None
        })
    
    save_spec(spec)
    
    # Notify parent if we have one
    if status.parent:
        msg = Message(
            id=f"msg-{STATE.message_counter:04d}",
            from_spec=spec.name,
            to_spec=status.parent,
            type="child_complete",
            payload={"child": spec.name, "success": success},
            priority=Priority.NORMAL,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        STATE.message_counter += 1
        STATE.add_message(msg)
    
    return success


async def process_non_leaf(spec_path: Path, mcp_server, depth: int) -> bool:
    """Process a non-leaf spec: Architecture -> Scaffold -> Wait for children -> Integrate"""
    spec = load_spec(spec_path)
    spec.depth = depth
    spec.status = "in_progress"
    save_spec(spec)
    
    status = SpecStatus(
        name=spec.name,
        path=spec_path,
        phase=Phase.PENDING,
        depth=depth,
        depends_on=spec.depends_on
    )
    STATE.set_spec_status(spec.name, status)
    
    # Check for existing hibernation
    if STATE.is_hibernating(spec.name):
        ctx = STATE.wake_agent(spec.name)
        log(f"Waking from hibernation", "WAKE", spec.name, depth)
        
        # Get wake messages
        wake_msgs = STATE.get_pending_messages(spec.name)
        
        # Process based on phase
        if ctx.phase == Phase.ARCHITECTURE:
            # Continue architecture somehow? Usually shouldn't happen
            pass
        
        # If waiting for children, check if all done
        if STATE.all_children_complete(spec.name):
            return await finalize_non_leaf(spec, mcp_server, status)
    
    # Architecture if needed
    if spec.is_leaf is None:
        success, proposal = await run_architecture_loop(spec, mcp_server)
        if not success:
            status.phase = Phase.FAILED
            return False
        
        apply_proposal_to_spec(spec, proposal)
        save_spec(spec)
        spec = load_spec(spec_path)
        
        # Did architecture decide this is actually a leaf?
        if spec.is_leaf is True:
            return await process_leaf(spec_path, mcp_server, depth)
    
    # Scaffold children
    created = scaffold_children(spec)
    status.children = created
    
    # Register children in state with parent linkage
    children_dir = spec_path.parent / "children"
    for child_name in created:
        child_path = children_dir / child_name / "spec.json"
        if child_path.exists():
            child_spec = load_spec(child_path)
            child_status = SpecStatus(
                name=child_name,
                path=child_path,
                phase=Phase.PENDING,
                depth=depth + 1,
                parent=spec.name,
                depends_on=child_spec.depends_on
            )
            STATE.set_spec_status(child_name, child_status)
    
    log(f"Scaffolded {len(created)} children, hibernating", "HIBERNATE", spec.name, depth)
    
    # Hibernate
    ctx = HibernationContext(
        spec_name=spec.name,
        agent_type="coordinator",
        phase=Phase.PENDING,
        state={"children": created},
        resume_trigger="all_children_complete",
        instructions="Check if all children complete, then run integration",
        exported_at=datetime.now(timezone.utc).isoformat()
    )
    STATE.hibernate_agent(ctx)
    
    return True  # Successfully setup, children will be processed by main loop


async def finalize_non_leaf(spec: Spec, mcp_server, status: SpecStatus) -> bool:
    """Run integration tests and finalize a non-leaf after all children complete."""
    log("All children complete, running integration", "INTEGRATE", spec.name, spec.depth)
    
    success = await run_integration_tests(spec, mcp_server)
    
    if success:
        status.phase = Phase.COMPLETE
        spec.status = "complete"
        spec.integration_tests_passed = True
    else:
        status.phase = Phase.BLOCKED
        spec.status = "blocked"
        STATE.flag_for_review(spec.name, "integration_failed", {})
    
    save_spec(spec)
    
    # Notify parent
    if status.parent:
        msg = Message(
            id=f"msg-{STATE.message_counter:04d}",
            from_spec=spec.name,
            to_spec=status.parent,
            type="child_complete",
            payload={"child": spec.name, "success": success},
            priority=Priority.NORMAL,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        STATE.message_counter += 1
        STATE.add_message(msg)
    
    return success


async def process_spec(spec_path: Path, mcp_server, depth: int = 0) -> bool:
    """Determine spec type and process accordingly."""
    spec = load_spec(spec_path)
    
    if spec.is_leaf is True:
        return await process_leaf(spec_path, mcp_server, depth)
    elif spec.is_leaf is False:
        return await process_non_leaf(spec_path, mcp_server, depth)
    else:
        # Undecided - run architecture
        return await process_non_leaf(spec_path, mcp_server, depth)


# =============================================================================
# MAIN ORCHESTRATOR LOOP
# =============================================================================

async def orchestrator_main(root_spec_path: Path):
    """
    Main orchestration loop.
    
    1. Initialize root spec
    2. Process specs in parallel (respecting dependencies)
    3. Handle hibernation/wake cycles
    4. Trigger integration when siblings complete
    5. Continue until all complete or blocked
    """
    log(f"Starting orchestrator for {root_spec_path}", "INFO")
    
    # Create MCP server
    mcp_server = create_mcp_tools()
    
    # Initialize root
    root_spec = load_spec(root_spec_path)
    root_status = SpecStatus(
        name=root_spec.name,
        path=root_spec_path,
        phase=Phase.PENDING,
        depth=0
    )
    STATE.set_spec_status(root_spec.name, root_status)
    
    # Start processing root
    await process_spec(root_spec_path, mcp_server, depth=0)
    
    # Main loop
    iteration = 0
    max_iterations = 1000  # Safety limit
    
    while iteration < max_iterations:
        iteration += 1
        
        # Check for completion
        root_status = STATE.get_spec_status(root_spec.name)
        if root_status and root_status.phase in [Phase.COMPLETE, Phase.FAILED, Phase.BLOCKED]:
            log(f"Root spec reached terminal state: {root_status.phase.value}", "INFO")
            break
        
        # Get ready specs
        ready = STATE.get_ready_specs()
        
        if not ready:
            # Check for hibernating specs that can be woken
            for name, ctx in list(STATE.hibernating.items()):
                if ctx.resume_trigger == "all_children_complete":
                    if STATE.all_children_complete(name):
                        status = STATE.get_spec_status(name)
                        if status:
                            spec = load_spec(status.path)
                            STATE.wake_agent(name)
                            await finalize_non_leaf(spec, mcp_server, status)
                            break
            else:
                # Nothing to do, check if stuck
                if not STATE.active_tasks and not STATE.hibernating:
                    log("No work remaining and nothing hibernating", "WARN")
                    break
                
                # Wait a bit
                await asyncio.sleep(0.1)
                continue
        
        # Process ready specs in parallel (up to limit)
        batch = ready[:CONFIG.max_concurrent_agents - len(STATE.active_tasks)]
        
        if batch:
            tasks = []
            for name in batch:
                status = STATE.get_spec_status(name)
                if status and status.path:
                    task = asyncio.create_task(
                        process_spec(status.path, mcp_server, status.depth)
                    )
                    STATE.active_tasks[name] = task
                    tasks.append((name, task))
            
            # Wait for at least one to complete
            if tasks:
                done, pending = await asyncio.wait(
                    [t for _, t in tasks],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                # Clean up completed tasks
                for name, task in tasks:
                    if task in done:
                        del STATE.active_tasks[name]
                        try:
                            result = task.result()
                            if not result:
                                status = STATE.get_spec_status(name)
                                if status:
                                    status.phase = Phase.FAILED
                        except Exception as e:
                            log(f"Task failed: {e}", "ERROR", name)
                            status = STATE.get_spec_status(name)
                            if status:
                                status.phase = Phase.FAILED
    
    # Final status
    log("=" * 60, "INFO")
    log("ORCHESTRATION COMPLETE", "COMPLETE")
    log(f"Agents spawned: {STATE.agents_spawned}", "INFO")
    log(f"Specs processed: {len(STATE.specs)}", "INFO")
    
    complete = [n for n, s in STATE.specs.items() if s.phase == Phase.COMPLETE]
    failed = [n for n, s in STATE.specs.items() if s.phase == Phase.FAILED]
    blocked = [n for n, s in STATE.specs.items() if s.phase == Phase.BLOCKED]
    
    log(f"Complete: {len(complete)}", "SUCCESS")
    if failed:
        log(f"Failed: {failed}", "ERROR")
    if blocked:
        log(f"Blocked (needs review): {blocked}", "BLOCKED")
    
    if STATE.needs_review:
        log(f"Items flagged for human review: {len(STATE.needs_review)}", "WARN")
        for item in STATE.needs_review:
            log(f"  - {item['spec']}: {item['reason']}", "WARN")
    
    return len(failed) == 0 and len(blocked) == 0


# =============================================================================
# STATUS ENDPOINT (for user-facing Claude)
# =============================================================================

def get_status_dict() -> dict:
    """Get current orchestrator status as a dict."""
    return {
        "agents_spawned": STATE.agents_spawned,
        "specs": {
            name: {
                "phase": s.phase.value,
                "depth": s.depth,
                "current_agent": s.current_agent,
                "iteration": s.iteration,
                "children": s.children,
            }
            for name, s in STATE.specs.items()
        },
        "active_tasks": list(STATE.active_tasks.keys()),
        "hibernating": list(STATE.hibernating.keys()),
        "needs_review": STATE.needs_review,
        "summary": {
            "total": len(STATE.specs),
            "complete": len([s for s in STATE.specs.values() if s.phase == Phase.COMPLETE]),
            "in_progress": len([s for s in STATE.specs.values() if s.phase not in [Phase.COMPLETE, Phase.FAILED, Phase.BLOCKED, Phase.PENDING]]),
            "failed": len([s for s in STATE.specs.values() if s.phase == Phase.FAILED]),
            "blocked": len([s for s in STATE.specs.values() if s.phase == Phase.BLOCKED]),
        }
    }


async def status_server(port: int = 8765):
    """Simple HTTP server for status queries."""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import threading
    
    class StatusHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/status":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(get_status_dict(), indent=2).encode())
            else:
                self.send_response(404)
                self.end_headers()
        
        def log_message(self, format, *args):
            pass  # Suppress logging
    
    server = HTTPServer(("localhost", port), StatusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log(f"Status server running on http://localhost:{port}/status", "INFO")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Ralph Orchestrator v4")
    parser.add_argument("--spec", required=True, help="Path to root spec.json")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without executing")
    parser.add_argument("--live", action="store_true", help="Actually call Agent SDK")
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--max-arch-iterations", type=int, default=5)
    parser.add_argument("--max-agents", type=int, default=100)
    parser.add_argument("--max-concurrent", type=int, default=5)
    parser.add_argument("--model", default="claude-opus-4-5-20251101")
    parser.add_argument("--status-port", type=int, default=0, help="Port for status server (0=disabled)")
    
    args = parser.parse_args()
    
    CONFIG.max_depth = args.max_depth
    CONFIG.max_iterations = args.max_iterations
    CONFIG.max_arch_iterations = args.max_arch_iterations
    CONFIG.max_total_agents = args.max_agents
    CONFIG.max_concurrent_agents = args.max_concurrent
    CONFIG.dry_run = args.dry_run
    CONFIG.live = args.live
    CONFIG.model = args.model
    
    spec_path = Path(args.spec)
    if not spec_path.exists():
        print(f"ERROR: Spec not found: {spec_path}")
        sys.exit(1)
    
    mode = "DRY RUN" if CONFIG.dry_run else ("LIVE" if CONFIG.live else "SIMULATED")
    
    print("=" * 60)
    print(f"RALPH ORCHESTRATOR v4 [{mode}]")
    print("=" * 60)
    print(f"Root Spec:       {spec_path}")
    print(f"Max Depth:       {CONFIG.max_depth}")
    print(f"Max Concurrent:  {CONFIG.max_concurrent_agents}")
    print(f"Max Agents:      {CONFIG.max_total_agents}")
    print(f"Model:           {CONFIG.model}")
    print("=" * 60)
    
    async def run():
        if args.status_port > 0:
            await status_server(args.status_port)
        
        return await orchestrator_main(spec_path)
    
    try:
        success = asyncio.run(run())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(130)
    except Exception as e:
        print(f"\nFATAL: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
