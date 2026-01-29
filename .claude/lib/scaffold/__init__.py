"""Scaffold module for stub generation."""
from .stub_generator import StubGenerator
from .python_stub_generator import PythonStubGenerator
from .agent_templates import get_agent_config, get_agent_prompt

__all__ = [
    "StubGenerator",
    "PythonStubGenerator",
    "get_agent_config",
    "get_agent_prompt",
]
