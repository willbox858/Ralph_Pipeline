#!/usr/bin/env python3
"""
Stub approval types - Data classes for stub file metadata.
Location: src/stub_approval/types.py
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class StubInfo:
    """Metadata about a stub file.

    Attributes:
        path: Absolute path to the stub file.
        name: File name without directory.
        size: File size in bytes.
        last_modified: When the file was last modified.
    """
    path: Path
    name: str
    size: int
    last_modified: datetime
