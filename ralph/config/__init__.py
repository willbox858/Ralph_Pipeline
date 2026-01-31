"""
Configuration system for the Ralph pipeline.

Allows projects to customize tool/MCP configuration via ralph.config.json
without modifying the Ralph submodule.
"""

from .loader import (
    MergedConfig,
    load_project_config,
    merge_configs,
    get_merged_config,
)
from .defaults import (
    get_defaults,
    DEFAULT_ROLE_TOOLS,
)

__all__ = [
    "MergedConfig",
    "load_project_config",
    "merge_configs",
    "get_merged_config",
    "get_defaults",
    "DEFAULT_ROLE_TOOLS",
]
