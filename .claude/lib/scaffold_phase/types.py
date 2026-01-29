"""Scaffold phase type definitions."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ScaffoldResult:
    """Result of scaffold phase execution.

    Attributes:
        success: Whether scaffold generation succeeded
        generated_files: List of generated stub file paths
        error: Error message if success is False
    """

    success: bool
    generated_files: tuple = ()
    error: Optional[str] = None


@dataclass(frozen=True)
class HibernationRequest:
    """Returned when spec needs human approval before proceeding.

    Attributes:
        reason: Why the spec is waiting
        spec_path: Path to the spec that needs approval
    """

    reason: str
    spec_path: str


@dataclass(frozen=True)
class ApprovalGrant:
    """Returned when stubs are approved and implementation can proceed."""

    pass
