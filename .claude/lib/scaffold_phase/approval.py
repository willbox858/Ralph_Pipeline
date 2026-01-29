"""Stub approval checking."""
import json
from pathlib import Path
from typing import Union

from .types import ApprovalGrant, HibernationRequest


def await_stub_approval(spec_path: str) -> Union[ApprovalGrant, HibernationRequest]:
    """Check if stubs are approved for a spec.

    Reads spec.stubs_approved field from spec.json.
    If False (or missing), returns HibernationRequest.
    If True, returns ApprovalGrant.

    Args:
        spec_path: Path to the spec.json file

    Returns:
        ApprovalGrant if approved, HibernationRequest if not
    """
    path = Path(spec_path)
    spec_data = json.loads(path.read_text(encoding="utf-8"))

    # Check stubs_approved field (default to False if missing)
    stubs_approved = spec_data.get("stubs_approved", False)

    if stubs_approved:
        return ApprovalGrant()
    else:
        return HibernationRequest(
            reason="Stubs pending human approval. Run /approve-stubs to continue.",
            spec_path=spec_path,
        )
