"""
Agent context builder for the Ralph pipeline.

The AgentContext contains everything an agent needs to do its job:
- The spec it's working on
- Its role and permissions
- Pending messages
- Previous errors (if retrying)
- Tool configuration
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from pathlib import Path
import json

from ..core.spec import Spec, TechStack
from ..core.message import Message
from ..core.errors import ErrorReport
from ..core.phase import Phase
from .roles import AgentRole, get_role_config


@dataclass
class SiblingStatus:
    """Status of a sibling spec."""
    name: str
    phase: str
    is_complete: bool
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "phase": self.phase,
            "is_complete": self.is_complete,
        }


@dataclass
class AgentContext:
    """
    Context provided to an agent when invoked.
    
    This is serialized to JSON and passed via environment variable
    so hooks can access it.
    """
    
    # Identity
    spec_id: str
    spec_name: str
    role: AgentRole
    
    # Current state
    current_phase: Phase
    iteration: int
    max_iterations: int
    
    # Spec details
    problem: str
    success_criteria: str
    context_info: str = ""
    
    # Interfaces (for implementer/verifier)
    provides: List[Dict] = field(default_factory=list)
    requires: List[Dict] = field(default_factory=list)
    shared_types: List[Dict] = field(default_factory=list)
    
    # Structure (for implementer)
    classes: List[Dict] = field(default_factory=list)
    dependencies: List[Dict] = field(default_factory=list)
    
    # Criteria
    acceptance_criteria: List[Dict] = field(default_factory=list)
    edge_cases: List[Dict] = field(default_factory=list)
    
    # Tech stack
    tech_stack: Optional[Dict] = None
    
    # Permissions
    allowed_paths: List[str] = field(default_factory=list)
    forbidden_paths: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    
    # Tool configuration
    build_command: str = ""
    test_command: str = ""
    lint_command: str = ""
    
    # Messages
    pending_messages: List[Dict] = field(default_factory=list)
    
    # Errors (for retry iterations)
    previous_errors: List[Dict] = field(default_factory=list)
    
    # Siblings (for coordination)
    sibling_status: List[SiblingStatus] = field(default_factory=list)
    
    # Parent spec (for context)
    parent_spec: Optional[Dict] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "spec_id": self.spec_id,
            "spec_name": self.spec_name,
            "role": self.role.value,
            "current_phase": self.current_phase.value,
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "problem": self.problem,
            "success_criteria": self.success_criteria,
            "context_info": self.context_info,
            "provides": self.provides,
            "requires": self.requires,
            "shared_types": self.shared_types,
            "classes": self.classes,
            "dependencies": self.dependencies,
            "acceptance_criteria": self.acceptance_criteria,
            "edge_cases": self.edge_cases,
            "tech_stack": self.tech_stack,
            "allowed_paths": self.allowed_paths,
            "forbidden_paths": self.forbidden_paths,
            "allowed_tools": self.allowed_tools,
            "build_command": self.build_command,
            "test_command": self.test_command,
            "lint_command": self.lint_command,
            "pending_messages": self.pending_messages,
            "previous_errors": self.previous_errors,
            "sibling_status": [s.to_dict() for s in self.sibling_status],
            "parent_spec": self.parent_spec,
        }
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_dict(cls, data: dict) -> "AgentContext":
        """Create from dictionary."""
        return cls(
            spec_id=data.get("spec_id", ""),
            spec_name=data.get("spec_name", ""),
            role=AgentRole(data.get("role", "implementer")),
            current_phase=Phase(data.get("current_phase", "implementation")),
            iteration=data.get("iteration", 0),
            max_iterations=data.get("max_iterations", 15),
            problem=data.get("problem", ""),
            success_criteria=data.get("success_criteria", ""),
            context_info=data.get("context_info", ""),
            provides=data.get("provides", []),
            requires=data.get("requires", []),
            shared_types=data.get("shared_types", []),
            classes=data.get("classes", []),
            dependencies=data.get("dependencies", []),
            acceptance_criteria=data.get("acceptance_criteria", []),
            edge_cases=data.get("edge_cases", []),
            tech_stack=data.get("tech_stack"),
            allowed_paths=data.get("allowed_paths", []),
            forbidden_paths=data.get("forbidden_paths", []),
            allowed_tools=data.get("allowed_tools", []),
            build_command=data.get("build_command", ""),
            test_command=data.get("test_command", ""),
            lint_command=data.get("lint_command", ""),
            pending_messages=data.get("pending_messages", []),
            previous_errors=data.get("previous_errors", []),
            sibling_status=[
                SiblingStatus(**s) for s in data.get("sibling_status", [])
            ],
            parent_spec=data.get("parent_spec"),
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> "AgentContext":
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))


def build_agent_context(
    spec: Spec,
    role: AgentRole,
    tech_stack: Optional[TechStack] = None,
    pending_messages: Optional[List[Message]] = None,
    previous_errors: Optional[List[ErrorReport]] = None,
    iteration: int = 1,
    allowed_paths: Optional[List[str]] = None,
    tool_config: Optional[Dict] = None,
    siblings: Optional[List[Spec]] = None,
    parent_spec: Optional[Spec] = None,
) -> AgentContext:
    """
    Build an AgentContext from a spec and configuration.
    
    Args:
        spec: The spec being worked on
        role: Agent role
        tech_stack: Tech stack configuration
        pending_messages: Messages to deliver to agent
        previous_errors: Errors from previous iterations
        iteration: Current iteration number
        allowed_paths: Paths agent can write to
        tool_config: Tool configuration from registry
        siblings: Sibling specs (for coordination)
        parent_spec: Parent spec (for context)
        
    Returns:
        AgentContext ready for serialization
    """
    role_config = get_role_config(role)
    tool_config = tool_config or {}
    
    # Build sibling status
    sibling_status = []
    if siblings:
        for sib in siblings:
            sibling_status.append(SiblingStatus(
                name=sib.name,
                phase=sib.phase.value,
                is_complete=sib.phase == Phase.COMPLETE,
            ))
    
    # Build parent spec dict (limited info for context)
    parent_dict = None
    if parent_spec:
        parent_dict = {
            "id": parent_spec.id,
            "name": parent_spec.name,
            "problem": parent_spec.problem,
            "shared_types": [t.to_dict() for t in parent_spec.shared_types],
        }
    
    return AgentContext(
        spec_id=spec.id,
        spec_name=spec.name,
        role=role,
        current_phase=spec.phase,
        iteration=iteration,
        max_iterations=spec.max_iterations,
        problem=spec.problem,
        success_criteria=spec.success_criteria,
        context_info=spec.context,
        provides=[i.to_dict() for i in spec.provides],
        requires=[i.to_dict() for i in spec.requires],
        shared_types=[t.to_dict() for t in spec.shared_types],
        classes=[c.to_dict() for c in spec.classes],
        dependencies=[d.to_dict() for d in spec.dependencies],
        acceptance_criteria=[c.to_dict() for c in spec.acceptance_criteria],
        edge_cases=[c.to_dict() for c in spec.edge_cases],
        tech_stack=tech_stack.to_dict() if tech_stack else None,
        allowed_paths=allowed_paths or spec.get_allowed_paths(),
        forbidden_paths=[],  # Could be populated from constraints
        allowed_tools=tool_config.get("allowed_tools", []),
        build_command=tool_config.get("build_command", ""),
        test_command=tool_config.get("test_command", ""),
        lint_command=tool_config.get("lint_command", ""),
        pending_messages=[m.to_dict() for m in (pending_messages or [])],
        previous_errors=[e.to_dict() for e in (previous_errors or [])],
        sibling_status=sibling_status,
        parent_spec=parent_dict,
    )


def build_initial_prompt(context: AgentContext) -> str:
    """
    Build the initial prompt for an agent from its context.
    
    This is what the agent sees when it starts.
    """
    lines = [
        f"# Task: {context.spec_name}",
        "",
        f"**Role:** {context.role.value}",
        f"**Phase:** {context.current_phase.value}",
        f"**Iteration:** {context.iteration}/{context.max_iterations}",
        "",
        "## Problem",
        context.problem,
        "",
        "## Success Criteria",
        context.success_criteria,
        "",
    ]
    
    if context.context_info:
        lines.extend([
            "## Additional Context",
            context.context_info,
            "",
        ])
    
    # Show pending messages
    if context.pending_messages:
        lines.append("## Pending Messages")
        lines.append("")
        for msg in context.pending_messages:
            lines.append(f"- **{msg.get('type', 'unknown')}** from {msg.get('from_id', 'unknown')}:")
            lines.append(f"  {json.dumps(msg.get('payload', {}), indent=2)}")
        lines.append("")
    
    # Show previous errors (for retry)
    if context.previous_errors:
        lines.append("## Previous Errors (Fix These!)")
        lines.append("")
        for err in context.previous_errors:
            lines.append(f"### Iteration {err.get('iteration', '?')}")
            lines.append(f"**{err.get('category', 'error')}:** {err.get('message', 'Unknown error')}")
            
            if err.get("compilation") and not err["compilation"].get("success", True):
                lines.append("")
                lines.append("**Compilation Errors:**")
                for ce in err["compilation"].get("errors", [])[:5]:
                    if isinstance(ce, dict):
                        lines.append(f"- {ce.get('file', '')}:{ce.get('line', '')}: {ce.get('message', '')}")
                    else:
                        lines.append(f"- {ce}")
            
            if err.get("tests") and err["tests"].get("failures"):
                lines.append("")
                lines.append("**Test Failures:**")
                for tf in err["tests"]["failures"][:5]:
                    if isinstance(tf, dict):
                        lines.append(f"- {tf.get('test_name', 'unknown')}: {tf.get('message', '')}")
                    else:
                        lines.append(f"- {tf}")
            
            lines.append("")
    
    # Show structure for implementer
    if context.role == AgentRole.IMPLEMENTER and context.classes:
        lines.append("## Files to Create/Modify")
        lines.append("")
        for cls in context.classes:
            lines.append(f"- `{cls.get('location', '')}`: {cls.get('name', '')} ({cls.get('kind', 'class')})")
            lines.append(f"  Responsibility: {cls.get('responsibility', '')}")
        lines.append("")
    
    # Show acceptance criteria
    if context.acceptance_criteria:
        lines.append("## Acceptance Criteria")
        lines.append("")
        for crit in context.acceptance_criteria:
            status = "✓" if crit.get("passed") else "○"
            lines.append(f"- [{status}] **{crit.get('id', '')}**: {crit.get('behavior', '')}")
        lines.append("")
    
    # Show tech stack
    if context.tech_stack:
        lines.append("## Tech Stack")
        lines.append(f"- Language: {context.tech_stack.get('language', 'Unknown')}")
        if context.tech_stack.get("runtime"):
            lines.append(f"- Runtime: {context.tech_stack['runtime']}")
        if context.tech_stack.get("frameworks"):
            lines.append(f"- Frameworks: {', '.join(context.tech_stack['frameworks'])}")
        lines.append("")
    
    # Show constraints
    lines.append("## Constraints")
    lines.append(f"- Allowed paths: {', '.join(context.allowed_paths) or 'None specified'}")
    if context.build_command:
        lines.append(f"- Build: `{context.build_command}`")
    if context.test_command:
        lines.append(f"- Test: `{context.test_command}`")
    lines.append("")
    
    return "\n".join(lines)
