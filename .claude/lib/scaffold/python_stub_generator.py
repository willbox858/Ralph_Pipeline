"""Python stub generator implementation."""
import re
import sys
import textwrap
from pathlib import Path
from typing import List, Optional, Tuple

# Add sibling shared module to path for imports
_shared_path = Path(__file__).parent.parent.parent.parent / "shared" / "src"
if str(_shared_path) not in sys.path:
    sys.path.insert(0, str(_shared_path))

from shared.stub_file import StubFile


class PythonStubGenerator:
    """Generates Python stub files from spec interfaces and structure.

    Produces type-annotated methods with docstrings and NotImplementedError bodies.
    Implements the StubGenerator protocol.
    """

    # Known type imports mapping
    TYPE_IMPORTS = {
        "List": "typing",
        "Dict": "typing",
        "Optional": "typing",
        "Tuple": "typing",
        "Set": "typing",
        "Protocol": "typing",
        "Any": "typing",
        "Union": "typing",
        "Callable": "typing",
        "Path": "pathlib",
        "StubFile": "shared.stub_file",
        "StubStatus": "shared.stub_status",
    }

    def generate_stubs(self, spec: dict) -> List[StubFile]:
        """Generate stub files from a spec.

        Args:
            spec: The spec dictionary containing interfaces and structure

        Returns:
            List of StubFile objects with path and content
        """
        stubs = []

        # Get classes from structure
        classes = spec.get("structure", {}).get("classes", [])

        for class_def in classes:
            stub = self._generate_class_stub(class_def, spec)
            if stub:
                stubs.append(stub)

        return stubs

    def _generate_class_stub(
        self, class_def: dict, spec: dict
    ) -> Optional[StubFile]:
        """Generate a stub for a single class/interface/module definition.

        Args:
            class_def: The class definition from structure.classes
            spec: The full spec for context

        Returns:
            StubFile or None if generation fails
        """
        name = class_def.get("name", "")
        class_type = class_def.get("type", "class")
        responsibility = class_def.get("responsibility", "")
        location = class_def.get("location", "")

        if not name or not location:
            return None

        # Find matching interface in provides (if any)
        interface_members = self._find_interface_members(name, spec)

        # Generate based on type
        if class_type == "interface":
            content = self._generate_protocol_stub(
                name, responsibility, interface_members
            )
        elif class_type == "module":
            content = self._generate_module_stub(
                name, responsibility, interface_members
            )
        else:
            # class, struct, etc. - generate as class
            content = self._generate_class_content(
                name, responsibility, interface_members
            )

        return StubFile(path=Path(location), content=content)

    def _find_interface_members(
        self, class_name: str, spec: dict
    ) -> List[dict]:
        """Find interface members for a class from spec.interfaces.provides.

        Args:
            class_name: Name of the class to find members for
            spec: The full spec

        Returns:
            List of member definitions
        """
        provides = spec.get("interfaces", {}).get("provides", [])

        for interface in provides:
            if interface.get("name") == class_name:
                return interface.get("members", [])

        return []

    def _generate_protocol_stub(
        self, name: str, responsibility: str, members: List[dict]
    ) -> str:
        """Generate a Protocol stub for an interface type.

        Args:
            name: Protocol name
            responsibility: Description of the protocol
            members: List of method definitions

        Returns:
            Generated Python code
        """
        imports = self._collect_imports(members)
        imports.add("from typing import Protocol")

        methods = []
        for member in members:
            method_code = self._generate_method_stub(member, is_protocol=True)
            methods.append(method_code)

        # If no members, add a placeholder
        if not methods:
            methods.append("    pass")

        imports_str = "\n".join(sorted(imports))
        methods_str = "\n\n".join(methods)

        lines = [
            f'"""{name} protocol."""',
            imports_str,
            "",
            "",
            f"class {name}(Protocol):",
            f'    """{responsibility}"""',
            "",
            methods_str,
        ]

        return "\n".join(lines) + "\n"

    def _generate_class_content(
        self, name: str, responsibility: str, members: List[dict]
    ) -> str:
        """Generate a class stub with NotImplementedError bodies.

        Args:
            name: Class name
            responsibility: Description of the class
            members: List of method definitions

        Returns:
            Generated Python code
        """
        imports = self._collect_imports(members)

        methods = []
        for member in members:
            method_code = self._generate_method_stub(member, is_protocol=False)
            methods.append(method_code)

        # If no members, add __init__ and pass
        if not methods:
            methods.append(
                '    def __init__(self) -> None:\n'
                '        """Initialize the instance."""\n'
                '        pass'
            )

        imports_str = "\n".join(sorted(imports)) if imports else ""
        methods_str = "\n\n".join(methods)

        lines = [f'"""{name} class."""']
        if imports_str:
            lines.append(imports_str)
        lines.extend([
            "",
            "",
            f"class {name}:",
            f'    """{responsibility}"""',
            "",
            methods_str,
        ])

        return "\n".join(lines) + "\n"

    def _generate_module_stub(
        self, name: str, responsibility: str, members: List[dict]
    ) -> str:
        """Generate a module stub with functions.

        Args:
            name: Module name (used in docstring)
            responsibility: Description of the module
            members: List of function definitions

        Returns:
            Generated Python code
        """
        imports = self._collect_imports(members)

        functions = []
        for member in members:
            func_code = self._generate_function_stub(member)
            functions.append(func_code)

        # If no members, add a placeholder function
        if not functions:
            functions.append(
                'def placeholder() -> None:\n'
                '    """Placeholder function."""\n'
                '    raise NotImplementedError()'
            )

        imports_str = "\n".join(sorted(imports)) if imports else ""
        functions_str = "\n\n\n".join(functions)

        lines = [
            f'"""{name} module.',
            "",
            f"{responsibility}",
            '"""',
        ]
        if imports_str:
            lines.append(imports_str)
            lines.append("")
        lines.append("")
        lines.append(functions_str)

        return "\n".join(lines) + "\n"

    def _generate_method_stub(self, member: dict, is_protocol: bool) -> str:
        """Generate a method stub.

        Args:
            member: Method definition with name, signature, expectations
            is_protocol: If True, use '...' body; otherwise NotImplementedError

        Returns:
            Generated method code (indented)
        """
        name = member.get("name", "method")
        signature = member.get("signature", "(self) -> None")
        expectations = member.get("expectations", "")

        params, return_type = self._parse_signature(signature)

        # Ensure 'self' is first param for methods
        if not params.startswith("self"):
            params = f"self, {params}" if params else "self"

        body = "..." if is_protocol else "raise NotImplementedError()"
        docstring = expectations if expectations else f"{name} method."

        return textwrap.indent(textwrap.dedent(f'''\
            def {name}({params}) -> {return_type}:
                """{docstring}"""
                {body}'''), "    ")

    def _generate_function_stub(self, member: dict) -> str:
        """Generate a module-level function stub.

        Args:
            member: Function definition with name, signature, expectations

        Returns:
            Generated function code (not indented)
        """
        name = member.get("name", "function")
        signature = member.get("signature", "() -> None")
        expectations = member.get("expectations", "")

        params, return_type = self._parse_signature(signature)
        docstring = expectations if expectations else f"{name} function."

        return textwrap.dedent(f'''\
            def {name}({params}) -> {return_type}:
                """{docstring}"""
                raise NotImplementedError()''')

    def _parse_signature(self, signature: str) -> Tuple[str, str]:
        """Parse a signature string into params and return type.

        Args:
            signature: String like '(a: int, b: str) -> bool'

        Returns:
            Tuple of (params_string, return_type_string)
        """
        signature = signature.strip()

        # Match (params) -> return_type pattern
        match = re.match(r"\(([^)]*)\)\s*(?:->\s*(.+))?", signature)

        if match:
            params = match.group(1).strip() if match.group(1) else ""
            return_type = match.group(2).strip() if match.group(2) else "None"
            return params, return_type

        return "", "None"

    def _collect_imports(self, members: List[dict]) -> set:
        """Collect required imports from member signatures.

        Args:
            members: List of member definitions

        Returns:
            Set of import statements
        """
        imports = set()

        for member in members:
            signature = member.get("signature", "")

            # Check for known types in signature
            for type_name, module in self.TYPE_IMPORTS.items():
                if type_name in signature:
                    if module == "typing":
                        imports.add(f"from typing import {type_name}")
                    elif module == "pathlib":
                        imports.add(f"from pathlib import {type_name}")
                    else:
                        imports.add(f"from {module} import {type_name}")

        return imports
