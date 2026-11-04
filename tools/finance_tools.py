"""Finance tools for the Finance Agent (watsonx Orchestrate ADK)."""

import json
import os
import tempfile
from pathlib import Path

from ibm_watsonx_orchestrate.agent_builder.tools import tool

BUDGET_FILE = Path(__file__).resolve().parent.parent / "data" / "budget.json"

BLOCKED_PAYLOAD = {
    "status": "blocked",
    "reason": "budget exceeded",
    "required_action": "human_approval",
}


def _write_budget(budget: dict) -> None:
    # Write to a temp file and swap it in, so a crash mid-write never corrupts budget.json.
    fd, tmp = tempfile.mkstemp(dir=BUDGET_FILE.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(budget, f, indent=2)
        f.write("\n")
    os.replace(tmp, BUDGET_FILE)


@tool
def check_budget(invoice_amount: float) -> str:
    """Checks an invoice against the remaining enterprise budget and records it if approved.

    Args:
        invoice_amount (float): The total invoice amount in USD to be approved.

    Returns:
        str: "approved" if the invoice keeps total spend at or under the cap (the new
            spend total is saved to budget.json), otherwise a JSON payload with status
            "blocked" requiring human approval (budget.json is left unchanged).
    """
    try:
        amount = float(invoice_amount)
    except (TypeError, ValueError):
        raise ValueError(f"invoice_amount must be a number, got {invoice_amount!r}")
    if amount < 0:
        raise ValueError("invoice_amount cannot be negative")

    budget = json.loads(BUDGET_FILE.read_text())
    new_spend = budget["current_spend"] + amount
    if new_spend > budget["total_cap"]:
        return json.dumps(BLOCKED_PAYLOAD)

    budget["current_spend"] = int(new_spend) if new_spend == int(new_spend) else round(new_spend, 2)
    _write_budget(budget)
    return "approved"
