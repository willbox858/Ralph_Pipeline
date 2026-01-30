"""
Agent Invoker for the Ralph pipeline.

Invokes Claude agents via the Claude Agent SDK with proper
configuration, tool access, and MCP servers.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime, timezone
import asyncio

from ..core.spec import Spec, TechStack
from ..core.message import Message, create_phase_complete_message
from ..core.errors import ErrorReport
from ..tools.registry import get_tool_registry
from .context import AgentContext, build_agent_context, build_initial_prompt
from .roles import AgentRole, load_system_prompt


@dataclass
class AgentResult:
    """Result of an agent invocation."""
    
    success: bool
    output: str = ""
    artifacts: List[str] = field(default_factory=list)
    messages: List[Message] = field(default_factory=list)
    error: Optional[str] = None
    duration_ms: int = 0
    cost_usd: Optional[float] = None
    session_id: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "output": self.output[:2000],
            "artifacts": self.artifacts,
            "messages": [m.to_dict() for m in self.messages],
            "error": self.error,
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
            "session_id": self.session_id,
        }


class AgentInvoker:
    """
    Invokes Claude agents via the Claude Agent SDK.
    
    Uses `claude_agent_sdk.query()` to run agents with:
    - Role-specific system prompts
    - Scoped tool access based on role and tech stack
    - MCP server configuration for Unity/Godot/etc.
    - Permission mode for autonomous operation
    """
    
    def __init__(
        self,
        project_root: Path,
        prompts_dir: Optional[Path] = None,
        dry_run: bool = False,
        permission_mode: str = "acceptEdits",
    ):
        """
        Initialize the invoker.
        
        Args:
            project_root: Root directory of the project
            prompts_dir: Directory containing agent prompts
            dry_run: If True, don't actually invoke agents
            permission_mode: SDK permission mode (acceptEdits, bypassPermissions, default)
        """
        self.project_root = project_root
        self.prompts_dir = prompts_dir or project_root / ".ralph" / "prompts"
        self.dry_run = dry_run
        self.permission_mode = permission_mode
        self.tool_registry = get_tool_registry()
        
        self._artifact_tracker: Dict[str, List[str]] = {}
    
    async def invoke(
        self,
        role: AgentRole,
        spec: Spec,
        tech_stack: Optional[TechStack] = None,
        pending_messages: Optional[List[Message]] = None,
        previous_errors: Optional[List[ErrorReport]] = None,
        iteration: int = 1,
        siblings: Optional[List[Spec]] = None,
        parent_spec: Optional[Spec] = None,
        timeout: float = 300.0,
    ) -> AgentResult:
        """
        Invoke an agent with the given role on a spec.
        
        Args:
            role: The agent role to invoke
            spec: The spec to work on
            tech_stack: Tech stack configuration
            pending_messages: Messages to deliver to agent
            previous_errors: Errors from previous iterations
            iteration: Current iteration number
            siblings: Sibling specs for coordination
            parent_spec: Parent spec for context
            timeout: Maximum execution time in seconds
            
        Returns:
            AgentResult with success status, output, artifacts, etc.
        """
        start_time = datetime.now(timezone.utc)
        
        tech_stack = tech_stack or spec.get_effective_tech_stack()
        language = tech_stack.language.lower() if tech_stack else "python"
        
        # Get tools for this role
        tool_config = self.tool_registry.get_tools_for_role(
            role=role.value,
            tech_stack=language,
            additional_mcp=tech_stack.mcp_tools if tech_stack else None,
        )
        
        # Build agent context and prompts
        context = build_agent_context(
            spec=spec,
            role=role,
            tech_stack=tech_stack,
            pending_messages=pending_messages,
            previous_errors=previous_errors,
            iteration=iteration,
            tool_config=tool_config,
            siblings=siblings,
            parent_spec=parent_spec,
        )
        
        system_prompt = load_system_prompt(role, self.prompts_dir)
        initial_prompt = build_initial_prompt(context)
        
        self._artifact_tracker[spec.id] = []
        
        if self.dry_run:
            return self._dry_run_result(role, spec, context)
        
        # Invoke via SDK
        result = await self._invoke_with_sdk(
            prompt=initial_prompt,
            system_prompt=system_prompt,
            tools=tool_config.get("builtin_tools", []),
            mcp_servers=tool_config.get("mcp_servers", []),
            timeout=timeout,
        )
        
        # Calculate duration if not provided by SDK
        if result.duration_ms == 0:
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            result.duration_ms = int(duration * 1000)
        
        result.artifacts = self._artifact_tracker.get(spec.id, [])
        
        return result
    
    async def _invoke_with_sdk(
        self,
        prompt: str,
        system_prompt: str,
        tools: List[str],
        mcp_servers: List[Dict[str, Any]],
        timeout: float,
    ) -> AgentResult:
        """
        Invoke using the Claude Agent SDK.
        
        Uses `claude_agent_sdk.query()` with ClaudeAgentOptions to
        stream messages as the agent works.
        """
        try:
            from claude_agent_sdk import (
                query,
                ClaudeAgentOptions,
                AssistantMessage,
                ResultMessage,
            )
        except ImportError:
            return AgentResult(
                success=False,
                output="",
                error="claude-agent-sdk not installed. Run: pip install claude-agent-sdk",
            )
        
        # Build MCP server config
        mcp_config: Dict[str, Dict[str, Any]] = {}
        for server in mcp_servers:
            name = server.get("name", "mcp")
            mcp_config[name] = {
                "command": server.get("command", ""),
                "args": server.get("args", []),
            }
            if server.get("env"):
                mcp_config[name]["env"] = server["env"]
        
        # Build options
        options = ClaudeAgentOptions(
            allowed_tools=tools,
            system_prompt=system_prompt,
            permission_mode=self.permission_mode,
            cwd=str(self.project_root),
            mcp_servers=mcp_config if mcp_config else None,
        )
        
        output_parts: List[str] = []
        artifacts: List[str] = []
        result_info: Dict[str, Any] = {}
        
        try:
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        # Handle text blocks
                        if hasattr(block, "text"):
                            output_parts.append(block.text)
                        # Handle tool use blocks
                        elif hasattr(block, "name"):
                            output_parts.append(f"[Tool: {block.name}]")
                            # Track file artifacts
                            if block.name in ("Write", "Edit") and hasattr(block, "input"):
                                file_path = block.input.get("file_path")
                                if file_path:
                                    artifacts.append(file_path)
                        # Handle tool result errors
                        elif hasattr(block, "is_error") and block.is_error:
                            output_parts.append(f"[Tool Error]")
                
                elif isinstance(message, ResultMessage):
                    result_info = {
                        "subtype": message.subtype,
                        "duration_ms": message.duration_ms,
                        "is_error": message.is_error,
                        "session_id": message.session_id,
                        "cost_usd": getattr(message, "total_cost_usd", None),
                    }
            
            success = not result_info.get("is_error", False)
            
            return AgentResult(
                success=success,
                output="\n".join(output_parts),
                artifacts=artifacts,
                duration_ms=result_info.get("duration_ms", 0),
                cost_usd=result_info.get("cost_usd"),
                session_id=result_info.get("session_id"),
                error=None if success else "Agent reported error",
            )
            
        except asyncio.TimeoutError:
            return AgentResult(
                success=False,
                output="\n".join(output_parts),
                artifacts=artifacts,
                error=f"Timeout after {timeout} seconds",
            )
        except Exception as e:
            return AgentResult(
                success=False,
                output="\n".join(output_parts),
                artifacts=artifacts,
                error=str(e),
            )
    
    def _dry_run_result(
        self,
        role: AgentRole,
        spec: Spec,
        context: AgentContext,
    ) -> AgentResult:
        """Return a dry-run result without invoking agent."""
        return AgentResult(
            success=True,
            output=f"[DRY RUN] Would invoke {role.value} for spec {spec.name}",
            artifacts=[],
            messages=[
                create_phase_complete_message(
                    spec.id,
                    context.current_phase.value,
                    success=True,
                    summary="Dry run completed",
                )
            ],
        )
    
    def track_artifact(self, spec_id: str, file_path: str) -> None:
        """Track an artifact created by an agent."""
        if spec_id not in self._artifact_tracker:
            self._artifact_tracker[spec_id] = []
        if file_path not in self._artifact_tracker[spec_id]:
            self._artifact_tracker[spec_id].append(file_path)
    
    def get_artifacts(self, spec_id: str) -> List[str]:
        """Get artifacts tracked for a spec."""
        return self._artifact_tracker.get(spec_id, [])
    
    def clear_artifacts(self, spec_id: str) -> None:
        """Clear artifact tracking for a spec."""
        self._artifact_tracker.pop(spec_id, None)


async def invoke_agent(
    role: AgentRole,
    spec: Spec,
    project_root: Path,
    **kwargs,
) -> AgentResult:
    """Convenience function to invoke an agent."""
    invoker = AgentInvoker(project_root)
    return await invoker.invoke(role, spec, **kwargs)
