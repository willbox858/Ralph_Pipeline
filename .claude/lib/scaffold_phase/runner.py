"""Scaffold phase runner."""
import json
import sys
from pathlib import Path

from .types import ScaffoldResult


def _setup_lib_paths() -> None:
    """Add sibling modules in .claude/lib/ to sys.path."""
    lib_dir = Path(__file__).parent.parent.resolve()  # .claude/lib/
    if str(lib_dir) not in sys.path:
        sys.path.insert(0, str(lib_dir))


_setup_lib_paths()


async def run_scaffold(spec_path: str) -> ScaffoldResult:
    """Run scaffold phase for a leaf spec.

    Generates stub files from spec.interfaces and spec.structure.classes
    using the PythonStubGenerator from scaffold-agent module.

    Args:
        spec_path: Path to the spec.json file

    Returns:
        ScaffoldResult with success status and list of generated files
    """
    try:
        # Import here to ensure path is set up
        from scaffold.python_stub_generator import PythonStubGenerator

        path = Path(spec_path)
        spec_dir = path.parent
        spec_data = json.loads(path.read_text(encoding="utf-8"))

        # Generate stubs
        generator = PythonStubGenerator()
        stubs = generator.generate_stubs(spec_data)

        if not stubs:
            return ScaffoldResult(success=True, generated_files=(), error=None)

        # Write stub files to spec directory
        generated = []
        for stub in stubs:
            output_path = spec_dir / stub.path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(stub.content, encoding="utf-8")
            generated.append(str(stub.path))

        return ScaffoldResult(success=True, generated_files=tuple(generated))
    except Exception as e:
        return ScaffoldResult(success=False, generated_files=(), error=str(e))
