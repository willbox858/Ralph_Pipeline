"""Scaffold phase module for orchestrator integration.

This module provides the scaffold phase functionality that can be integrated
into the orchestrator workflow. It generates stub files from spec interfaces
and structure, then waits for human approval before proceeding.

Exports:
    ScaffoldPhase: Enum with SCAFFOLD value
    run_scaffold: Async function to run scaffold generation
    await_stub_approval: Function to check stub approval status
    ScaffoldResult: Result of scaffold phase execution
    HibernationRequest: Returned when awaiting approval
    ApprovalGrant: Returned when stubs are approved
"""
from .approval import await_stub_approval
from .phase import ScaffoldPhase
from .runner import run_scaffold
from .types import ApprovalGrant, HibernationRequest, ScaffoldResult

__all__ = [
    "ScaffoldPhase",
    "run_scaffold",
    "await_stub_approval",
    "ScaffoldResult",
    "HibernationRequest",
    "ApprovalGrant",
]
