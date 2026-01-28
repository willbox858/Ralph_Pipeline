#!/usr/bin/env python3
"""
Ralph-Recursive v2: Hierarchical spec implementation using Claude Agent SDK.

This script acts as a "trampoline" that allows recursive agent spawning
by wrapping the Agent SDK in a Python script that Claude Code can execute.

Features:
- Adversarial architecture loop (Proposer <-> Critic)
- Adversarial implementation loop (Implementer <-> Verifier)
- Hierarchical messaging (parent <-> child only)
- Style guide enforcement
- Hooks integration via setting_sources

Requirements:
    pip install claude-agent-sdk

Usage:
    python3 ralph-recursive-v2.py --spec spec.json --dry-run
    python3 ralph-recursive-v2.py --spec spec.json --live
"""

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, AsyncIterator, Any

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
    confirm_each_level: bool = False
    dry_run: bool = False
    live: bool = False
    pause_on_error: bool = True
    model: str = "claude-opus-4-5-20251101"
    agents_spawned: int = 0


CONFIG = Config()

# Tools available to each agent type
# Architects (proposer/critic) need to read existing code to make informed decisions
# Implementer needs full file manipulation
# Verifier needs to run tests and read results
AGENT_TOOLS = {
    "proposer": ["Read", "Glob", "Bash", "Write"],  # Architect: analyze codebase, write spec updates
    "critic": ["Read", "Glob", "Bash"],              # Architect: review proposals, analyze feasibility
    "implementer": ["Read", "Write", "Edit", "MultiEdit", "Bash", "Glob"],  # Full implementation
    "verifier": ["Read", "Bash", "Glob"],            # Run tests, report results (no writes)
    "coordinator": ["Read", "Glob"],                 # Analyze state, route messages
}


# =============================================================================
# LOGGING
# =============================================================================

def log(msg: str, level: str = "INFO", depth: int = 0) -> None:
    indent = "  " * depth
    prefix = {
        "INFO": "->", "WARN": "!", "ERROR": "X", "SUCCESS": "*",
        "DRY": "o", "SPAWN": "+", "API": "@", "ARCH": "#",
        "MSG": "m", "STREAM": "~"
    }.get(level, "-")
    print(f"{indent}{prefix} [{level}] {msg}")


# =============================================================================
# SAFETY
# =============================================================================

def check_safety(agent_type: str, depth: int) -> tuple[bool, str]:
    if depth > CONFIG.max_depth:
        return False, f"Max depth ({CONFIG.max_depth}) exceeded"
    if CONFIG.agents_spawned >= CONFIG.max_total_agents:
        return False, f"Max agents ({CONFIG.max_total_agents}) exceeded"
    return True, ""


def confirm_action(action: str, depth: int) -> bool:
    if not CONFIG.confirm_each_level:
        return True
    indent = "  " * depth
    print(f"\n{indent}CONFIRM: {action}")
    print(f"{indent}Agents spawned: {CONFIG.agents_spawned}")
    return input(f"{indent}Proceed? [y/N]: ").strip().lower() == 'y'


def track_spawn(agent_type: str):
    CONFIG.agents_spawned += 1


# =============================================================================
# STYLE GUIDE
# =============================================================================

def find_project_root() -> Path:
    """Find project root by looking for STYLE.md or CLAUDE.md."""
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / "STYLE.md").exists() or (parent / "CLAUDE.md").exists():
            return parent
    return cwd


def load_style_guide() -> str:
    """Load STYLE.md if it exists."""
    style_path = find_project_root() / "STYLE.md"
    if style_path.exists():
        return style_path.read_text(encoding='utf-8')
    return ""


# =============================================================================
# MESSAGING (unchanged from original)
# =============================================================================

def load_messages(spec_dir: Path) -> dict:
    """Load messages.json for a spec."""
    msg_path = spec_dir / "messages.json"
    if msg_path.exists():
        return json.loads(msg_path.read_text(encoding='utf-8'))
    return {"inbox": [], "outbox": [], "pending_responses": []}


def save_messages(spec_dir: Path, messages: dict) -> None:
    """Save messages.json for a spec."""
    msg_path = spec_dir / "messages.json"
    msg_path.write_text(json.dumps(messages, indent=2), encoding='utf-8')


def send_message(from_dir: Path, to_dir: Path, msg_type: str, payload: dict, needs_response: bool = False) -> str:
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
        "status": "pending"
    }
    
    sender_msgs["outbox"].append(msg)
    if needs_response:
        sender_msgs["pending_responses"].append(msg_id)
    save_messages(from_dir, sender_msgs)
    
    receiver_msgs = load_messages(to_dir)
    receiver_msgs["inbox"].append(msg)
    save_messages(to_dir, receiver_msgs)
    
    return msg_id


def get_pending_messages(spec_dir: Path) -> list[dict]:
    """Get unprocessed messages from inbox."""
    messages = load_messages(spec_dir)
    return [m for m in messages["inbox"] if m.get("status") == "pending"]


def mark_message_processed(spec_dir: Path, msg_id: str) -> None:
    """Mark a message as processed."""
    messages = load_messages(spec_dir)
    for msg in messages["inbox"]:
        if msg["id"] == msg_id:
            msg["status"] = "processed"
    save_messages(spec_dir, messages)


# =============================================================================
# AGENT PROMPTS & CONTEXT
# =============================================================================

def load_agent_prompt(agent_type: str) -> str:
    """Load the system prompt for an agent type."""
    agent_file = Path(__file__).parent.parent / "agents" / f"{agent_type}.md"
    if not agent_file.exists():
        raise FileNotFoundError(f"Agent prompt not found: {agent_file}")
    return agent_file.read_text(encoding='utf-8')


def build_agent_context(agent_type: str, spec: Spec, extra_context: str = "") -> str:
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
    
    # Add style guide for relevant agents (architects and implementers)
    if agent_type in ["proposer", "critic", "implementer"]:
        style = load_style_guide()
        if style:
            context += f"\n## Project Style Guide (STYLE.md)\n\n{style}\n"
    
    # Inject pending messages so agent knows about them
    if spec.path:
        pending = get_pending_messages(spec.path.parent)
        if pending:
            context += "\n## Pending Messages\n\n"
            for msg in pending:
                context += f"- **{msg.get('type')}** from `{Path(msg.get('from', '')).name}`:\n"
                context += f"  ```json\n  {json.dumps(msg.get('payload', {}), indent=2)}\n  ```\n"
    
    # Add previous errors for implementer
    if agent_type == "implementer" and spec.errors:
        context += f"\n## Previous Errors (Iteration {spec.errors.iteration})\n"
        if spec.errors.compilation_errors:
            context += "Compilation:\n```\n" + "\n".join(spec.errors.compilation_errors) + "\n```\n"
        if spec.errors.test_failures:
            context += "Test failures:\n"
            for f in spec.errors.test_failures:
                context += f"- {f.get('test_name')}: expected {f.get('expected')}, got {f.get('actual')}\n"
    
    # Add extra context (proposals, critiques, etc.)
    if extra_context:
        context += f"\n{extra_context}\n"
    
    context += f"\nProcess this spec according to your role as {agent_type}.\n"
    context += "Output any spec updates as a ```json block.\n"
    
    return context


# =============================================================================
# AGENT SDK INTEGRATION
# =============================================================================

def extract_json_from_text(text: str) -> list[dict]:
    """Extract all JSON blocks from response text."""
    results = []
    for block in re.findall(r'```json\s*([\s\S]*?)\s*```', text):
        try:
            results.append(json.loads(block))
        except:
            continue
    return results


async def spawn_agent(agent_type: str, spec: Spec, depth: int, extra_context: str = "") -> dict:
    """
    Spawn an agent using the Claude Agent SDK.
    
    Returns a dict with:
        - success: bool
        - response: str (accumulated text from agent)
        - json_blocks: list[dict] (extracted JSON from response)
        - error: str (if failed)
    """
    safe, reason = check_safety(agent_type, depth)
    if not safe:
        return {"success": False, "error": f"Safety: {reason}"}
    
    if not confirm_action(f"Spawn {agent_type} for {spec.name}", depth):
        return {"success": False, "error": "User cancelled"}
    
    if CONFIG.dry_run:
        log(f"Would spawn {agent_type} for {spec.name}", "DRY", depth)
        return {"success": True, "dry_run": True, "response": "", "json_blocks": []}
    
    track_spawn(agent_type)
    log(f"Spawning {agent_type}", "SPAWN", depth)
    
    if not CONFIG.live:
        # Simulated mode - return fake success
        log(f"[SIMULATED] {agent_type} completed", "INFO", depth)
        return {"success": True, "simulated": True, "response": "", "json_blocks": []}
    
    # === LIVE MODE: Use Agent SDK ===
    try:
        from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, ResultMessage
    except ImportError:
        return {"success": False, "error": "Run: pip install claude-agent-sdk"}
    
    spec_dir = spec.path.parent if spec.path else Path.cwd()
    project_root = find_project_root()
    
    system_prompt = load_agent_prompt(agent_type)
    user_prompt = build_agent_context(agent_type, spec, extra_context)
    tools = AGENT_TOOLS.get(agent_type, ["Read", "Glob"])
    
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        allowed_tools=tools,
        permission_mode="bypassPermissions",  # Ralph-loop: trust the agents
        # Note: If this fails, try: dangerously_skip_permissions=True
        # The exact parameter name may vary by SDK version
        cwd=str(spec_dir),
        setting_sources=["project"],  # Enable hooks from .claude/settings.json
        model=CONFIG.model,
    )
    
    accumulated_text = ""
    
    try:
        log(f"Calling Agent SDK ({CONFIG.model})...", "API", depth)
        
        async for message in query(prompt=user_prompt, options=options):
            # Handle different message types
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if hasattr(block, 'text'):
                        accumulated_text += block.text
                        # Log a snippet for visibility
                        snippet = block.text[:50].replace('\n', ' ')
                        if len(block.text) > 50:
                            snippet += "..."
                        log(f"Agent: {snippet}", "STREAM", depth)
            
            elif isinstance(message, ResultMessage):
                # Final result
                if hasattr(message, 'result'):
                    accumulated_text += str(message.result)
                log("Agent completed", "SUCCESS", depth)
        
        # Extract JSON blocks from accumulated response
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
# ADVERSARIAL ARCHITECTURE LOOP
# =============================================================================

async def run_architecture_loop(spec: Spec, depth: int) -> bool:
    """Run Proposer <-> Critic loop until architecture is approved."""
    log(f"Architecture loop for {spec.name}", "ARCH", depth)
    
    proposal = None
    critique = None
    
    for iteration in range(1, CONFIG.max_arch_iterations + 1):
        log(f"Architecture iteration {iteration}/{CONFIG.max_arch_iterations}", "ARCH", depth)
        
        # Build context with previous critique if exists
        extra = ""
        if critique:
            extra = f"## Previous Critique\n\n```json\n{json.dumps(critique, indent=2)}\n```\n"
            extra += "\nAddress the critic's concerns in your revised proposal."
        
        # === PROPOSER ===
        result = await spawn_agent("proposer", spec, depth, extra)
        if not result.get("success"):
            return False
        
        # Extract proposal from response
        if CONFIG.live and result.get("json_blocks"):
            for j in result["json_blocks"]:
                if "structure" in j or "rationale" in j:
                    proposal = j
                    break
        
        if CONFIG.dry_run or not CONFIG.live:
            # Simulate proposal
            proposal = {"structure": {"is_leaf": spec.is_leaf}, "approved_simulation": True}
        
        # === CRITIC ===
        extra = f"## Proposal to Review\n\n```json\n{json.dumps(proposal, indent=2)}\n```"
        
        result = await spawn_agent("critic", spec, depth, extra)
        if not result.get("success"):
            return False
        
        # Extract critique from response
        if CONFIG.live and result.get("json_blocks"):
            for j in result["json_blocks"]:
                if "approved" in j:
                    critique = j
                    break
        
        if CONFIG.dry_run or not CONFIG.live:
            # Simulate approval after iteration 2
            critique = {"approved": iteration >= 2}
        
        # Check if approved
        if critique and critique.get("approved"):
            log("Architecture approved by critic", "SUCCESS", depth)
            
            # Apply proposal to spec
            if proposal and "structure" in proposal:
                if "is_leaf" in proposal["structure"]:
                    spec.is_leaf = proposal["structure"]["is_leaf"]
                if "children" in proposal["structure"]:
                    spec.children = [
                        Child(**c) if isinstance(c, dict) else c
                        for c in proposal["structure"]["children"]
                    ]
                if "classes" in proposal["structure"]:
                    spec.classes = [
                        ClassDef(**c) if isinstance(c, dict) else c
                        for c in proposal["structure"]["classes"]
                    ]
            
            if proposal and "interfaces" in proposal:
                if "shared_types" in proposal["interfaces"]:
                    spec.shared_types = [
                        SharedType(**s) if isinstance(s, dict) else s
                        for s in proposal["interfaces"]["shared_types"]
                    ]
            
            if proposal and "criteria" in proposal:
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
            
            save_spec(spec)
            return True
    
    log(f"Architecture loop exhausted ({CONFIG.max_arch_iterations} iterations)", "WARN", depth)
    # Take last proposal anyway
    if proposal:
        save_spec(spec)
    return True


# =============================================================================
# IMPLEMENTATION LOOP
# =============================================================================

async def run_implementation_loop(spec: Spec, depth: int) -> bool:
    """Run Implementer <-> Verifier loop until tests pass."""
    log(f"Implementation loop for {spec.name}", "INFO", depth)
    
    while spec.ralph_iteration < CONFIG.max_iterations:
        spec.ralph_iteration += 1
        log(f"Iteration {spec.ralph_iteration}/{CONFIG.max_iterations}", "INFO", depth)
        
        # === IMPLEMENTER ===
        result = await spawn_agent("implementer", spec, depth)
        if not result.get("success"):
            return False
        
        # === VERIFIER ===
        result = await spawn_agent("verifier", spec, depth)
        if not result.get("success"):
            return False
        
        # Check for test pass in response
        if CONFIG.live:
            response_text = result.get("response", "").lower()
            if "all tests pass" in response_text or "all_tests_passed\": true" in response_text:
                spec.all_tests_passed = True
            
            # Also check JSON blocks for structured result
            for j in result.get("json_blocks", []):
                if j.get("runtime", {}).get("all_tests_passed"):
                    spec.all_tests_passed = True
                if j.get("all_tests_passed"):
                    spec.all_tests_passed = True
        
        # Reload spec in case agent modified it
        if spec.path:
            spec = load_spec(spec.path)
        
        if spec.all_tests_passed:
            spec.status = "complete"
            save_spec(spec)
            log("All tests passed!", "SUCCESS", depth)
            return True
        
        # Simulated success after 2 iterations
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
# SCAFFOLDING
# =============================================================================

def scaffold_children(spec: Spec, depth: int) -> list[Path]:
    """Create child spec directories from parent spec."""
    if not spec.path:
        raise ValueError("Spec has no path")
    
    children_dir = spec.path.parent / "children"
    children_dir.mkdir(exist_ok=True)
    created = []
    
    # Create shared/ if shared_types exist
    if spec.shared_types:
        shared_dir = children_dir / "shared"
        shared_dir.mkdir(exist_ok=True)
        shared_path = shared_dir / "spec.json"
        if not shared_path.exists():
            save_spec(create_shared_spec(spec, shared_path), shared_path)
            created.append(shared_path)
            log("Created shared/", "INFO", depth)
    
    # Create child directories
    for child_def in spec.children:
        child_dir = children_dir / child_def.name
        child_dir.mkdir(exist_ok=True)
        child_path = child_dir / "spec.json"
        if not child_path.exists():
            child_spec = create_child_spec(spec, child_def, child_path)
            if spec.shared_types and "shared" not in child_spec.depends_on:
                child_spec.depends_on.insert(0, "shared")
            save_spec(child_spec, child_path)
            created.append(child_path)
            log(f"Created {child_def.name}/", "INFO", depth)
    
    return created


# =============================================================================
# MESSAGE HANDLING
# =============================================================================

def process_messages(spec: Spec, depth: int) -> bool:
    """Process any pending messages for this spec."""
    if not spec.path:
        return True
    
    spec_dir = spec.path.parent
    pending = get_pending_messages(spec_dir)
    
    if not pending:
        return True
    
    log(f"Processing {len(pending)} message(s)", "MSG", depth)
    
    for msg in pending:
        msg_type = msg.get("type")
        payload = msg.get("payload", {})
        
        if msg_type == "need_shared_type":
            type_name = payload.get("name")
            log(f"Child requests shared type: {type_name}", "MSG", depth)
            
            # Add to shared_types if not present
            existing = [st.name for st in spec.shared_types]
            if type_name and type_name not in existing:
                spec.shared_types.append(SharedType(
                    name=type_name,
                    kind=payload.get("kind", "class"),
                    description=payload.get("reason", "")
                ))
                save_spec(spec)
                log(f"Added {type_name} to shared_types", "SUCCESS", depth)
        
        elif msg_type == "dependency_issue":
            log(f"Child reports dependency issue: {payload}", "WARN", depth)
        
        mark_message_processed(spec_dir, msg["id"])
    
    return True


# =============================================================================
# INTEGRATION TESTING
# =============================================================================

async def run_integration_tests(spec: Spec, depth: int) -> bool:
    """
    Run integration tests for a non-leaf spec.
    
    TODO: This should spawn a verifier-like agent to run integration criteria.
    For now, we check that all children completed successfully.
    """
    log("Running integration check", "INFO", depth)
    
    if not spec.path:
        return True
    
    children_dir = spec.path.parent / "children"
    if not children_dir.exists():
        return True
    
    all_complete = True
    for child_dir in children_dir.iterdir():
        if child_dir.is_dir():
            child_spec_path = child_dir / "spec.json"
            if child_spec_path.exists():
                try:
                    child_spec = load_spec(child_spec_path)
                    if child_spec.status != "complete":
                        log(f"Child {child_spec.name} not complete: {child_spec.status}", "WARN", depth)
                        all_complete = False
                except Exception as e:
                    log(f"Error loading child spec: {e}", "ERROR", depth)
                    all_complete = False
    
    if all_complete:
        log("All children complete - integration passed", "SUCCESS", depth)
    
    return all_complete


# =============================================================================
# MAIN RECURSIVE LOGIC
# =============================================================================

async def ralph_recursive(spec_path: Path, depth: int = 0) -> bool:
    """Main recursive entry point."""
    log(f"Processing: {spec_path.parent.name}", "INFO", depth)
    
    safe, reason = check_safety("recursive", depth)
    if not safe:
        log(f"Safety: {reason}", "ERROR", depth)
        return False
    
    try:
        spec = load_spec(spec_path)
    except Exception as e:
        log(f"Load failed: {e}", "ERROR", depth)
        return False
    
    spec.depth = depth
    spec.status = "in_progress"
    save_spec(spec)
    
    # Process any pending messages first
    process_messages(spec, depth)
    
    # Determine structure if undecided
    if spec.is_leaf is None:
        log("Structure undecided - running architecture loop", "ARCH", depth)
        if not await run_architecture_loop(spec, depth):
            return False
        spec = load_spec(spec_path)
    
    leaf = spec.is_leaf
    
    # === NON-LEAF: scaffold and recurse ===
    if leaf is False:
        children_dir = spec_path.parent / "children"
        if not children_dir.exists() or not any(children_dir.iterdir()):
            scaffold_children(spec, depth)
        
        # Process shared/ first (other children depend on it)
        shared_path = children_dir / "shared" / "spec.json"
        if shared_path.exists():
            log("Processing shared/ first", "INFO", depth)
            if not await ralph_recursive(shared_path, depth + 1):
                return False
            
            # Notify siblings that shared is ready
            for child_def in spec.children:
                if child_def.name != "shared":
                    child_dir = children_dir / child_def.name
                    if child_dir.exists():
                        send_message(
                            spec_path.parent,
                            child_dir,
                            "proceed",
                            {"dependency": "shared", "status": "complete"}
                        )
        
        # Process other children
        for child_def in spec.children:
            if child_def.name == "shared":
                continue
            child_path = children_dir / child_def.name / "spec.json"
            if child_path.exists():
                if not await ralph_recursive(child_path, depth + 1):
                    if CONFIG.pause_on_error:
                        return False
        
        # Integration check
        if await run_integration_tests(spec, depth):
            spec = load_spec(spec_path)
            spec.integration_tests_passed = True
            spec.status = "complete"
            save_spec(spec)
            return True
        else:
            return False
    
    # === LEAF: run implementation loop ===
    else:
        success = await run_implementation_loop(spec, depth)
        spec = load_spec(spec_path)
        spec.status = "complete" if success else "failed"
        save_spec(spec)
        return success


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Ralph-Recursive v2 (Agent SDK)")
    parser.add_argument("--spec", required=True, help="Path to spec.json")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without executing")
    parser.add_argument("--live", action="store_true", help="Actually call Agent SDK")
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--max-arch-iterations", type=int, default=5)
    parser.add_argument("--max-agents", type=int, default=50)
    parser.add_argument("--confirm-each", action="store_true", help="Confirm each agent spawn")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--model", default="claude-opus-4-5-20251101")
    
    args = parser.parse_args()
    
    CONFIG.max_depth = args.max_depth
    CONFIG.max_iterations = args.max_iterations
    CONFIG.max_arch_iterations = args.max_arch_iterations
    CONFIG.max_total_agents = args.max_agents
    CONFIG.confirm_each_level = args.confirm_each
    CONFIG.dry_run = args.dry_run
    CONFIG.live = args.live
    CONFIG.pause_on_error = not args.continue_on_error
    CONFIG.model = args.model
    
    spec_path = Path(args.spec)
    mode = "DRY RUN" if CONFIG.dry_run else ("LIVE" if CONFIG.live else "SIMULATED")
    
    print("=" * 60)
    print(f"RALPH-RECURSIVE v2 [Agent SDK] [{mode}]")
    print("=" * 60)
    print(f"Spec:            {spec_path}")
    print(f"Max Depth:       {CONFIG.max_depth}")
    print(f"Max Arch Iters:  {CONFIG.max_arch_iterations}")
    print(f"Max Impl Iters:  {CONFIG.max_iterations}")
    print(f"Max Agents:      {CONFIG.max_total_agents}")
    
    style = load_style_guide()
    print(f"Style Guide:     {'Loaded' if style else 'Not found'}")
    
    if CONFIG.live:
        print(f"Model:           {CONFIG.model}")
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        print(f"API Key:         {'Set' if key else 'NOT SET!'}")
    print("=" * 60)
    
    if CONFIG.live and not os.environ.get("ANTHROPIC_API_KEY"):
        print("\nERROR: Set ANTHROPIC_API_KEY environment variable")
        sys.exit(1)
    
    try:
        success = asyncio.run(ralph_recursive(spec_path))
        print(f"\n{'='*60}")
        print(f"Result:  {'SUCCESS' if success else 'FAILED'}")
        print(f"Agents:  {CONFIG.agents_spawned}")
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
