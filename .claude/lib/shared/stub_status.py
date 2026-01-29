"""StubStatus enum for stub-generation-phase."""
from enum import StrEnum, auto


class StubStatus(StrEnum):
    """Status of a generated stub file.

    Values:
        PENDING_REVIEW: Stub generated, awaiting user review
        APPROVED: User approved the stub, ready for implementation
        MODIFIED: User modified the stub before approval
    """

    PENDING_REVIEW = auto()
    APPROVED = auto()
    MODIFIED = auto()
