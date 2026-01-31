"""
Hook system for the Ralph pipeline.

Provides scope enforcement and message injection via Claude Code hooks.
"""

from .scope import (
    normalize_path,
    is_path_allowed,
    is_tool_allowed,
    get_agent_context_from_env,
    get_allowed_paths_from_env,
    get_allowed_tools_from_env,
)

from .runner import (
    run_pre_tool_use,
    run_post_tool_use,
    run_on_stop,
    load_pending_messages,
    clear_pending_messages,
    track_artifact,
    log_tool_use,
)

from .sdk_hooks import (
    create_ralph_hooks,
    pre_tool_use_hook,
    post_tool_use_hook,
    post_tool_use_failure_hook,
    stop_hook,
)

__all__ = [
    # Scope
    "normalize_path",
    "is_path_allowed",
    "is_tool_allowed",
    "get_agent_context_from_env",
    "get_allowed_paths_from_env",
    "get_allowed_tools_from_env",
    # Runner
    "run_pre_tool_use",
    "run_post_tool_use",
    "run_on_stop",
    "load_pending_messages",
    "clear_pending_messages",
    "track_artifact",
    "log_tool_use",
    # SDK Hooks
    "create_ralph_hooks",
    "pre_tool_use_hook",
    "post_tool_use_hook",
    "post_tool_use_failure_hook",
    "stop_hook",
]
