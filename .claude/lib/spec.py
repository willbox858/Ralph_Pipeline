#!/usr/bin/env python3
"""
Spec library - Core functions for working with JSON specs.
Location: lib/spec.py
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class InterfaceMember:
    name: str
    signature: str
    expectations: str = ""


@dataclass
class Interface:
    name: str
    description: str = ""
    members: list[InterfaceMember] = field(default_factory=list)


@dataclass
class SharedType:
    name: str
    kind: str  # class, struct, interface, enum, type, record
    description: str = ""


@dataclass
class Child:
    name: str
    responsibility: str
    provides: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)


@dataclass
class ClassDef:
    name: str
    type: str  # class, interface, struct, enum, module, function
    responsibility: str
    location: str


@dataclass
class Criterion:
    id: str
    behavior: str
    test: str = ""
    passed: Optional[bool] = None


@dataclass
class Errors:
    iteration: int = 0
    timestamp: str = ""
    compilation_success: bool = True
    compilation_errors: list[str] = field(default_factory=list)
    test_total: int = 0
    test_passed: int = 0
    test_failed: int = 0
    test_failures: list[dict] = field(default_factory=list)


@dataclass 
class Spec:
    """Full spec representation."""
    name: str
    version: str = "1.0.0"
    status: str = "draft"
    author: str = ""
    created: str = ""
    updated: str = ""
    
    # Overview
    problem: str = ""
    success: str = ""
    context: str = ""
    
    # Interfaces
    provides: list[Interface] = field(default_factory=list)
    requires: list[dict] = field(default_factory=list)  # {name, source, usage}
    shared_types: list[SharedType] = field(default_factory=list)
    
    # Structure
    is_leaf: Optional[bool] = None
    children: list[Child] = field(default_factory=list)
    composition: str = ""
    classes: list[ClassDef] = field(default_factory=list)
    dependencies: list[dict] = field(default_factory=list)  # {component, depends_on, reason}
    
    # Criteria
    acceptance: list[Criterion] = field(default_factory=list)
    edge_cases: list[Criterion] = field(default_factory=list)
    integration: list[Criterion] = field(default_factory=list)
    
    # Constraints
    tech_stack: Optional[dict] = None  # {language, runtime, frameworks, rationale}
    scope_boundaries: list[str] = field(default_factory=list)
    performance: list[str] = field(default_factory=list)
    security: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    
    # Verification
    tests_passed: Optional[bool] = None
    lint_passed: Optional[bool] = None
    build_passed: Optional[bool] = None
    deviations: list[str] = field(default_factory=list)
    summary: str = ""
    
    # Runtime
    depth: int = 0
    ralph_iteration: int = 0
    all_tests_passed: bool = False
    integration_tests_passed: bool = False
    depends_on: list[str] = field(default_factory=list)
    errors: Optional[Errors] = None
    
    # Path tracking
    path: Optional[Path] = None


# =============================================================================
# LOADING / SAVING
# =============================================================================

def load_spec(spec_path: Path) -> Spec:
    """Load a spec from JSON file."""
    if not spec_path.exists():
        raise FileNotFoundError(f"Spec not found: {spec_path}")

    data = json.loads(spec_path.read_text(encoding='utf-8'))
    return parse_spec(data, spec_path)


def parse_spec(data: dict, path: Optional[Path] = None) -> Spec:
    """Parse spec dict into Spec object."""
    spec = Spec(
        name=data.get("name", "unnamed"),
        version=data.get("version", "1.0.0"),
        status=data.get("status", "draft"),
        author=data.get("author", ""),
        created=data.get("created", ""),
        updated=data.get("updated", ""),
        path=path,
    )
    
    # Overview
    overview = data.get("overview", {})
    spec.problem = overview.get("problem", "")
    spec.success = overview.get("success", "")
    spec.context = overview.get("context", "")
    
    # Interfaces
    interfaces = data.get("interfaces", {})
    
    for iface_data in interfaces.get("provides", []):
        members = [
            InterfaceMember(
                name=m.get("name", ""),
                signature=m.get("signature", ""),
                expectations=m.get("expectations", "")
            )
            for m in iface_data.get("members", [])
        ]
        spec.provides.append(Interface(
            name=iface_data.get("name", ""),
            description=iface_data.get("description", ""),
            members=members
        ))
    
    spec.requires = interfaces.get("requires", [])
    
    for st_data in interfaces.get("shared_types", []):
        spec.shared_types.append(SharedType(
            name=st_data.get("name", ""),
            kind=st_data.get("kind", "class"),
            description=st_data.get("description", "")
        ))
    
    # Structure
    structure = data.get("structure", {})
    spec.is_leaf = structure.get("is_leaf")
    spec.composition = structure.get("composition", "")
    
    for child_data in structure.get("children", []):
        spec.children.append(Child(
            name=child_data.get("name", ""),
            responsibility=child_data.get("responsibility", ""),
            provides=child_data.get("provides", []),
            requires=child_data.get("requires", [])
        ))
    
    for class_data in structure.get("classes", []):
        spec.classes.append(ClassDef(
            name=class_data.get("name", ""),
            type=class_data.get("type", "class"),
            responsibility=class_data.get("responsibility", ""),
            location=class_data.get("location", "")
        ))
    
    spec.dependencies = structure.get("dependencies", [])
    
    # Criteria
    criteria = data.get("criteria", {})
    
    for ac_data in criteria.get("acceptance", []):
        spec.acceptance.append(Criterion(
            id=ac_data.get("id", ""),
            behavior=ac_data.get("behavior", ""),
            test=ac_data.get("test", ""),
            passed=ac_data.get("passed")
        ))
    
    for ec_data in criteria.get("edge_cases", []):
        spec.edge_cases.append(Criterion(
            id=ec_data.get("id", ""),
            behavior=ec_data.get("behavior", ""),
            test=ec_data.get("test", ""),
            passed=ec_data.get("passed")
        ))
    
    for ic_data in criteria.get("integration", []):
        spec.integration.append(Criterion(
            id=ic_data.get("id", ""),
            behavior=ic_data.get("behavior", ""),
            test=ic_data.get("test", ""),
            passed=ic_data.get("passed")
        ))
    
    # Constraints
    constraints = data.get("constraints", {})
    spec.tech_stack = constraints.get("tech_stack")  # Optional dict
    spec.scope_boundaries = constraints.get("scope_boundaries", [])
    spec.performance = constraints.get("performance", [])
    spec.security = constraints.get("security", [])
    spec.open_questions = constraints.get("open_questions", [])
    
    # Verification
    verification = data.get("verification", {})
    spec.tests_passed = verification.get("tests_passed")
    spec.lint_passed = verification.get("lint_passed")
    spec.build_passed = verification.get("build_passed")
    spec.deviations = verification.get("deviations", [])
    spec.summary = verification.get("summary", "")
    
    # Runtime
    runtime = data.get("runtime", {})
    spec.depth = runtime.get("depth", 0)
    spec.ralph_iteration = runtime.get("ralph_iteration", 0)
    spec.all_tests_passed = runtime.get("all_tests_passed", False)
    spec.integration_tests_passed = runtime.get("integration_tests_passed", False)
    spec.depends_on = runtime.get("depends_on", [])
    
    if "errors" in runtime and runtime["errors"]:
        err = runtime["errors"]
        spec.errors = Errors(
            iteration=err.get("iteration", 0),
            timestamp=err.get("timestamp", ""),
            compilation_success=err.get("compilation", {}).get("success", True),
            compilation_errors=err.get("compilation", {}).get("errors", []),
            test_total=err.get("test_results", {}).get("total", 0),
            test_passed=err.get("test_results", {}).get("passed", 0),
            test_failed=err.get("test_results", {}).get("failed", 0),
            test_failures=err.get("test_results", {}).get("failures", [])
        )
    
    return spec


def spec_to_dict(spec: Spec) -> dict:
    """Convert Spec object to dict for JSON serialization."""
    data = {
        "name": spec.name,
        "version": spec.version,
        "status": spec.status,
        "author": spec.author,
        "created": spec.created,
        "updated": datetime.now(timezone.utc).isoformat(),
        
        "overview": {
            "problem": spec.problem,
            "success": spec.success,
            "context": spec.context
        },
        
        "interfaces": {
            "provides": [
                {
                    "name": iface.name,
                    "description": iface.description,
                    "members": [
                        {"name": m.name, "signature": m.signature, "expectations": m.expectations}
                        for m in iface.members
                    ]
                }
                for iface in spec.provides
            ],
            "requires": spec.requires,
            "shared_types": [
                {"name": st.name, "kind": st.kind, "description": st.description}
                for st in spec.shared_types
            ]
        },
        
        "structure": {
            "is_leaf": spec.is_leaf,
            "children": [
                {"name": c.name, "responsibility": c.responsibility, "provides": c.provides, "requires": c.requires}
                for c in spec.children
            ],
            "composition": spec.composition,
            "classes": [
                {"name": c.name, "type": c.type, "responsibility": c.responsibility, "location": c.location}
                for c in spec.classes
            ],
            "dependencies": spec.dependencies
        },
        
        "criteria": {
            "acceptance": [
                {"id": c.id, "behavior": c.behavior, "test": c.test, "passed": c.passed}
                for c in spec.acceptance
            ],
            "edge_cases": [
                {"id": c.id, "behavior": c.behavior, "test": c.test, "passed": c.passed}
                for c in spec.edge_cases
            ],
            "integration": [
                {"id": c.id, "behavior": c.behavior, "test": c.test, "passed": c.passed}
                for c in spec.integration
            ]
        },
        
        "constraints": {
            "tech_stack": spec.tech_stack,
            "scope_boundaries": spec.scope_boundaries,
            "performance": spec.performance,
            "security": spec.security,
            "open_questions": spec.open_questions
        },
        
        "verification": {
            "tests_passed": spec.tests_passed,
            "lint_passed": spec.lint_passed,
            "build_passed": spec.build_passed,
            "deviations": spec.deviations,
            "summary": spec.summary
        },
        
        "runtime": {
            "depth": spec.depth,
            "ralph_iteration": spec.ralph_iteration,
            "all_tests_passed": spec.all_tests_passed,
            "integration_tests_passed": spec.integration_tests_passed,
            "depends_on": spec.depends_on,
            "errors": None
        }
    }
    
    if spec.errors:
        data["runtime"]["errors"] = {
            "iteration": spec.errors.iteration,
            "timestamp": spec.errors.timestamp,
            "compilation": {
                "success": spec.errors.compilation_success,
                "errors": spec.errors.compilation_errors
            },
            "test_results": {
                "total": spec.errors.test_total,
                "passed": spec.errors.test_passed,
                "failed": spec.errors.test_failed,
                "failures": spec.errors.test_failures
            }
        }
    
    return data


def save_spec(spec: Spec, path: Optional[Path] = None) -> None:
    """Save spec to JSON file."""
    path = path or spec.path
    if not path:
        raise ValueError("No path specified for saving spec")
    
    data = spec_to_dict(spec)
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')


# =============================================================================
# SPEC OPERATIONS
# =============================================================================

def is_leaf(spec: Spec) -> Optional[bool]:
    """Determine if spec is a leaf."""
    # Explicit value takes precedence
    if spec.is_leaf is not None:
        return spec.is_leaf
    
    # Infer from content
    has_children = len(spec.children) > 0
    has_classes = len(spec.classes) > 0
    
    if has_classes and not has_children:
        return True
    if has_children and not has_classes:
        return False
    
    # Ambiguous
    return None


def is_ready(spec: Spec) -> tuple[bool, list[str]]:
    """Check if spec is ready for implementation/decomposition."""
    blockers = []
    
    # Must have overview
    if not spec.problem:
        blockers.append("Missing problem statement")
    if not spec.success:
        blockers.append("Missing success statement")
    
    # Must have provided interfaces
    if not spec.provides:
        blockers.append("No interfaces provided")
    
    # Must have structure decided
    if spec.is_leaf is None:
        blockers.append("Leaf/non-leaf not decided")
    
    # Leaf-specific
    if spec.is_leaf is True:
        if not spec.classes:
            blockers.append("Leaf spec has no classes defined")
        if not spec.acceptance:
            blockers.append("Leaf spec has no acceptance criteria")
    
    # Non-leaf specific
    if spec.is_leaf is False:
        if not spec.children:
            blockers.append("Non-leaf spec has no children defined")
        if not spec.integration:
            blockers.append("Non-leaf spec has no integration criteria")
    
    # No open questions
    if spec.open_questions:
        blockers.append(f"Open questions remaining: {len(spec.open_questions)}")
    
    return len(blockers) == 0, blockers


def get_allowed_files(spec: Spec) -> list[str]:
    """Get list of file paths the implementer can modify."""
    return [c.location for c in spec.classes if c.location]


def create_child_spec(parent: Spec, child_def: Child, child_path: Path) -> Spec:
    """Create a new spec for a child based on parent's child definition."""
    child = Spec(
        name=child_def.name,
        version="1.0.0",
        status="draft",
        path=child_path,
        created=datetime.now(timezone.utc).isoformat(),

        problem=child_def.responsibility,
        success=f"This spec is successful when {child_def.name} is implemented correctly.",

        depth=parent.depth + 1,
        depends_on=child_def.requires if child_def.requires else [],

        # Inherit tech_stack from parent
        tech_stack=parent.tech_stack,
    )

    # Add provided interfaces
    for iface_name in child_def.provides:
        child.provides.append(Interface(name=iface_name))

    # Add required interfaces from parent
    for req in child_def.requires:
        child.requires.append({
            "name": req,
            "source": "sibling" if req in [c.name for c in parent.children] else "parent",
            "usage": f"Required by {child_def.name}"
        })

    return child


def _get_file_extension_and_case(tech_stack: Optional[dict]) -> tuple[str, str]:
    """Get file extension and naming case from tech_stack.

    Returns (extension, case_style) where case_style is one of:
    - "PascalCase" (C#)
    - "kebab-case" (TypeScript/JavaScript)
    - "snake_case" (Python)
    """
    if not tech_stack or not tech_stack.get("language"):
        return ".cs", "PascalCase"  # Default to C#

    lang = tech_stack["language"].lower()
    if "typescript" in lang or "ts" in lang:
        return ".ts", "kebab-case"
    elif "javascript" in lang or "js" in lang:
        return ".js", "kebab-case"
    elif "python" in lang or "py" in lang:
        return ".py", "snake_case"
    elif "go" in lang:
        return ".go", "snake_case"
    elif "java" in lang:
        return ".java", "PascalCase"
    elif "rust" in lang:
        return ".rs", "snake_case"
    else:
        return ".cs", "PascalCase"  # Default to C#


def _convert_case(name: str, case_style: str) -> str:
    """Convert PascalCase name to target case style."""
    import re
    if case_style == "kebab-case":
        # PascalCase -> kebab-case
        return re.sub(r'(?<!^)(?=[A-Z])', '-', name).lower()
    elif case_style == "snake_case":
        # PascalCase -> snake_case
        return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
    else:
        return name  # PascalCase - no change


def create_shared_spec(parent: Spec, shared_path: Path) -> Spec:
    """Create a spec for shared types from parent's shared_types."""
    shared = Spec(
        name="shared",
        version="1.0.0",
        status="draft",
        path=shared_path,
        created=datetime.now(timezone.utc).isoformat(),

        is_leaf=True,  # Shared is always a leaf

        problem=f"Multiple children of {parent.name} need access to common types.",
        success="All shared types are implemented and available for sibling specs.",

        depth=parent.depth + 1,
        depends_on=[],  # Shared has no dependencies

        # Inherit tech_stack from parent
        tech_stack=parent.tech_stack,
    )

    # Add interface for shared types
    shared.provides.append(Interface(
        name="SharedTypes",
        description=", ".join(st.name for st in parent.shared_types)
    ))

    # Determine file extension and naming case from tech_stack
    file_ext, case_style = _get_file_extension_and_case(parent.tech_stack)

    # Convert shared types to classes
    for st in parent.shared_types:
        file_name = _convert_case(st.name, case_style)
        shared.classes.append(ClassDef(
            name=st.name,
            type=st.kind,
            responsibility=st.description,
            location=f"src/shared/{file_name}{file_ext}"
        ))

        # Add acceptance criterion for each type
        shared.acceptance.append(Criterion(
            id=f"AC-{len(shared.acceptance)+1:03d}",
            behavior=f"{st.name} {st.kind} is defined and accessible",
            test=f"test_{st.name.lower()}_exists"
        ))

    return shared
