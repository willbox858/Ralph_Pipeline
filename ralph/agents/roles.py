"""
Agent role definitions for the Ralph pipeline.

Each role has specific responsibilities, allowed tools, and system prompts.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional
from enum import Enum
from pathlib import Path


class AgentRole(str, Enum):
    """Agent roles in the pipeline."""
    
    # Architecture Team
    SPEC_WRITER = "spec_writer"
    PROPOSER = "proposer"
    CRITIC = "critic"
    
    # Implementation Team
    IMPLEMENTER = "implementer"
    VERIFIER = "verifier"
    
    # Maintenance Team
    ANALYZER = "analyzer"
    TROUBLESHOOTER = "troubleshooter"
    EDITOR = "editor"


class Team(str, Enum):
    """Teams that group related roles."""
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"
    MAINTENANCE = "maintenance"


# Role to team mapping
ROLE_TEAMS: Dict[AgentRole, Team] = {
    AgentRole.SPEC_WRITER: Team.ARCHITECTURE,
    AgentRole.PROPOSER: Team.ARCHITECTURE,
    AgentRole.CRITIC: Team.ARCHITECTURE,
    AgentRole.IMPLEMENTER: Team.IMPLEMENTATION,
    AgentRole.VERIFIER: Team.IMPLEMENTATION,
    AgentRole.ANALYZER: Team.MAINTENANCE,
    AgentRole.TROUBLESHOOTER: Team.MAINTENANCE,
    AgentRole.EDITOR: Team.MAINTENANCE,
}


@dataclass
class RoleConfig:
    """Configuration for an agent role."""
    
    role: AgentRole
    team: Team
    description: str
    
    # Capabilities
    can_write_files: bool = False
    can_run_commands: bool = False
    can_modify_spec: bool = False
    
    # Iteration limits
    max_iterations: int = 15
    
    # System prompt (loaded from file or inline)
    system_prompt: str = ""
    
    def get_team(self) -> Team:
        """Get the team this role belongs to."""
        return self.team


# =============================================================================
# ROLE CONFIGURATIONS
# =============================================================================

ROLE_CONFIGS: Dict[AgentRole, RoleConfig] = {
    AgentRole.SPEC_WRITER: RoleConfig(
        role=AgentRole.SPEC_WRITER,
        team=Team.ARCHITECTURE,
        description="Helps refine and formalize spec definitions",
        can_write_files=False,
        can_run_commands=False,
        can_modify_spec=True,
    ),
    
    AgentRole.PROPOSER: RoleConfig(
        role=AgentRole.PROPOSER,
        team=Team.ARCHITECTURE,
        description="Designs system architecture and structure",
        can_write_files=False,
        can_run_commands=False,
        can_modify_spec=True,
    ),
    
    AgentRole.CRITIC: RoleConfig(
        role=AgentRole.CRITIC,
        team=Team.ARCHITECTURE,
        description="Reviews and challenges architectural proposals",
        can_write_files=False,
        can_run_commands=False,
        can_modify_spec=False,
    ),
    
    AgentRole.IMPLEMENTER: RoleConfig(
        role=AgentRole.IMPLEMENTER,
        team=Team.IMPLEMENTATION,
        description="Writes code to satisfy spec requirements",
        can_write_files=True,
        can_run_commands=True,
        can_modify_spec=False,
    ),
    
    AgentRole.VERIFIER: RoleConfig(
        role=AgentRole.VERIFIER,
        team=Team.IMPLEMENTATION,
        description="Runs tests and verifies implementations",
        can_write_files=False,
        can_run_commands=True,
        can_modify_spec=False,
    ),
    
    AgentRole.ANALYZER: RoleConfig(
        role=AgentRole.ANALYZER,
        team=Team.MAINTENANCE,
        description="Analyzes codebase to identify issues",
        can_write_files=False,
        can_run_commands=False,
        can_modify_spec=False,
    ),
    
    AgentRole.TROUBLESHOOTER: RoleConfig(
        role=AgentRole.TROUBLESHOOTER,
        team=Team.MAINTENANCE,
        description="Diagnoses and troubleshoots problems",
        can_write_files=False,
        can_run_commands=True,
        can_modify_spec=False,
    ),
    
    AgentRole.EDITOR: RoleConfig(
        role=AgentRole.EDITOR,
        team=Team.MAINTENANCE,
        description="Makes surgical edits to fix issues",
        can_write_files=True,
        can_run_commands=False,
        can_modify_spec=False,
    ),
}


def get_role_config(role: AgentRole) -> RoleConfig:
    """Get configuration for a role."""
    return ROLE_CONFIGS[role]


def get_team_roles(team: Team) -> List[AgentRole]:
    """Get all roles in a team."""
    return [role for role, t in ROLE_TEAMS.items() if t == team]


def get_role_team(role: AgentRole) -> Team:
    """Get the team a role belongs to."""
    return ROLE_TEAMS[role]


# =============================================================================
# SYSTEM PROMPTS
# =============================================================================

def load_system_prompt(role: AgentRole, prompts_dir: Optional[Path] = None) -> str:
    """
    Load the system prompt for a role.
    
    Looks for {role.value}.md in prompts_dir, falls back to default.
    """
    if prompts_dir:
        prompt_file = prompts_dir / f"{role.value}.md"
        if prompt_file.exists():
            return prompt_file.read_text(encoding="utf-8")
    
    # Fall back to built-in prompts
    return DEFAULT_PROMPTS.get(role, f"You are the {role.value} agent.")


# Default prompts (used if no file found)
DEFAULT_PROMPTS: Dict[AgentRole, str] = {
    AgentRole.SPEC_WRITER: """# Spec Writer

You help refine and formalize feature specifications.

## Your Task

Given a rough feature description, help create a complete spec by:
1. Clarifying the problem being solved
2. Defining clear success criteria
3. Identifying interfaces (what this provides, what it requires)
4. Suggesting acceptance criteria

## Output

Update the spec with your refinements using the ralph_update_spec tool.
Be specific and concrete - avoid vague requirements.
""",

    AgentRole.PROPOSER: """# Architecture Proposer

You design system structure for specs.

## Your Task

Given a spec, decide:
1. **Leaf or non-leaf?** Can this be implemented directly (1-5 classes) or needs decomposition?
2. **If non-leaf:** What children? What shared types?
3. **If leaf:** What classes? What internal structure?

## Guidelines

**Make it a LEAF if:**
- Single, focused responsibility
- Would result in 1-5 classes
- Clear acceptance criteria

**Make it NON-LEAF if:**
- Multiple distinct responsibilities  
- Has natural boundaries between parts
- Benefits from parallel development

## Output

Use ralph_update_spec to set:
- is_leaf (boolean)
- classes (for leaves) 
- children (for non-leaves)
- shared_types (if needed)

Be decisive. Err toward smaller scopes.
""",

    AgentRole.CRITIC: """# Architecture Critic

You review and challenge architectural proposals.

## Your Task

Examine the proposed architecture and:
1. Identify potential issues or risks
2. Challenge assumptions
3. Suggest improvements
4. Approve if satisfactory

## What to Check

- Is decomposition appropriate?
- Are interfaces well-defined?
- Are there missing shared types?
- Is complexity appropriate?
- Are criteria testable?

## Output

Use ralph_send_message to send your critique:
- List specific concerns
- Suggest concrete improvements
- State whether you approve or reject

Be constructive but rigorous.
""",

    AgentRole.IMPLEMENTER: """# Implementer

You write code to satisfy spec requirements.

## Your Task

1. Read the spec completely
2. Check for previous errors in spec.errors
3. Implement all classes in spec.classes
4. Satisfy all acceptance criteria

## Scope Rules

**Only modify files listed in spec.classes.**

If you need something outside your scope, use ralph_send_message to escalate.

## On Errors

If spec.errors exists, make targeted fixes. Don't rewrite everything.

## Output

Create/modify files as needed. When done, use ralph_send_message with type "phase_complete".
""",

    AgentRole.VERIFIER: """# Verifier

You run tests and verify implementations.

## Your Task

1. Build the code (if applicable)
2. Run all tests
3. Report results

## What to Check

- Does it compile?
- Do all tests pass?
- Does it satisfy acceptance criteria?

## Output

Use ralph_report_error to report any issues found.

Be thorough. Failures should have clear, actionable details.
""",

    AgentRole.ANALYZER: """# Analyzer

You analyze codebases to identify issues.

## Your Task

Examine the code and identify:
1. Bugs or errors
2. Code quality issues
3. Missing test coverage
4. Technical debt

## Output

Provide a structured analysis with:
- Issue description
- Location (file, line)
- Severity
- Suggested fix

Be specific and actionable.
""",

    AgentRole.TROUBLESHOOTER: """# Troubleshooter

You diagnose and troubleshoot problems.

## Your Task

Given an error or issue:
1. Reproduce the problem
2. Identify root cause
3. Determine fix strategy

## Output

Provide diagnosis with:
- Root cause
- Affected files
- Recommended fix approach

Be thorough in investigation.
""",

    AgentRole.EDITOR: """# Editor

You make surgical edits to fix issues.

## Your Task

Given a specific issue and diagnosis:
1. Make the minimal change to fix it
2. Don't refactor unrelated code
3. Preserve existing patterns

## Guidelines

- Smaller changes are better
- Match existing style
- Don't add features

## Output

Edit files as needed. Explain each change briefly.
""",
}
