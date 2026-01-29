#!/usr/bin/env python3
"""
Stub approval module - Tools for reviewing and approving generated stubs.

This module provides:
- StubInfo: Dataclass for stub file metadata
- list_stubs(): List stub files defined in a spec
- read_stub(): Read stub file content
- approve_stubs(): Mark stubs as approved
- get_approval_status(): Check approval status
"""

from .types import StubInfo
from .reviewer import (
    list_stubs,
    read_stub,
    approve_stubs,
    get_approval_status,
)

__all__ = [
    "StubInfo",
    "list_stubs",
    "read_stub",
    "approve_stubs",
    "get_approval_status",
]
