"""
Agent management for the Ralph pipeline.
"""

from .roles import (
    AgentRole,
    Team,
    RoleConfig,
    ROLE_TEAMS,
    ROLE_CONFIGS,
    get_role_config,
    get_team_roles,
    get_role_team,
    load_system_prompt,
)

from .context import (
    AgentContext,
    SiblingStatus,
    build_agent_context,
    build_initial_prompt,
)

from .invoker import (
    AgentResult,
    AgentInvoker,
    invoke_agent,
)

__all__ = [
    # Roles
    "AgentRole",
    "Team",
    "RoleConfig",
    "ROLE_TEAMS",
    "ROLE_CONFIGS",
    "get_role_config",
    "get_team_roles",
    "get_role_team",
    "load_system_prompt",
    # Context
    "AgentContext",
    "SiblingStatus",
    "build_agent_context",
    "build_initial_prompt",
    # Invoker
    "AgentResult",
    "AgentInvoker",
    "invoke_agent",
]
