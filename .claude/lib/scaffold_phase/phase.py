"""Scaffold phase enum."""
from enum import Enum


class ScaffoldPhase(str, Enum):
    """Enum with SCAFFOLD value for orchestrator Phase enum.

    Positioned between ARCHITECTURE and IMPLEMENTATION.
    Value 'scaffold' matches the lowercase pattern of other phases.
    """

    SCAFFOLD = "scaffold"
