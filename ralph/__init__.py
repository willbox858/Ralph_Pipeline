"""
Ralph Pipeline v2

A programmatic pipeline for orchestrating LLM agents in software development.

Key components:
- core: Domain types (Spec, Phase, Message, etc.)
- orchestrator: Pipeline coordination and state management
- agents: Agent roles, context, and invocation
- messaging: Inter-agent communication
- hooks: Scope enforcement and message injection
- tools: Tool registry and MCP configuration
- validation: Schema validation
- mcp_server: MCP server for Interface Agent
"""

__version__ = "2.0.0"

from .core import (
    # Phase
    Phase,
    can_transition,
    is_approval_phase,
    # Spec
    Spec,
    TechStack,
    Constraints,
    create_spec,
    # Message
    Message,
    MessageType,
    # Errors
    ErrorReport,
    RalphError,
)

from .orchestrator import (
    Orchestrator,
    PipelineConfig,
    PipelineStatus,
    init_orchestrator,
    get_orchestrator,
)

from .agents import (
    AgentRole,
    Team,
    AgentInvoker,
)

from .tools import (
    ToolRegistry,
    get_tool_registry,
)

__all__ = [
    # Version
    "__version__",
    # Phase
    "Phase",
    "can_transition",
    "is_approval_phase",
    # Spec
    "Spec",
    "TechStack",
    "Constraints",
    "create_spec",
    # Message
    "Message",
    "MessageType",
    # Errors
    "ErrorReport",
    "RalphError",
    # Orchestrator
    "Orchestrator",
    "PipelineConfig",
    "PipelineStatus",
    "init_orchestrator",
    "get_orchestrator",
    # Agents
    "AgentRole",
    "Team",
    "AgentInvoker",
    # Tools
    "ToolRegistry",
    "get_tool_registry",
]
