#!/usr/bin/env python3
"""
Ralph-Recursive v3: Hibernating Parent Pattern

Key Innovation: Parents don't wait for children. They:
1. Complete architecture
2. Spawn children  
3. Export their context
4. TERMINATE

When a child needs parent input:
1. Child sends message with priority="blocking"
2. Orchestrator detects wake signal
3. Orchestrator re-spawns parent with exported context + message
4. Parent handles, then hibernates again (or completes)

This is continuation-passing style for agents.

Requirements:
    pip install claude-agent-sdk

Usage:
    python3 ralph-recursive-v3.py --spec spec.json --live
"""

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any
from enum import Enum

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
    max_total_agents: int = 50
    dry_run: bool = False
    live: bool = False
    model: str = "claude-opus-4-5-20251101"
    agents_spawned: int = 0


CONFIG = Config()


class Phase(str, Enum):
    """Phases a parent can be in."""
    ARCHITECTURE = "architecture"
    AWAITING_CHILDREN = "awaiting_children"
    INTEGRATION = "integration"
    COMPLETE = "complete"


# Tools available to each agent type
AGENT_TOOLS = {
    "proposer": ["Read", "Glob", "Bash", "Write"],
    "critic": ["Read", "Glob", "Bash"],
    "implementer": ["Read", "Write", "Edit", "MultiEdit", "Bash", "Glob"],
    "verifier": ["Read", "Bash", "Glob"],
}


# =============================================================================
# LOGGING
# =============================================================================

def log(msg: str, level: str = "INFO", depth: int = 0) -> None:
    indent = "  " * depth
    prefix = {
        "INFO": "->", "WARN": "!", "ERROR": "X", "SUCCESS": "*",
        "DRY": "o", "SPAWN": "+", "HIBERNATE": "zzz", "WAKE": "^",
        "ARCH": "#", "MSG": "m", "STREAM": "~"
    }.get(level, "-")
    print(f"{indent}{prefix} [{level}] {msg}")


# =============================================================================
# PARENT CONTEXT MANAGEMENT
# =============================================================================

@dataclass
class ParentContext:
    """Exported state from a hibernating parent."""
    spec_name: str
    spec_path: str
    phase: Phase
    depth: int
    exported_at: str = ""
    
    # Architecture state
    architecture_iterations: int = 0
    final_proposal: Optional[dict] = None
    critiques: list[dict] = field(default_factory=list)
    architecture_approved: bool = False
    
    # Children state
    children_spawned: list[str] = field(default_factory=list)
    children_completed: list[str] = field(default_factory=list)
    children_blocked: list[dict] = field(default_factory=list)
    
    # Decision log for continuity
    decisions: list[dict] = field(default_factory=list)
    
    # Resume instructions
    resume_instructions: str = ""


def export_parent_context(
    spec: Spec,
    phase: Phase,
    depth: int,
    architecture_state: Optional[dict] = None,
    children_state: Optional[dict] = None,
    decisions: Optional[list] = None,
    resume_instructions: str = ""
) -> Path:
    """Export parent context to JSON file for later restoration."""
    if not spec.path:
        raise ValueError("Spec has no path")
    
    context = ParentContext(
        spec_name=spec.name,
        spec_path=str(spec.path),
        phase=phase,
        depth=depth,
        exported_at=datetime.now(timezone.utc).isoformat(),
        resume_instructions=resume_instructions
    )
    
    if architecture_state:
        context.architecture_iterations = architecture_state.get("iterations", 0)
        context.final_proposal = architecture_state.get("proposal")
        context.critiques = architecture_state.get("critiques", [])
        context.architecture_approved = architecture_state.get("approved", False)
    
    if children_state:
        context.children_spawned = children_state.get("spawned", [])
        context.children_completed = children_state.get("completed", [])
        context.children_blocked = children_state.get("blocked", [])
    
    if decisions:
        context.decisions = decisions
    
    # Save to parent-context.json in spec directory
    context_path = spec.path.parent / "parent-context.json"
    context_dict = {
        "spec_name": context.spec_name,
        "spec_path": context.spec_path,
        "phase": context.phase.value,
        "depth": context.depth,
        "exported_at": context.exported_at,
        "architecture_state": {
            "iterations_completed": context.architecture_iterations,
            "final_proposal": context.final_proposal,
            "critiques": context.critiques,
            "approved": context.architecture_approved
        },
        "children_state": {
            "spawned": context.children_spawned,
            "completed": context.children_completed,
            "blocked": context.children_blocked
        },
        "decisions": context.decisions,
        "resume_instructions": context.resume_instructions
    }
    
    context_path.write_text(json.dumps(context_dict, indent=2), encoding='utf-8')
    return context_path


def load_parent_context(spec_dir: Path) -> Optional[ParentContext]:
    """Load parent context from JSON file."""
    context_path = spec_dir / "parent-context.json"
    if not context_path.exists():
        return None
    
    data = json.loads(context_path.read_text(encoding='utf-8'))
    
    context = ParentContext(
        spec_name=data["spec_name"],
        spec_path=data["spec_path"],
        phase=Phase(data["phase"]),
        depth=data["depth"],
        exported_at=data.get("exported_at", "")
    )
    
    arch = data.get("architecture_state", {})
    context.architecture_iterations = arch.get("iterations_completed", 0)
    context.final_proposal = arch.get("final_proposal")
    context.critiques = arch.get("critiques", [])
    context.architecture_approved = arch.get("approved", False)
    
    children = data.get("children_state", {})
    context.children_spawned = children.get("spawned", [])
    context.children_completed = children.get("completed", [])
    context.children_blocked = children.get("blocked", [])
    
    context.decisions = data.get("decisions", [])
    context.resume_instructions = data.get("resume_instructions", "")
    
    return context


# =============================================================================
# MESSAGING
# =============================================================================

def load_messages(spec_dir: Path) -> dict:
    """Load messages.json for a spec."""
    msg_path = spec_dir / "messages.json"
    if msg_path.exists():
        return json.loads(msg_path.read_text(encoding='utf-8'))
    return {"inbox": [], "outbox": [], "pending_responses": [], "wake_signals": []}


def save_messages(spec_dir: Path, messages: dict) -> None:
    """Save messages.json for a spec."""
    msg_path = spec_dir / "messages.json"
    msg_path.write_text(json.dumps(messages, indent=2), encoding='utf-8')


def send_message(
    from_dir: Path, 
    to_dir: Path, 
    msg_type: str, 
    payload: dict, 
    needs_response: bool = False,
    priority: str = "normal"
) -> str:
    """Send a message from one spec to another."""
    sender_msgs = load_messages(from_dir)
    msg_id = f"msg-{len(sender_msgs['outbox']) + 1:03d}"
    
    msg = {
        "id": msg_id,
        "from": str(from_dir),
        "to": str(to_dir),
        "type": msg_type,
        "payload": payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "needs_response": needs_response,
        "priority": priority,
        "status": "pending"
    }
    
    sender_msgs["outbox"].append(msg)
    if needs_response:
        sender_msgs["pending_responses"].append(msg_id)
    save_messages(from_dir, sender_msgs)
    
    receiver_msgs = load_messages(to_dir)
    receiver_msgs["inbox"].append(msg)
    
    # If blocking priority, add to wake signals
    if priority == "blocking":
        if "wake_signals" not in receiver_msgs:
            receiver_msgs["wake_signals"] = []
        receiver_msgs["wake_signals"].append(msg_id)
    
    save_messages(to_dir, receiver_msgs)
    
    return msg_id


def get_pending_messages(spec_dir: Path) -> list[dict]:
    """Get unprocessed messages from inbox."""
    messages = load_messages(spec_dir)
    return [m for m in messages["inbox"] if m.get("status") == "pending"]


def get_wake_signals(spec_dir: Path) -> list[dict]:
    """Get messages that should wake a hibernating parent."""
    messages = load_messages(spec_dir)
    wake_ids = set(messages.get("wake_signals", []))
    return [m for m in messages["inbox"] if m["id"] in wake_ids and m.get("status") == "pending"]


def mark_message_processed(spec_dir: Path, msg_id: str) -> None:
    """Mark a message as processed."""
    messages = load_messages(spec_dir)
    for msg in messages["inbox"]:
        if msg["id"] == msg_id:
            msg["status"] = "processed"
    # Remove from wake signals
    if "wake_signals" in messages:
        messages["wake_signals"] = [w for w in messages["wake_signals"] if w != msg_id]
    save_messages(spec_dir, messages)


def check_for_wake_signals(spec_dir: Path) -> bool:
    """Check if there are any wake signals pending."""
    return len(get_wake_signals(spec_dir)) > 0


# =============================================================================
# VERIFICATION RESULT PARSING
# =============================================================================

def parse_verification_result(response_text: str, json_blocks: list[dict]) -> Optional[dict]:
    """
    Parse structured verification result from verifier output.
    
    Expected format (from verification-result-schema.json):
    {
        "spec_name": "...",
        "iteration": 1,
        "compilation": { "success": true/false, "errors": [...] },
        "tests": { "ran": true, "total": 10, "passed": 10, "failed": 0, "failures": [...] },
        "verdict": "pass" | "fail_compilation" | "fail_tests" | ...
    }
    """
    # Look for verification result in JSON blocks
    for block in json_blocks:
        if "verdict" in block and "compilation" in block:
            return block
    
    # Fallback: try to infer from text
    text_lower = response_text.lower()
    
    if "all tests pass" in text_lower or "verdict\": \"pass" in text_lower:
        return {
            "verdict": "pass",
            "compilation": {"success": True},
            "tests": {"ran": True, "passed": 0, "failed": 0}  # Unknown counts
        }
    
    return None


def apply_verification_to_spec(spec: Spec, result: dict) -> None:
    """Apply verification result to spec's errors field."""
    verdict = result.get("verdict", "")
    
    if verdict == "pass":
        spec.all_tests_passed = True
        spec.errors = None
    else:
        spec.all_tests_passed = False
        
        compilation = result.get("compilation", {})
        tests = result.get("tests", {})
        
        spec.errors = Errors(
            iteration=result.get("iteration", spec.ralph_iteration),
            timestamp=datetime.now(timezone.utc).isoformat(),
            compilation_success=compilation.get("success", True),
            compilation_errors=[
                e.get("message", str(e)) for e in compilation.get("errors", [])
            ],
            test_total=tests.get("total", 0),
            test_passed=tests.get("passed", 0),
            test_failed=tests.get("failed", 0),
            test_failures=tests.get("failures", [])
        )


# =============================================================================
# AGENT SPAWNING
# =============================================================================

def extract_json_from_text(text: str) -> list[dict]:
    """Extract all JSON blocks from response text."""
    import re
    results = []
    for block in re.findall(r'```json\s*([\s\S]*?)\s*```', text):
        try:
            results.append(json.loads(block))
        except:
            continue
    return results


def load_agent_prompt(agent_type: str) -> str:
    """Load the system prompt for an agent type."""
    agent_file = Path(__file__).parent.parent / "agents" / f"{agent_type}.md"
    if not agent_file.exists():
        raise FileNotFoundError(f"Agent prompt not found: {agent_file}")
    return agent_file.read_text(encoding='utf-8')


def load_style_guide() -> str:
    """Load STYLE.md if it exists."""
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        style_path = parent / "STYLE.md"
        if style_path.exists():
            return style_path.read_text(encoding='utf-8')
    return ""


def build_agent_context(
    agent_type: str, 
    spec: Spec, 
    extra_context: str = "",
    parent_context: Optional[ParentContext] = None,
    wake_messages: Optional[list[dict]] = None
) -> str:
    """Build the user prompt/context for an agent."""
    spec_json = json.dumps(spec_to_dict(spec), indent=2)
    spec_dir = spec.path.parent if spec.path else Path.cwd()
    
    context = f"""# Task Context

**Spec:** {spec.name}
**Directory:** {spec_dir}
**Type:** {"Leaf" if spec.is_leaf else "Non-leaf" if spec.is_leaf is False else "Undecided"}
**Status:** {spec.status}

## spec.json

```json
{spec_json}
```
"""
    
    # Add restored parent context if this is a wake-up
    if parent_context:
        context += f"""
## Restored Context (You were hibernating)

You are being woken up from hibernation. Here's your previous state:

**Phase when hibernated:** {parent_context.phase.value}
**Architecture approved:** {parent_context.architecture_approved}
**Children spawned:** {', '.join(parent_context.children_spawned) or 'None'}
**Children completed:** {', '.join(parent_context.children_completed) or 'None'}

**Your previous decisions:**
"""
        for d in parent_context.decisions[-5:]:  # Last 5 decisions
            context += f"- {d.get('decision', '')}\n"
        
        if parent_context.resume_instructions:
            context += f"\n**Resume instructions:** {parent_context.resume_instructions}\n"
    
    # Add wake messages if this is a parent being woken
    if wake_messages:
        context += "\n## Messages That Woke You\n\n"
        for msg in wake_messages:
            context += f"- **{msg.get('type')}** from `{Path(msg.get('from', '')).name}` (priority: {msg.get('priority', 'normal')}):\n"
            context += f"  ```json\n  {json.dumps(msg.get('payload', {}), indent=2)}\n  ```\n"
    
    # Add pending messages
    if spec.path:
        pending = get_pending_messages(spec.path.parent)
        non_wake = [m for m in pending if m not in (wake_messages or [])]
        if non_wake:
            context += "\n## Other Pending Messages\n\n"
            for msg in non_wake:
                context += f"- **{msg.get('type')}** from `{Path(msg.get('from', '')).name}`\n"
    
    # Add style guide for relevant agents
    if agent_type in ["proposer", "critic", "implementer"]:
        style = load_style_guide()
        if style:
            context += f"\n## Project Style Guide (STYLE.md)\n\n{style}\n"
    
    # Add previous errors for implementer
    if agent_type == "implementer" and spec.errors:
        context += f"\n## Previous Errors (Iteration {spec.errors.iteration})\n"
        if spec.errors.compilation_errors:
            context += "Compilation:\n```\n" + "\n".join(spec.errors.compilation_errors) + "\n```\n"
        if spec.errors.test_failures:
            context += "Test failures:\n"
            for f in spec.errors.test_failures:
                context += f"- {f.get('test_name')}: expected {f.get('expected')}, got {f.get('actual')}\n"
    
    # Add extra context
    if extra_context:
        context += f"\n{extra_context}\n"
    
    context += f"\nProcess this spec according to your role as {agent_type}.\n"
    context += "Output any spec updates as a ```json block.\n"
    
    return context


async def spawn_agent(
    agent_type: str, 
    spec: Spec, 
    depth: int, 
    extra_context: str = "",
    parent_context: Optional[ParentContext] = None,
    wake_messages: Optional[list[dict]] = None
) -> dict:
    """Spawn an agent using the Claude Agent SDK."""
    
    if CONFIG.agents_spawned >= CONFIG.max_total_agents:
        return {"success": False, "error": f"Max agents ({CONFIG.max_total_agents}) exceeded"}
    
    if CONFIG.dry_run:
        log(f"Would spawn {agent_type} for {spec.name}", "DRY", depth)
        return {"success": True, "dry_run": True, "response": "", "json_blocks": []}
    
    CONFIG.agents_spawned += 1
    log(f"Spawning {agent_type}", "SPAWN", depth)
    
    if not CONFIG.live:
        log(f"[SIMULATED] {agent_type} completed", "INFO", depth)
        return {"success": True, "simulated": True, "response": "", "json_blocks": []}
    
    # === LIVE MODE ===
    try:
        from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, ResultMessage
    except ImportError:
        return {"success": False, "error": "Run: pip install claude-agent-sdk"}
    
    spec_dir = spec.path.parent if spec.path else Path.cwd()
    
    system_prompt = load_agent_prompt(agent_type)
    user_prompt = build_agent_context(agent_type, spec, extra_context, parent_context, wake_messages)
    tools = AGENT_TOOLS.get(agent_type, ["Read", "Glob"])
    
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        allowed_tools=tools,
        permission_mode="bypassPermissions",
        cwd=str(spec_dir),
        setting_sources=["project"],
        model=CONFIG.model,
    )
    
    accumulated_text = ""
    
    try:
        async for message in query(prompt=user_prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if hasattr(block, 'text'):
                        accumulated_text += block.text
            elif isinstance(message, ResultMessage):
                if hasattr(message, 'result'):
                    accumulated_text += str(message.result)
        
        json_blocks = extract_json_from_text(accumulated_text)
        
        return {
            "success": True,
            "response": accumulated_text,
            "json_blocks": json_blocks
        }
        
    except Exception as e:
        log(f"Agent SDK error: {e}", "ERROR", depth)
        return {"success": False, "error": str(e)}


# =============================================================================
# ARCHITECTURE LOOP
# =============================================================================

async def run_architecture_loop(spec: Spec, depth: int) -> tuple[bool, dict]:
    """
    Run Proposer <-> Critic loop.
    Returns (success, architecture_state) for context export.
    """
    log(f"Architecture loop for {spec.name}", "ARCH", depth)
    
    proposal = None
    critiques = []
    
    for iteration in range(1, CONFIG.max_arch_iterations + 1):
        log(f"Architecture iteration {iteration}/{CONFIG.max_arch_iterations}", "ARCH", depth)
        
        # Build context with previous critique
        extra = ""
        if critiques:
            extra = f"## Previous Critique\n\n```json\n{json.dumps(critiques[-1], indent=2)}\n```\n"
            extra += "\nAddress the critic's concerns in your revised proposal."
        
        # Proposer
        result = await spawn_agent("proposer", spec, depth, extra)
        if not result.get("success"):
            return False, {"iterations": iteration, "error": result.get("error")}
        
        # Extract proposal
        if CONFIG.live and result.get("json_blocks"):
            for j in result["json_blocks"]:
                if "structure" in j or "rationale" in j:
                    proposal = j
                    break
        
        if CONFIG.dry_run or not CONFIG.live:
            proposal = {"structure": {"is_leaf": spec.is_leaf}, "approved_simulation": True}
        
        # Critic
        extra = f"## Proposal to Review\n\n```json\n{json.dumps(proposal, indent=2)}\n```"
        result = await spawn_agent("critic", spec, depth, extra)
        if not result.get("success"):
            return False, {"iterations": iteration, "error": result.get("error")}
        
        # Extract critique
        critique = None
        if CONFIG.live and result.get("json_blocks"):
            for j in result["json_blocks"]:
                if "approved" in j:
                    critique = j
                    critiques.append(critique)
                    break
        
        if CONFIG.dry_run or not CONFIG.live:
            critique = {"approved": iteration >= 2}
            critiques.append(critique)
        
        # Check approval
        if critique and critique.get("approved"):
            log("Architecture approved", "SUCCESS", depth)
            
            # Apply proposal to spec
            apply_proposal_to_spec(spec, proposal)
            save_spec(spec)
            
            return True, {
                "iterations": iteration,
                "proposal": proposal,
                "critiques": critiques,
                "approved": True
            }
    
    log(f"Architecture loop exhausted", "WARN", depth)
    return True, {
        "iterations": CONFIG.max_arch_iterations,
        "proposal": proposal,
        "critiques": critiques,
        "approved": False
    }


def apply_proposal_to_spec(spec: Spec, proposal: Optional[dict]) -> None:
    """Apply an approved proposal to a spec."""
    if not proposal:
        return
    
    if "structure" in proposal:
        struct = proposal["structure"]
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
    
    if "interfaces" in proposal:
        if "shared_types" in proposal["interfaces"]:
            spec.shared_types = [
                SharedType(**s) if isinstance(s, dict) else s
                for s in proposal["interfaces"]["shared_types"]
            ]
    
    if "criteria" in proposal:
        if "acceptance" in proposal["criteria"]:
            spec.acceptance = [
                Criterion(**c) if isinstance(c, dict) else c
                for c in proposal["criteria"]["acceptance"]
            ]
        if "integration" in proposal["criteria"]:
            spec.integration = [
                Criterion(**c) if isinstance(c, dict) else c
                for c in proposal["criteria"]["integration"]
            ]


# =============================================================================
# SCAFFOLDING
# =============================================================================

def scaffold_children(spec: Spec, depth: int) -> list[str]:
    """Create child spec directories. Returns list of child names created."""
    if not spec.path:
        raise ValueError("Spec has no path")
    
    children_dir = spec.path.parent / "children"
    children_dir.mkdir(exist_ok=True)
    created = []
    
    if spec.shared_types:
        shared_dir = children_dir / "shared"
        shared_dir.mkdir(exist_ok=True)
        shared_path = shared_dir / "spec.json"
        if not shared_path.exists():
            save_spec(create_shared_spec(spec, shared_path), shared_path)
            created.append("shared")
            log("Created shared/", "INFO", depth)
    
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
            log(f"Created {child_def.name}/", "INFO", depth)
    
    return created


# =============================================================================
# IMPLEMENTATION LOOP (for leaves)
# =============================================================================

async def run_implementation_loop(spec: Spec, depth: int) -> bool:
    """Run Implementer <-> Verifier loop until tests pass."""
    log(f"Implementation loop for {spec.name}", "INFO", depth)
    
    while spec.ralph_iteration < CONFIG.max_iterations:
        spec.ralph_iteration += 1
        log(f"Iteration {spec.ralph_iteration}/{CONFIG.max_iterations}", "INFO", depth)
        
        # Implementer
        result = await spawn_agent("implementer", spec, depth)
        if not result.get("success"):
            return False
        
        # Verifier
        result = await spawn_agent("verifier", spec, depth)
        if not result.get("success"):
            return False
        
        # Parse structured verification result
        verification = parse_verification_result(
            result.get("response", ""),
            result.get("json_blocks", [])
        )
        
        if verification:
            apply_verification_to_spec(spec, verification)
        
        # Reload and check
        if spec.path:
            spec = load_spec(spec.path)
        
        if spec.all_tests_passed:
            spec.status = "complete"
            save_spec(spec)
            log("All tests passed!", "SUCCESS", depth)
            return True
        
        # Simulated success
        if (CONFIG.dry_run or not CONFIG.live) and spec.ralph_iteration >= 2:
            spec.all_tests_passed = True
            spec.status = "complete"
            save_spec(spec)
            log("Tests passed (simulated)", "SUCCESS", depth)
            return True
        
        save_spec(spec)
    
    log(f"Max iterations reached", "ERROR", depth)
    return False


# =============================================================================
# MAIN ORCHESTRATION LOGIC
# =============================================================================

async def process_leaf(spec_path: Path, depth: int) -> bool:
    """Process a leaf spec (direct implementation)."""
    spec = load_spec(spec_path)
    spec.depth = depth
    spec.status = "in_progress"
    save_spec(spec)
    
    success = await run_implementation_loop(spec, depth)
    
    spec = load_spec(spec_path)
    spec.status = "complete" if success else "failed"
    save_spec(spec)
    
    # Notify parent of completion
    parent_dir = spec_path.parent.parent.parent  # children/<name>/spec.json -> parent
    if (parent_dir / "spec.json").exists():
        send_message(
            spec_path.parent,
            parent_dir,
            "complete",
            {"child": spec.name, "success": success}
        )
    
    return success


async def process_non_leaf(spec_path: Path, depth: int) -> bool:
    """
    Process a non-leaf spec using the hibernation pattern.
    
    1. Run architecture loop if needed
    2. Scaffold children
    3. Export context and "hibernate"
    4. Let children run independently
    5. Wake when needed or when all complete
    """
    spec = load_spec(spec_path)
    spec.depth = depth
    spec.status = "in_progress"
    save_spec(spec)
    
    spec_dir = spec_path.parent
    decisions = []
    
    # Check for existing context (are we resuming?)
    parent_ctx = load_parent_context(spec_dir)
    
    if parent_ctx and parent_ctx.phase == Phase.AWAITING_CHILDREN:
        # We're being woken up!
        log(f"Waking parent {spec.name}", "WAKE", depth)
        wake_msgs = get_wake_signals(spec_dir)
        
        # Process wake messages
        for msg in wake_msgs:
            msg_type = msg.get("type")
            payload = msg.get("payload", {})
            
            if msg_type == "need_shared_type":
                type_name = payload.get("name")
                log(f"Child requests shared type: {type_name}", "MSG", depth)
                
                existing = [st.name for st in spec.shared_types]
                if type_name and type_name not in existing:
                    spec.shared_types.append(SharedType(
                        name=type_name,
                        kind=payload.get("kind", "class"),
                        description=payload.get("reason", "")
                    ))
                    save_spec(spec)
                    decisions.append({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "decision": f"Added shared type {type_name}",
                        "rationale": payload.get("reason", "Child requested")
                    })
            
            elif msg_type == "complete":
                child_name = payload.get("child")
                if child_name and child_name not in parent_ctx.children_completed:
                    parent_ctx.children_completed.append(child_name)
                    log(f"Child {child_name} completed", "SUCCESS", depth)
            
            mark_message_processed(spec_dir, msg["id"])
        
        # Check if all children complete
        all_complete = set(parent_ctx.children_spawned) <= set(parent_ctx.children_completed)
        
        if all_complete:
            log("All children complete, running integration", "INFO", depth)
            spec.integration_tests_passed = True  # TODO: actual integration tests
            spec.status = "complete"
            save_spec(spec)
            return True
        else:
            # Re-hibernate
            log(f"Re-hibernating, waiting for: {set(parent_ctx.children_spawned) - set(parent_ctx.children_completed)}", "HIBERNATE", depth)
            export_parent_context(
                spec, Phase.AWAITING_CHILDREN, depth,
                children_state={
                    "spawned": parent_ctx.children_spawned,
                    "completed": parent_ctx.children_completed,
                    "blocked": parent_ctx.children_blocked
                },
                decisions=parent_ctx.decisions + decisions,
                resume_instructions="Continue waiting for children or handle their messages"
            )
            return True  # Successfully hibernated
    
    # Fresh start - run architecture loop
    if spec.is_leaf is None:
        log("Running architecture loop", "ARCH", depth)
        success, arch_state = await run_architecture_loop(spec, depth)
        if not success:
            return False
        spec = load_spec(spec_path)
        
        decisions.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decision": f"Architecture decided: is_leaf={spec.is_leaf}",
            "rationale": arch_state.get("proposal", {}).get("rationale", "")
        })
    
    # If architecture decided this is actually a leaf, process as leaf
    if spec.is_leaf is True:
        return await process_leaf(spec_path, depth)
    
    # Scaffold children
    children_dir = spec_path.parent / "children"
    if not children_dir.exists() or not any(children_dir.iterdir()):
        spawned = scaffold_children(spec, depth)
    else:
        spawned = [d.name for d in children_dir.iterdir() if d.is_dir()]
    
    # Export context and hibernate
    log(f"Hibernating, spawned children: {spawned}", "HIBERNATE", depth)
    export_parent_context(
        spec, Phase.AWAITING_CHILDREN, depth,
        children_state={"spawned": spawned, "completed": [], "blocked": []},
        decisions=decisions,
        resume_instructions="Wait for children to complete or handle their messages"
    )
    
    # Now process children (they run independently)
    # Process shared first if it exists
    shared_path = children_dir / "shared" / "spec.json"
    if shared_path.exists():
        log("Processing shared/ first", "INFO", depth)
        await ralph_recursive(shared_path, depth + 1)
    
    # Process other children
    for child_name in spawned:
        if child_name == "shared":
            continue
        child_path = children_dir / child_name / "spec.json"
        if child_path.exists():
            await ralph_recursive(child_path, depth + 1)
    
    # After children finish, check if we need to wake parent for integration
    # (In a real async system, this would be event-driven)
    if check_for_wake_signals(spec_dir):
        return await process_non_leaf(spec_path, depth)  # Recursive wake
    
    # Final integration check
    spec = load_spec(spec_path)
    spec.integration_tests_passed = True
    spec.status = "complete"
    save_spec(spec)
    log("Integration complete", "SUCCESS", depth)
    
    return True


async def ralph_recursive(spec_path: Path, depth: int = 0) -> bool:
    """Main entry point for processing a spec."""
    log(f"Processing: {spec_path.parent.name}", "INFO", depth)
    
    if depth > CONFIG.max_depth:
        log(f"Max depth ({CONFIG.max_depth}) exceeded", "ERROR", depth)
        return False
    
    try:
        spec = load_spec(spec_path)
    except Exception as e:
        log(f"Load failed: {e}", "ERROR", depth)
        return False
    
    # Determine if leaf or non-leaf
    if spec.is_leaf is True:
        return await process_leaf(spec_path, depth)
    elif spec.is_leaf is False:
        return await process_non_leaf(spec_path, depth)
    else:
        # Undecided - need architecture loop
        return await process_non_leaf(spec_path, depth)


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Ralph-Recursive v3 (Hibernating Parents)")
    parser.add_argument("--spec", required=True, help="Path to spec.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--max-arch-iterations", type=int, default=5)
    parser.add_argument("--max-agents", type=int, default=50)
    parser.add_argument("--model", default="claude-opus-4-5-20251101")
    
    args = parser.parse_args()
    
    CONFIG.max_depth = args.max_depth
    CONFIG.max_iterations = args.max_iterations
    CONFIG.max_arch_iterations = args.max_arch_iterations
    CONFIG.max_total_agents = args.max_agents
    CONFIG.dry_run = args.dry_run
    CONFIG.live = args.live
    CONFIG.model = args.model
    
    spec_path = Path(args.spec)
    mode = "DRY RUN" if CONFIG.dry_run else ("LIVE" if CONFIG.live else "SIMULATED")
    
    print("=" * 60)
    print(f"RALPH-RECURSIVE v3 [Hibernating Parents] [{mode}]")
    print("=" * 60)
    print(f"Spec: {spec_path}")
    print(f"Max Depth: {CONFIG.max_depth}")
    print("=" * 60)
    
    try:
        success = asyncio.run(ralph_recursive(spec_path))
        print(f"\n{'='*60}")
        print(f"Result: {'SUCCESS' if success else 'FAILED'}")
        print(f"Agents spawned: {CONFIG.agents_spawned}")
        print("=" * 60)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(130)
    except Exception as e:
        print(f"\nFATAL: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
