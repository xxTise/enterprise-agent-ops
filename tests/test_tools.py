import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import finance_tools, it_tools  # noqa: E402

# @tool wraps functions in a PythonTool; .fn is the raw function with plain return values.
check_budget = finance_tools.check_budget.fn
order_hardware = it_tools.order_hardware.fn


@pytest.fixture
def budget_file(tmp_path, monkeypatch):
    path = tmp_path / "budget.json"
    path.write_text(json.dumps({"total_cap": 500000, "current_spend": 420000}))
    monkeypatch.setattr(finance_tools, "BUDGET_FILE", path)
    return path


def test_check_budget_approved_under_cap(budget_file):
    assert check_budget(50000) == "approved"


def test_check_budget_exactly_at_cap_is_approved(budget_file):
    assert check_budget(80000) == "approved"


def test_check_budget_blocked_over_cap(budget_file):
    assert json.loads(check_budget(80000.01)) == {
        "status": "blocked",
        "reason": "budget exceeded",
        "required_action": "human_approval",
    }


def test_check_budget_approved_writes_new_spend(budget_file):
    assert check_budget(18990) == "approved"
    assert json.loads(budget_file.read_text())["current_spend"] == 438990
    # The second invoice is checked against the updated total, not the original one.
    assert check_budget(61010) == "approved"
    assert json.loads(budget_file.read_text())["current_spend"] == 500000
    assert json.loads(check_budget(1))["status"] == "blocked"


def test_check_budget_blocked_leaves_file_unchanged(budget_file):
    before = budget_file.read_text()
    check_budget(80000.01)
    assert budget_file.read_text() == before


def test_check_budget_keeps_cents(budget_file):
    check_budget(0.5)
    assert json.loads(budget_file.read_text())["current_spend"] == 420000.5


def test_check_budget_rejects_bad_input(budget_file):
    with pytest.raises(ValueError):
        check_budget(-1)
    with pytest.raises(ValueError):
        check_budget("lots")


def test_order_hardware_invoice_math():
    invoice = json.loads(order_hardware(10, "Lenovo ThinkPad X1 Carbon"))
    assert invoice["unit_price"] == 1899
    assert invoice["total_invoice"] == 18990


def test_order_hardware_matches_id_case_insensitive():
    invoice = json.loads(order_hardware(2, "lt-200"))
    assert invoice["model"] == "Apple MacBook Pro 14"
    assert invoice["total_invoice"] == 4798


def test_order_hardware_unknown_model():
    result = json.loads(order_hardware(1, "Commodore 64"))
    assert result["status"] == "error"
    assert len(result["valid_models"]) == 3


def test_order_hardware_invalid_quantity():
    with pytest.raises(ValueError):
        order_hardware(0, "LT-100")


def test_tools_feed_each_other_end_to_end(budget_file):
    # 50 MacBooks = $119,950 -> pushes $420K spend over the $500K cap.
    invoice = json.loads(order_hardware(50, "LT-200"))
    assert json.loads(check_budget(invoice["total_invoice"]))["status"] == "blocked"
