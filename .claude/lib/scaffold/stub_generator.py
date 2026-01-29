"""StubGenerator protocol for language-agnostic stub generation."""
import sys
from typing import List, Protocol

# Add sibling shared module to path for imports
from pathlib import Path
_shared_path = Path(__file__).parent.parent.parent.parent / "shared" / "src"
if str(_shared_path) not in sys.path:
    sys.path.insert(0, str(_shared_path))

from shared.stub_file import StubFile


class StubGenerator(Protocol):
    """Protocol defining stub generation interface.

    Language-agnostic contract for generating stub files from spec definitions.
    Implementers should parse the spec's interfaces and structure to produce
    type-annotated stub files appropriate for their target language.
    """

    def generate_stubs(self, spec: dict) -> List[StubFile]:
        """Generate stub files from a spec.

        Args:
            spec: The spec dictionary containing:
                - interfaces.provides: List of interface definitions with members
                - structure.classes: List of class/interface/module definitions

        Returns:
            List of StubFile objects, each containing:
                - path: Where the stub should be written
                - content: The generated stub code
        """
        ...
