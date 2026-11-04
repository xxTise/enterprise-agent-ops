import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import orchestrator  # noqa: E402
from agents.finance_agent import finance_agent  # noqa: E402
from agents.it_agent import it_agent  # noqa: E402
from tools import finance_tools  # noqa: E402


@pytest.fixture
def budget_file(tmp_path, monkeypatch):
    path = tmp_path / "budget.json"
    path.write_text(json.dumps({"total_cap": 500000, "current_spend": 420000}))
    monkeypatch.setattr(finance_tools, "BUDGET_FILE", path)
    return path


def test_orchestrator_agent_wires_collaborators():
    assert orchestrator.orchestrator_agent.name == "orchestrator_agent"
    assert orchestrator.orchestrator_agent.collaborators == ["it_agent", "finance_agent"]


@pytest.mark.parametrize("prompt, expected", [
    ("Order 10 ThinkPads", (10, "LT-100")),
    ("We need 3 MacBook Pro 14s for engineering", (3, "LT-200")),
    ("order 25 dell latitude 7450", (25, "LT-300")),
    ("Buy LT-200 x 4", (4, "LT-200")),
])
def test_parse_intent(prompt, expected):
    assert orchestrator.parse_intent(prompt) == expected


@pytest.mark.parametrize("prompt", [
    "Order some laptops",            # no model
    "Order ThinkPads",               # no quantity
    "Order 5 ThinkPads and 5 Macs",  # two models
])
def test_parse_intent_rejects(prompt):
    with pytest.raises(orchestrator.OrchestrationError):
        orchestrator.parse_intent(prompt)


def test_run_approved_updates_budget(budget_file):
    result = orchestrator.run("Order 10 ThinkPads")
    assert result["status"] == "approved"
    assert result["invoice"]["total_invoice"] == 18990
    assert json.loads(budget_file.read_text())["current_spend"] == 438990
    speakers = [entry["speaker"] for entry in result["logs"]]
    assert speakers.index("it_agent") < speakers.index("finance_agent")
    messages = [entry["message"] for entry in result["logs"]]
    assert messages[0] == 'Received prompt: "Order 10 ThinkPads"'
    assert "IT Agent calculated invoice: $18,990" in messages[2]
    assert messages[-1].startswith("Result: APPROVED")


def test_run_blocked_returns_exact_payload(budget_file):
    result = orchestrator.run("Order 50 MacBooks")
    assert result["status"] == "blocked"
    assert result["finance_decision"] == {
        "status": "blocked",
        "reason": "budget exceeded",
        "required_action": "human_approval",
    }
    assert json.loads(budget_file.read_text())["current_spend"] == 420000
    assert result["logs"][-1]["message"].startswith("Result: BLOCKED")


def test_run_bad_prompt_never_reaches_finance(budget_file):
    result = orchestrator.run("Order some laptops")
    assert result["status"] == "error"
    assert result["error"]
    assert "finance_agent" not in [entry["speaker"] for entry in result["logs"]]
    assert result["logs"][-1]["message"].startswith("Result: ERROR")


def test_delegate_enforces_tool_binding():
    with pytest.raises(PermissionError):
        orchestrator.delegate(it_agent, "check_budget", invoice_amount=1)
    with pytest.raises(PermissionError):
        orchestrator.delegate(finance_agent, "order_hardware", quantity=1, model="LT-100")
