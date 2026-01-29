"""StubFile dataclass for stub-generation-phase."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StubFile:
    """Represents a generated stub file.

    A value object containing the path where the stub should be written
    and the generated stub code content.

    Attributes:
        path: The file path where the stub should be written
        content: The generated stub code content
    """

    path: Path
    content: str
