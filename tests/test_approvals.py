import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import approvals as approvals_mod  # noqa: E402
from agents.approvals import (  # noqa: E402
    create_approval,
    list_approvals,
    resolve_approval,
)
from agents import orchestrator  # noqa: E402
from tools import finance_tools  # noqa: E402

# Fixtures are provided by tests/conftest.py (autouse=True isolate_data_files).

_SAMPLE_INVOICE = {
    "quantity": 50,
    "model": "Apple MacBook Pro 14",
    "unit_price": 2399,
    "total_invoice": 119950,
}


# ── create_approval ───────────────────────────────────────────────────────────

def test_create_approval_returns_pending_record(approvals_file):
    record = create_approval("Order 50 MacBooks", _SAMPLE_INVOICE)
    assert record["status"] == "pending"
    assert record["prompt"] == "Order 50 MacBooks"
    assert record["invoice"] == _SAMPLE_INVOICE
    assert len(record["id"]) == 8
    assert "created_at" in record


def test_create_approval_persists_to_file(approvals_file):
    create_approval("Order 50 MacBooks", _SAMPLE_INVOICE)
    stored = json.loads(approvals_file.read_text())
    assert len(stored) == 1
    assert stored[0]["status"] == "pending"


def test_create_multiple_approvals(approvals_file):
    create_approval("Order 50 MacBooks", _SAMPLE_INVOICE)
    create_approval("Order 10 ThinkPads", {**_SAMPLE_INVOICE, "total_invoice": 18990})
    assert len(list_approvals()) == 2


# ── list_approvals ────────────────────────────────────────────────────────────

def test_list_approvals_no_filter(approvals_file):
    create_approval("Order 50 MacBooks", _SAMPLE_INVOICE)
    assert len(list_approvals()) == 1


def test_list_approvals_filter_pending(approvals_file):
    create_approval("Order 50 MacBooks", _SAMPLE_INVOICE)
    assert len(list_approvals(status="pending")) == 1
    assert len(list_approvals(status="approved")) == 0


# ── resolve_approval: approve ─────────────────────────────────────────────────

def test_approve_increases_budget_past_cap(approvals_file, budget_file):
    """Approving a blocked invoice adds to current_spend even if it exceeds the cap."""
    record = create_approval("Order 50 MacBooks", _SAMPLE_INVOICE)
    resolved = resolve_approval(record["id"], "approved", "alice")

    assert resolved["status"] == "approved"
    assert resolved["approver"] == "alice"
    assert "resolved_at" in resolved

    budget = json.loads(budget_file.read_text())
    # 420,000 + 119,950 = 539,950 — deliberately over the 500,000 cap
    assert budget["current_spend"] == 539950


def test_approve_updates_status_in_file(approvals_file, budget_file):
    record = create_approval("Order 50 MacBooks", _SAMPLE_INVOICE)
    resolve_approval(record["id"], "approved", "alice")
    stored = json.loads(approvals_file.read_text())
    assert stored[0]["status"] == "approved"


# ── resolve_approval: reject ──────────────────────────────────────────────────

def test_reject_leaves_budget_unchanged(approvals_file, budget_file):
    record = create_approval("Order 50 MacBooks", _SAMPLE_INVOICE)
    resolved = resolve_approval(record["id"], "rejected", "bob")

    assert resolved["status"] == "rejected"
    assert resolved["approver"] == "bob"

    budget = json.loads(budget_file.read_text())
    assert budget["current_spend"] == 420000  # unchanged


def test_reject_updates_status_in_file(approvals_file, budget_file):
    record = create_approval("Order 50 MacBooks", _SAMPLE_INVOICE)
    resolve_approval(record["id"], "rejected", "bob")
    stored = json.loads(approvals_file.read_text())
    assert stored[0]["status"] == "rejected"


# ── double-resolve raises ValueError ─────────────────────────────────────────

def test_double_resolve_approved_raises(approvals_file, budget_file):
    record = create_approval("Order 50 MacBooks", _SAMPLE_INVOICE)
    resolve_approval(record["id"], "approved", "alice")
    with pytest.raises(ValueError, match="already"):
        resolve_approval(record["id"], "approved", "alice")


def test_double_resolve_rejected_raises(approvals_file, budget_file):
    record = create_approval("Order 50 MacBooks", _SAMPLE_INVOICE)
    resolve_approval(record["id"], "rejected", "bob")
    with pytest.raises(ValueError, match="already"):
        resolve_approval(record["id"], "rejected", "bob")


def test_resolve_nonexistent_raises(approvals_file, budget_file):
    with pytest.raises(ValueError, match="not found"):
        resolve_approval("deadbeef", "approved", "alice")


# ── orchestrator.run returns approval_id when blocked ────────────────────────

def test_orchestrator_run_returns_approval_id(approvals_file, budget_file):
    result = orchestrator.run("Order 50 MacBooks")
    assert result["status"] == "blocked"
    assert "approval_id" in result
    assert isinstance(result["approval_id"], str)
    assert len(result["approval_id"]) == 8

    # The approval should be persisted as pending
    pending = list_approvals(status="pending")
    assert len(pending) == 1
    assert pending[0]["id"] == result["approval_id"]
