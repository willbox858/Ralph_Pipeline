"""
Spec types for the Ralph pipeline.

The Spec is the core unit of work. It defines what needs to be built,
how it should be structured, and tracks progress through the pipeline.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from enum import Enum
import uuid

from .phase import Phase
from .errors import ErrorReport


class TypeKind(str, Enum):
    """Kind of type definition."""
    CLASS = "class"
    INTERFACE = "interface"
    STRUCT = "struct"
    RECORD = "record"
    ENUM = "enum"
    MODULE = "module"
    FUNCTION = "function"


# =============================================================================
# INTERFACE DEFINITIONS
# =============================================================================

@dataclass
class InterfaceMember:
    """A member of an interface (method, property)."""
    name: str
    signature: str
    description: str = ""
    expectations: str = ""
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "signature": self.signature,
            "description": self.description,
            "expectations": self.expectations,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "InterfaceMember":
        return cls(
            name=data.get("name", ""),
            signature=data.get("signature", ""),
            description=data.get("description", ""),
            expectations=data.get("expectations", ""),
        )


@dataclass
class Interface:
    """An interface this spec provides or requires."""
    name: str
    description: str = ""
    members: List[InterfaceMember] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "members": [m.to_dict() for m in self.members],
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Interface":
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            members=[InterfaceMember.from_dict(m) for m in data.get("members", [])],
        )


@dataclass
class SharedType:
    """A shared type definition."""
    name: str
    kind: TypeKind
    description: str = ""
    fields: List[Dict[str, str]] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "description": self.description,
            "fields": self.fields,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "SharedType":
        return cls(
            name=data.get("name", ""),
            kind=TypeKind(data.get("kind", "class")),
            description=data.get("description", ""),
            fields=data.get("fields", []),
        )


# =============================================================================
# STRUCTURE DEFINITIONS
# =============================================================================

@dataclass
class ClassDefinition:
    """A class/module to be implemented."""
    name: str
    kind: TypeKind
    responsibility: str
    location: str  # File path relative to spec directory
    implements: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "responsibility": self.responsibility,
            "location": self.location,
            "implements": self.implements,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ClassDefinition":
        return cls(
            name=data.get("name", ""),
            kind=TypeKind(data.get("kind", "class")),
            responsibility=data.get("responsibility", ""),
            location=data.get("location", ""),
            implements=data.get("implements", []),
        )


@dataclass
class Dependency:
    """Internal dependency between components."""
    component: str
    depends_on: str
    reason: str
    
    def to_dict(self) -> dict:
        return {
            "component": self.component,
            "depends_on": self.depends_on,
            "reason": self.reason,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Dependency":
        return cls(
            component=data.get("component", ""),
            depends_on=data.get("depends_on", ""),
            reason=data.get("reason", ""),
        )


@dataclass
class ChildRef:
    """Reference to a child spec."""
    name: str
    responsibility: str
    provides: List[str] = field(default_factory=list)
    requires: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "responsibility": self.responsibility,
            "provides": self.provides,
            "requires": self.requires,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ChildRef":
        return cls(
            name=data.get("name", ""),
            responsibility=data.get("responsibility", ""),
            provides=data.get("provides", []),
            requires=data.get("requires", []),
        )


# =============================================================================
# CRITERIA
# =============================================================================

@dataclass
class Criterion:
    """An acceptance criterion."""
    id: str
    behavior: str
    test_hint: str = ""
    passed: Optional[bool] = None
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "behavior": self.behavior,
            "test_hint": self.test_hint,
            "passed": self.passed,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Criterion":
        return cls(
            id=data.get("id", ""),
            behavior=data.get("behavior", ""),
            test_hint=data.get("test_hint", ""),
            passed=data.get("passed"),
        )


# =============================================================================
# TECH STACK & CONSTRAINTS
# =============================================================================

@dataclass
class TechStack:
    """Technology stack configuration."""
    language: str  # "Python", "C#", "TypeScript", etc.
    runtime: str = ""  # ".NET 8", "Node 20", "Python 3.11+"
    frameworks: List[str] = field(default_factory=list)
    test_framework: str = ""  # "pytest", "xunit", "jest"
    build_command: str = ""  # "dotnet build", "npm run build"
    test_command: str = ""  # "pytest", "dotnet test", "npm test"
    lint_command: str = ""  # "ruff check", "dotnet format"
    mcp_tools: List[str] = field(default_factory=list)  # ["unity", "dotnet"]
    rationale: str = ""
    
    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "runtime": self.runtime,
            "frameworks": self.frameworks,
            "test_framework": self.test_framework,
            "build_command": self.build_command,
            "test_command": self.test_command,
            "lint_command": self.lint_command,
            "mcp_tools": self.mcp_tools,
            "rationale": self.rationale,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TechStack":
        return cls(
            language=data.get("language", ""),
            runtime=data.get("runtime", ""),
            frameworks=data.get("frameworks", []),
            test_framework=data.get("test_framework", ""),
            build_command=data.get("build_command", ""),
            test_command=data.get("test_command", ""),
            lint_command=data.get("lint_command", ""),
            mcp_tools=data.get("mcp_tools", []),
            rationale=data.get("rationale", ""),
        )


@dataclass
class Constraints:
    """Constraints on implementation."""
    tech_stack: Optional[TechStack] = None
    scope_boundaries: List[str] = field(default_factory=list)
    performance: List[str] = field(default_factory=list)
    security: List[str] = field(default_factory=list)
    forbidden_patterns: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "tech_stack": self.tech_stack.to_dict() if self.tech_stack else None,
            "scope_boundaries": self.scope_boundaries,
            "performance": self.performance,
            "security": self.security,
            "forbidden_patterns": self.forbidden_patterns,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Constraints":
        return cls(
            tech_stack=TechStack.from_dict(data["tech_stack"]) if data.get("tech_stack") else None,
            scope_boundaries=data.get("scope_boundaries", []),
            performance=data.get("performance", []),
            security=data.get("security", []),
            forbidden_patterns=data.get("forbidden_patterns", []),
        )


# =============================================================================
# SPEC
# =============================================================================

@dataclass
class Spec:
    """
    The core spec type. Represents a unit of work in the pipeline.
    
    Can be hierarchical (parent/children) or a leaf (directly implemented).
    """
    
    # Identity
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    parent_id: Optional[str] = None
    
    # Status
    phase: Phase = Phase.DRAFT
    is_leaf: Optional[bool] = None  # Decided during architecture
    
    # Overview
    problem: str = ""
    success_criteria: str = ""
    context: str = ""
    
    # Interfaces
    provides: List[Interface] = field(default_factory=list)
    requires: List[Interface] = field(default_factory=list)
    shared_types: List[SharedType] = field(default_factory=list)
    
    # Structure (populated during architecture)
    classes: List[ClassDefinition] = field(default_factory=list)
    dependencies: List[Dependency] = field(default_factory=list)
    children: List[ChildRef] = field(default_factory=list)
    composition: str = ""  # How children integrate
    
    # Criteria
    acceptance_criteria: List[Criterion] = field(default_factory=list)
    edge_cases: List[Criterion] = field(default_factory=list)
    integration_criteria: List[Criterion] = field(default_factory=list)
    
    # Constraints (inherited from parent if not specified)
    constraints: Optional[Constraints] = None
    
    # Runtime tracking
    iteration: int = 0
    max_iterations: int = 15
    errors: List[ErrorReport] = field(default_factory=list)
    
    # Timestamps
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    
    # Paths (set by orchestrator)
    spec_dir: str = ""  # Directory containing this spec
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "parent_id": self.parent_id,
            "phase": self.phase.value,
            "is_leaf": self.is_leaf,
            "problem": self.problem,
            "success_criteria": self.success_criteria,
            "context": self.context,
            "provides": [i.to_dict() for i in self.provides],
            "requires": [i.to_dict() for i in self.requires],
            "shared_types": [t.to_dict() for t in self.shared_types],
            "classes": [c.to_dict() for c in self.classes],
            "dependencies": [d.to_dict() for d in self.dependencies],
            "children": [c.to_dict() for c in self.children],
            "composition": self.composition,
            "acceptance_criteria": [c.to_dict() for c in self.acceptance_criteria],
            "edge_cases": [c.to_dict() for c in self.edge_cases],
            "integration_criteria": [c.to_dict() for c in self.integration_criteria],
            "constraints": self.constraints.to_dict() if self.constraints else None,
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "errors": [e.to_dict() for e in self.errors],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "spec_dir": self.spec_dir,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Spec":
        """Create from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            parent_id=data.get("parent_id"),
            phase=Phase(data.get("phase", "draft")),
            is_leaf=data.get("is_leaf"),
            problem=data.get("problem", ""),
            success_criteria=data.get("success_criteria", ""),
            context=data.get("context", ""),
            provides=[Interface.from_dict(i) for i in data.get("provides", [])],
            requires=[Interface.from_dict(i) for i in data.get("requires", [])],
            shared_types=[SharedType.from_dict(t) for t in data.get("shared_types", [])],
            classes=[ClassDefinition.from_dict(c) for c in data.get("classes", [])],
            dependencies=[Dependency.from_dict(d) for d in data.get("dependencies", [])],
            children=[ChildRef.from_dict(c) for c in data.get("children", [])],
            composition=data.get("composition", ""),
            acceptance_criteria=[Criterion.from_dict(c) for c in data.get("acceptance_criteria", [])],
            edge_cases=[Criterion.from_dict(c) for c in data.get("edge_cases", [])],
            integration_criteria=[Criterion.from_dict(c) for c in data.get("integration_criteria", [])],
            constraints=Constraints.from_dict(data["constraints"]) if data.get("constraints") else None,
            iteration=data.get("iteration", 0),
            max_iterations=data.get("max_iterations", 15),
            errors=[ErrorReport.from_dict(e) for e in data.get("errors", [])],
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            spec_dir=data.get("spec_dir", ""),
        )
    
    def touch(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.now(timezone.utc).isoformat()
    
    def get_effective_tech_stack(self) -> Optional[TechStack]:
        """Get tech stack from constraints."""
        if self.constraints and self.constraints.tech_stack:
            return self.constraints.tech_stack
        return None
    
    def get_allowed_paths(self) -> List[str]:
        """Get paths this spec can write to."""
        paths = []
        
        if self.spec_dir:
            paths.append(f"{self.spec_dir}/")
        
        # Add class locations
        for cls in self.classes:
            dir_path = "/".join(cls.location.split("/")[:-1])
            if dir_path:
                path = f"{dir_path}/"
                if path not in paths:
                    paths.append(path)
        
        return paths
    
    def add_error(self, error: ErrorReport) -> None:
        """Add an error report."""
        self.errors.append(error)
        self.touch()
    
    def get_latest_error(self) -> Optional[ErrorReport]:
        """Get the most recent error report."""
        if self.errors:
            return self.errors[-1]
        return None
    
    def increment_iteration(self) -> int:
        """Increment iteration counter and return new value."""
        self.iteration += 1
        self.touch()
        return self.iteration
    
    def can_iterate(self) -> bool:
        """Check if more iterations are allowed."""
        return self.iteration < self.max_iterations


# =============================================================================
# SPEC FACTORIES
# =============================================================================

def create_spec(
    name: str,
    problem: str,
    success_criteria: str,
    parent_id: Optional[str] = None,
    tech_stack: Optional[TechStack] = None,
) -> Spec:
    """Create a new spec with minimal required fields."""
    constraints = Constraints(tech_stack=tech_stack) if tech_stack else None
    
    return Spec(
        name=name,
        parent_id=parent_id,
        problem=problem,
        success_criteria=success_criteria,
        constraints=constraints,
    )


def create_child_spec(
    parent: Spec,
    child_ref: ChildRef,
) -> Spec:
    """Create a child spec from a parent and child reference."""
    # Inherit tech stack from parent
    tech_stack = parent.get_effective_tech_stack()
    
    # Inherit and narrow constraints
    constraints = None
    if parent.constraints:
        constraints = Constraints(
            tech_stack=tech_stack,
            scope_boundaries=list(parent.constraints.scope_boundaries),
            performance=list(parent.constraints.performance),
            security=list(parent.constraints.security),
            forbidden_patterns=list(parent.constraints.forbidden_patterns),
        )
    elif tech_stack:
        constraints = Constraints(tech_stack=tech_stack)
    
    return Spec(
        name=child_ref.name,
        parent_id=parent.id,
        problem=child_ref.responsibility,
        success_criteria=f"Provides: {', '.join(child_ref.provides)}" if child_ref.provides else "",
        constraints=constraints,
        max_iterations=parent.max_iterations,
    )
