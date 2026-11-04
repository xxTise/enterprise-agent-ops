"""Human-approval store: JSON-backed approval queue for blocked invoices."""

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

APPROVALS_FILE = Path(__file__).resolve().parent.parent / "data" / "approvals.json"
_BUDGET_FILE_PATH = Path(__file__).resolve().parent.parent / "data" / "budget.json"


def _read_approvals() -> list:
    if not APPROVALS_FILE.exists():
        return []
    return json.loads(APPROVALS_FILE.read_text())


def _write_approvals(approvals: list) -> None:
    fd, tmp = tempfile.mkstemp(dir=APPROVALS_FILE.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(approvals, f, indent=2)
        f.write("\n")
    os.replace(tmp, APPROVALS_FILE)


def _read_budget() -> dict:
    # Import here to allow tests to monkeypatch finance_tools.BUDGET_FILE
    from tools import finance_tools
    return json.loads(finance_tools.BUDGET_FILE.read_text())


def _write_budget_override(budget: dict) -> None:
    from tools import finance_tools
    fd, tmp = tempfile.mkstemp(dir=finance_tools.BUDGET_FILE.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(budget, f, indent=2)
        f.write("\n")
    os.replace(tmp, finance_tools.BUDGET_FILE)


def create_approval(prompt: str, invoice: dict) -> dict:
    """Creates a new pending approval record and persists it.

    Returns:
        dict: The approval record with keys id, prompt, invoice, status, created_at.
    """
    approval = {
        "id": uuid.uuid4().hex[:8],
        "prompt": prompt,
        "invoice": invoice,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    approvals = _read_approvals()
    approvals.append(approval)
    _write_approvals(approvals)
    return approval


def list_approvals(status: str | None = None) -> list:
    """Returns all approvals, optionally filtered by status."""
    approvals = _read_approvals()
    if status is not None:
        approvals = [a for a in approvals if a["status"] == status]
    return approvals


def resolve_approval(approval_id: str, decision: str, approver: str) -> dict:
    """Resolves a pending approval as 'approved' or 'rejected'.

    On approval, adds the invoice total to current_spend (human override — may exceed cap).
    On rejection, leaves the budget unchanged.

    Raises:
        ValueError: If the approval is not found or is not in 'pending' status.
    """
    if decision not in ("approved", "rejected"):
        raise ValueError(f"decision must be 'approved' or 'rejected', got {decision!r}")

    approvals = _read_approvals()
    record = next((a for a in approvals if a["id"] == approval_id), None)
    if record is None:
        raise ValueError(f"Approval {approval_id!r} not found")
    if record["status"] != "pending":
        raise ValueError(f"Approval {approval_id!r} is already {record['status']!r}, cannot resolve again")

    record["status"] = decision
    record["approver"] = approver
    record["resolved_at"] = datetime.now(timezone.utc).isoformat()

    if decision == "approved":
        budget = _read_budget()
        total = record["invoice"]["total_invoice"]
        new_spend = budget["current_spend"] + total
        budget["current_spend"] = int(new_spend) if new_spend == int(new_spend) else round(new_spend, 2)
        _write_budget_override(budget)

    _write_approvals(approvals)
    return record
