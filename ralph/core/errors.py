"""
Error types for the Ralph pipeline.

Defines structured error types that can be:
- Captured by the Verifier
- Fed back to the Implementer
- Escalated to users when unrecoverable
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
from datetime import datetime, timezone


class ErrorCategory(str, Enum):
    """Categories of errors."""
    COMPILATION = "compilation"     # Code doesn't compile
    TEST = "test"                   # Tests fail
    VALIDATION = "validation"       # Schema/constraint violation
    SCOPE = "scope"                 # Agent tried to access forbidden resource
    AGENT = "agent"                 # Agent produced invalid output
    TIMEOUT = "timeout"             # Operation timed out
    INFRASTRUCTURE = "infrastructure"  # System error (disk, network, etc.)


class ErrorSeverity(str, Enum):
    """Severity levels for errors."""
    WARNING = "warning"       # Non-blocking issue
    ERROR = "error"           # Blocking but recoverable
    CRITICAL = "critical"     # Unrecoverable, needs human


@dataclass
class CompilationError:
    """A single compilation error."""
    file: str
    line: Optional[int] = None
    column: Optional[int] = None
    message: str = ""
    code: str = ""  # Error code (e.g., "CS1002", "E0001")
    
    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "message": self.message,
            "code": self.code,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "CompilationError":
        return cls(
            file=data.get("file", ""),
            line=data.get("line"),
            column=data.get("column"),
            message=data.get("message", ""),
            code=data.get("code", ""),
        )
    
    def __str__(self) -> str:
        loc = f"{self.file}"
        if self.line:
            loc += f":{self.line}"
            if self.column:
                loc += f":{self.column}"
        return f"{loc}: {self.code} {self.message}"


@dataclass
class TestFailure:
    """A single test failure."""
    test_name: str
    test_file: str = ""
    message: str = ""
    expected: str = ""
    actual: str = ""
    stack_trace: str = ""
    criterion_id: Optional[str] = None  # Related acceptance criterion
    
    def to_dict(self) -> dict:
        return {
            "test_name": self.test_name,
            "test_file": self.test_file,
            "message": self.message,
            "expected": self.expected,
            "actual": self.actual,
            "stack_trace": self.stack_trace,
            "criterion_id": self.criterion_id,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TestFailure":
        return cls(
            test_name=data.get("test_name", ""),
            test_file=data.get("test_file", ""),
            message=data.get("message", ""),
            expected=data.get("expected", ""),
            actual=data.get("actual", ""),
            stack_trace=data.get("stack_trace", ""),
            criterion_id=data.get("criterion_id"),
        )
    
    def __str__(self) -> str:
        s = f"FAIL: {self.test_name}"
        if self.message:
            s += f"\n  {self.message}"
        if self.expected and self.actual:
            s += f"\n  Expected: {self.expected}"
            s += f"\n  Actual: {self.actual}"
        return s


@dataclass
class TestResults:
    """Results from running tests."""
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration_seconds: float = 0.0
    failures: List[TestFailure] = field(default_factory=list)
    
    @property
    def success(self) -> bool:
        """Did all tests pass?"""
        return self.failed == 0 and self.total > 0
    
    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "duration_seconds": self.duration_seconds,
            "failures": [f.to_dict() for f in self.failures],
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TestResults":
        return cls(
            total=data.get("total", 0),
            passed=data.get("passed", 0),
            failed=data.get("failed", 0),
            skipped=data.get("skipped", 0),
            duration_seconds=data.get("duration_seconds", 0.0),
            failures=[TestFailure.from_dict(f) for f in data.get("failures", [])],
        )


@dataclass
class CompilationResults:
    """Results from compilation."""
    success: bool = False
    errors: List[CompilationError] = field(default_factory=list)
    warnings: List[CompilationError] = field(default_factory=list)
    duration_seconds: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "duration_seconds": self.duration_seconds,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "CompilationResults":
        return cls(
            success=data.get("success", False),
            errors=[CompilationError.from_dict(e) for e in data.get("errors", [])],
            warnings=[CompilationError.from_dict(w) for w in data.get("warnings", [])],
            duration_seconds=data.get("duration_seconds", 0.0),
        )


@dataclass
class VerificationResults:
    """Combined verification results (compilation + tests)."""
    iteration: int
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    compilation: Optional[CompilationResults] = None
    tests: Optional[TestResults] = None
    lint_passed: Optional[bool] = None
    verdict: str = "pending"  # "pass", "fail_compilation", "fail_tests", "fail_lint"
    summary: str = ""
    
    @property
    def passed(self) -> bool:
        """Did verification pass?"""
        return self.verdict == "pass"
    
    def compute_verdict(self) -> str:
        """Compute the verdict from results."""
        if self.compilation and not self.compilation.success:
            return "fail_compilation"
        if self.tests and not self.tests.success:
            return "fail_tests"
        if self.lint_passed is False:
            return "fail_lint"
        if self.compilation and self.compilation.success:
            if self.tests and self.tests.success:
                return "pass"
        return "pending"
    
    def to_dict(self) -> dict:
        return {
            "iteration": self.iteration,
            "timestamp": self.timestamp,
            "compilation": self.compilation.to_dict() if self.compilation else None,
            "tests": self.tests.to_dict() if self.tests else None,
            "lint_passed": self.lint_passed,
            "verdict": self.verdict,
            "summary": self.summary,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "VerificationResults":
        return cls(
            iteration=data.get("iteration", 0),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            compilation=CompilationResults.from_dict(data["compilation"]) if data.get("compilation") else None,
            tests=TestResults.from_dict(data["tests"]) if data.get("tests") else None,
            lint_passed=data.get("lint_passed"),
            verdict=data.get("verdict", "pending"),
            summary=data.get("summary", ""),
        )


@dataclass
class ErrorReport:
    """
    Complete error report for a spec iteration.
    
    This is what gets stored in the spec and fed back to agents.
    """
    iteration: int
    category: ErrorCategory
    severity: ErrorSeverity
    message: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    compilation: Optional[CompilationResults] = None
    tests: Optional[TestResults] = None
    details: Dict[str, Any] = field(default_factory=dict)
    recoverable: bool = True
    
    def to_dict(self) -> dict:
        return {
            "iteration": self.iteration,
            "category": self.category.value,
            "severity": self.severity.value,
            "message": self.message,
            "timestamp": self.timestamp,
            "compilation": self.compilation.to_dict() if self.compilation else None,
            "tests": self.tests.to_dict() if self.tests else None,
            "details": self.details,
            "recoverable": self.recoverable,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ErrorReport":
        return cls(
            iteration=data.get("iteration", 0),
            category=ErrorCategory(data.get("category", "agent")),
            severity=ErrorSeverity(data.get("severity", "error")),
            message=data.get("message", ""),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            compilation=CompilationResults.from_dict(data["compilation"]) if data.get("compilation") else None,
            tests=TestResults.from_dict(data["tests"]) if data.get("tests") else None,
            details=data.get("details", {}),
            recoverable=data.get("recoverable", True),
        )
    
    def format_for_agent(self) -> str:
        """Format error report for agent consumption."""
        lines = [
            f"## Error Report (Iteration {self.iteration})",
            f"**Category:** {self.category.value}",
            f"**Message:** {self.message}",
            "",
        ]
        
        if self.compilation and self.compilation.errors:
            lines.append("### Compilation Errors")
            for err in self.compilation.errors[:10]:  # Limit to 10
                lines.append(f"- {err}")
            if len(self.compilation.errors) > 10:
                lines.append(f"  ... and {len(self.compilation.errors) - 10} more")
            lines.append("")
        
        if self.tests and self.tests.failures:
            lines.append("### Test Failures")
            for fail in self.tests.failures[:10]:
                lines.append(f"- {fail}")
            if len(self.tests.failures) > 10:
                lines.append(f"  ... and {len(self.tests.failures) - 10} more")
            lines.append("")
        
        return "\n".join(lines)


# =============================================================================
# PIPELINE EXCEPTIONS
# =============================================================================

class RalphError(Exception):
    """Base exception for Ralph pipeline errors."""
    pass


class SpecValidationError(RalphError):
    """Spec failed schema validation."""
    def __init__(self, message: str, errors: Optional[List[str]] = None):
        super().__init__(message)
        self.errors = errors or []


class InvalidTransitionError(RalphError):
    """Invalid phase transition attempted."""
    def __init__(self, from_phase: str, to_phase: str):
        super().__init__(f"Invalid transition: {from_phase} -> {to_phase}")
        self.from_phase = from_phase
        self.to_phase = to_phase


class ScopeViolationError(RalphError):
    """Agent attempted to access resource outside scope."""
    def __init__(self, path: str, allowed_paths: List[str]):
        super().__init__(f"Scope violation: {path} not in {allowed_paths}")
        self.path = path
        self.allowed_paths = allowed_paths


class MaxIterationsError(RalphError):
    """Spec exceeded maximum iterations."""
    def __init__(self, spec_id: str, iterations: int, max_iterations: int):
        super().__init__(
            f"Spec {spec_id} exceeded max iterations ({iterations}/{max_iterations})"
        )
        self.spec_id = spec_id
        self.iterations = iterations
        self.max_iterations = max_iterations


class AgentError(RalphError):
    """Agent produced invalid or unexpected output."""
    def __init__(self, agent_role: str, message: str, output: Optional[str] = None):
        super().__init__(f"Agent error ({agent_role}): {message}")
        self.agent_role = agent_role
        self.output = output
