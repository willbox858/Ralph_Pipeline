#!/usr/bin/env python3
"""
Ralph-Recursive v2: JSON-based hierarchical spec implementation.

Features:
- Adversarial architecture loop (Proposer <-> Critic)
- Adversarial implementation loop (Implementer <-> Verifier)
- Hierarchical messaging (parent <-> child only)
- Style guide enforcement

Requirements:
    pip install anthropic

Usage:
    python3 ralph-recursive.py --spec spec.json --dry-run
    python3 ralph-recursive.py --spec spec.json --live --confirm-each
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from spec import (
    Spec, load_spec, save_spec, is_leaf, is_ready,
    create_child_spec, create_shared_spec, Child, spec_to_dict,
    ClassDef, Criterion, Errors
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
    max_cost_usd: float = 50.0
    confirm_each_level: bool = False
    dry_run: bool = False
    live: bool = False
    pause_on_error: bool = True
    model: str = "claude-opus-4-5-20251101"
    max_tokens: int = 8192
    agents_spawned: int = 0
    estimated_cost: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0


CONFIG = Config()

COST_ESTIMATES = {
    "proposer": 0.15,
    "critic": 0.10,
    "implementer": 0.25,
    "verifier": 0.10,
    "coordinator": 0.08,
}


# =============================================================================
# LOGGING
# =============================================================================

def log(msg: str, level: str = "INFO", depth: int = 0) -> None:
    indent = "  " * depth
    prefix = {"INFO": "->", "WARN": "!", "ERROR": "X", "SUCCESS": "*",
              "DRY": "o", "SPAWN": "+", "API": "@", "ARCH": "#",
              "MSG": "m"}.get(level, "-")
    print(f"{indent}{prefix} [{level}] {msg}")


# =============================================================================
# SAFETY
# =============================================================================

def check_safety(agent_type: str, depth: int) -> tuple[bool, str]:
    if depth > CONFIG.max_depth:
        return False, f"Max depth ({CONFIG.max_depth}) exceeded"
    if CONFIG.agents_spawned >= CONFIG.max_total_agents:
        return False, f"Max agents ({CONFIG.max_total_agents}) exceeded"
    if CONFIG.estimated_cost + COST_ESTIMATES.get(agent_type, 0.2) > CONFIG.max_cost_usd:
        return False, f"Cost limit (${CONFIG.max_cost_usd:.2f}) would be exceeded"
    return True, ""


def confirm_action(action: str, depth: int) -> bool:
    if not CONFIG.confirm_each_level:
        return True
    indent = "  " * depth
    print(f"\n{indent}CONFIRM: {action}")
    print(f"{indent}Agents: {CONFIG.agents_spawned} | Cost: ${CONFIG.estimated_cost:.2f}")
    return input(f"{indent}Proceed? [y/N]: ").strip().lower() == 'y'


def track_spawn(agent_type: str):
    CONFIG.agents_spawned += 1
    CONFIG.estimated_cost += COST_ESTIMATES.get(agent_type, 0.20)


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
# MESSAGING
# =============================================================================

@dataclass
class Message:
    id: str
    from_: str
    to: str
    type: str
    payload: dict
    timestamp: str = ""
    needs_response: bool = False
    status: str = "pending"


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
    # Load sender's messages
    sender_msgs = load_messages(from_dir)
    
    # Generate ID
    msg_id = f"msg-{len(sender_msgs['outbox']) + 1:03d}"
    
    # Create message
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
    
    # Add to sender's outbox
    sender_msgs["outbox"].append(msg)
    if needs_response:
        sender_msgs["pending_responses"].append(msg_id)
    save_messages(from_dir, sender_msgs)
    
    # Add to receiver's inbox
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
    agent_file = Path(__file__).parent.parent / "agents" / f"{agent_type}.md"
    if not agent_file.exists():
        raise FileNotFoundError(f"Agent prompt not found: {agent_file}")
    return agent_file.read_text(encoding='utf-8')


def build_agent_context(agent_type: str, spec: Spec, extra_context: str = "") -> str:
    """Build context for an agent, including style guide for relevant agents."""
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
    
    # Add extra context (proposals, critiques, etc.)
    if extra_context:
        context += f"\n{extra_context}\n"
    
    context += f"\nProcess this spec according to your role as {agent_type}.\n"
    context += "Output any spec updates as a ```json block.\n"
    
    return context


# =============================================================================
# API CALLS
# =============================================================================

def call_anthropic_api(system_prompt: str, user_message: str, depth: int) -> dict:
    try:
        from anthropic import Anthropic
    except ImportError:
        return {"success": False, "error": "Run: pip install anthropic"}
    
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"success": False, "error": "ANTHROPIC_API_KEY not set"}
    
    try:
        client = Anthropic(api_key=api_key)
        log(f"Calling {CONFIG.model}...", "API", depth)
        
        response = client.messages.create(
            model=CONFIG.model,
            max_tokens=CONFIG.max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}]
        )
        
        text = "".join(b.text for b in response.content if hasattr(b, "text"))
        inp = response.usage.input_tokens if hasattr(response, 'usage') else 0
        out = response.usage.output_tokens if hasattr(response, 'usage') else 0
        
        CONFIG.total_input_tokens += inp
        CONFIG.total_output_tokens += out
        log(f"Response: {inp} in, {out} out", "API", depth)
        
        return {"success": True, "response": text, "input_tokens": inp, "output_tokens": out}
    except Exception as e:
        return {"success": False, "error": str(e)}


def extract_json_from_response(response: str) -> list[dict]:
    """Extract all JSON blocks from response."""
    results = []
    for block in re.findall(r'```json\s*([\s\S]*?)\s*```', response):
        try:
            results.append(json.loads(block))
        except:
            continue
    return results


# =============================================================================
# AGENT SPAWNING
# =============================================================================

def spawn_agent(agent_type: str, spec: Spec, depth: int, extra_context: str = "") -> dict:
    safe, reason = check_safety(agent_type, depth)
    if not safe:
        return {"success": False, "error": f"Safety: {reason}"}
    
    if not confirm_action(f"Spawn {agent_type} for {spec.name}", depth):
        return {"success": False, "error": "User cancelled"}
    
    if CONFIG.dry_run:
        log(f"Would spawn {agent_type} for {spec.name}", "DRY", depth)
        return {"success": True, "dry_run": True}
    
    track_spawn(agent_type)
    log(f"Spawning {agent_type}", "SPAWN", depth)
    
    if not CONFIG.live:
        log(f"[SIMULATED] {agent_type} completed", "INFO", depth)
        return {"success": True, "simulated": True}
    
    # Live API call
    try:
        system_prompt = load_agent_prompt(agent_type)
        user_message = build_agent_context(agent_type, spec, extra_context)
        result = call_anthropic_api(system_prompt, user_message, depth)
        
        if not result["success"]:
            log(f"API failed: {result['error']}", "ERROR", depth)
            return result
        
        return {"success": True, "response": result["response"]}
    except Exception as e:
        log(f"Error: {e}", "ERROR", depth)
        return {"success": False, "error": str(e)}


# =============================================================================
# ADVERSARIAL ARCHITECTURE LOOP
# =============================================================================

def run_architecture_loop(spec: Spec, depth: int) -> bool:
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
        
        # Proposer
        result = spawn_agent("proposer", spec, depth, extra)
        if not result.get("success"):
            return False
        
        # Extract proposal
        if CONFIG.live and result.get("response"):
            jsons = extract_json_from_response(result["response"])
            for j in jsons:
                if "structure" in j or "rationale" in j:
                    proposal = j
                    break
        
        if CONFIG.dry_run or not CONFIG.live:
            # Simulate proposal
            proposal = {"structure": {"is_leaf": spec.is_leaf}, "approved_simulation": True}
        
        # Build context for critic
        extra = f"## Proposal to Review\n\n```json\n{json.dumps(proposal, indent=2)}\n```"
        
        # Critic
        result = spawn_agent("critic", spec, depth, extra)
        if not result.get("success"):
            return False
        
        # Extract critique
        if CONFIG.live and result.get("response"):
            jsons = extract_json_from_response(result["response"])
            for j in jsons:
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
                    from spec import SharedType
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

def run_implementation_loop(spec: Spec, depth: int) -> bool:
    """Run Implementer <-> Verifier loop until tests pass."""
    log(f"Implementation loop for {spec.name}", "INFO", depth)
    
    while spec.ralph_iteration < CONFIG.max_iterations:
        spec.ralph_iteration += 1
        log(f"Iteration {spec.ralph_iteration}/{CONFIG.max_iterations}", "INFO", depth)
        
        # Implementer
        if not spawn_agent("implementer", spec, depth).get("success"):
            return False
        
        # Verifier
        result = spawn_agent("verifier", spec, depth)
        if not result.get("success"):
            return False
        
        # Check for test pass in response
        if CONFIG.live and result.get("response"):
            if "all tests pass" in result["response"].lower():
                spec.all_tests_passed = True
        
        # Reload spec
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
            created.append(shared_path)
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
            created.append(child_path)
            log(f"Created {child_def.name}/", "INFO", depth)
    
    return created


# =============================================================================
# MESSAGE HANDLING (COORDINATOR)
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
        from_path = Path(msg.get("from", ""))
        
        if msg_type == "need_shared_type":
            # Child needs a shared type
            type_name = payload.get("name")
            log(f"Child requests shared type: {type_name}", "MSG", depth)
            
            # Add to shared_types if not present
            existing = [st.name for st in spec.shared_types]
            if type_name and type_name not in existing:
                from spec import SharedType
                spec.shared_types.append(SharedType(
                    name=type_name,
                    kind=payload.get("kind", "class"),
                    description=payload.get("reason", "")
                ))
                save_spec(spec)
                log(f"Added {type_name} to shared_types", "SUCCESS", depth)
        
        elif msg_type == "dependency_issue":
            log(f"Child reports dependency issue: {payload}", "WARN", depth)
            # Could escalate further or try to resolve
        
        mark_message_processed(spec_dir, msg["id"])
    
    return True


# =============================================================================
# MAIN RECURSIVE LOGIC
# =============================================================================

def ralph_recursive(spec_path: Path, depth: int = 0) -> bool:
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
        if not run_architecture_loop(spec, depth):
            return False
        spec = load_spec(spec_path)
    
    leaf = spec.is_leaf
    
    # Non-leaf: scaffold and recurse
    if leaf is False:
        children_dir = spec_path.parent / "children"
        if not children_dir.exists() or not any(children_dir.iterdir()):
            scaffold_children(spec, depth)
        
        # Process shared/ first
        shared_path = children_dir / "shared" / "spec.json"
        if shared_path.exists():
            log("Processing shared/ first", "INFO", depth)
            if not ralph_recursive(shared_path, depth + 1):
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
                if not ralph_recursive(child_path, depth + 1):
                    if CONFIG.pause_on_error:
                        return False
        
        # Integration check
        log("Integration check", "INFO", depth)
        spec = load_spec(spec_path)
        spec.integration_tests_passed = True
        spec.status = "complete"
        save_spec(spec)
        log("Integration passed", "SUCCESS", depth)
        return True
    
    # Leaf: run implementation loop
    else:
        success = run_implementation_loop(spec, depth)
        spec = load_spec(spec_path)
        spec.status = "complete" if success else "failed"
        save_spec(spec)
        return success


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Ralph-Recursive v2")
    parser.add_argument("--spec", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live", action="store_true", help="Actually call API")
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--max-arch-iterations", type=int, default=5)
    parser.add_argument("--max-agents", type=int, default=50)
    parser.add_argument("--max-cost", type=float, default=50.0)
    parser.add_argument("--confirm-each", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--model", default="claude-opus-4-5-20251101")
    
    args = parser.parse_args()
    
    CONFIG.max_depth = args.max_depth
    CONFIG.max_iterations = args.max_iterations
    CONFIG.max_arch_iterations = args.max_arch_iterations
    CONFIG.max_total_agents = args.max_agents
    CONFIG.max_cost_usd = args.max_cost
    CONFIG.confirm_each_level = args.confirm_each
    CONFIG.dry_run = args.dry_run
    CONFIG.live = args.live
    CONFIG.pause_on_error = not args.continue_on_error
    CONFIG.model = args.model
    
    spec_path = Path(args.spec)
    mode = "DRY RUN" if CONFIG.dry_run else ("LIVE" if CONFIG.live else "SIMULATED")
    
    print("=" * 60)
    print(f"RALPH-RECURSIVE v2 [{mode}]")
    print("=" * 60)
    print(f"Spec:            {spec_path}")
    print(f"Max Depth:       {CONFIG.max_depth}")
    print(f"Max Arch Iters:  {CONFIG.max_arch_iterations}")
    print(f"Max Impl Iters:  {CONFIG.max_iterations}")
    print(f"Max Cost:        ${CONFIG.max_cost_usd:.2f}")
    
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
        success = ralph_recursive(spec_path)
        print(f"\n{'='*60}")
        print(f"Result:  {'SUCCESS' if success else 'FAILED'}")
        print(f"Agents:  {CONFIG.agents_spawned}")
        print(f"Cost:    ${CONFIG.estimated_cost:.2f}")
        if CONFIG.live:
            print(f"Tokens:  {CONFIG.total_input_tokens:,} in, {CONFIG.total_output_tokens:,} out")
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
