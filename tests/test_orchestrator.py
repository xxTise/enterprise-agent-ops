import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import orchestrator  # noqa: E402
from agents.finance_agent import finance_agent  # noqa: E402
from agents.it_agent import it_agent  # noqa: E402
from tools import finance_tools  # noqa: E402

# Fixtures are provided by tests/conftest.py (autouse=True isolate_data_files).


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
    messages = [e["message"] for e in result["logs"]]
    # Second-to-last is "Result: BLOCKED…", last is the approval-request log
    assert any(m.startswith("Result: BLOCKED") for m in messages)
    approval_id = result["approval_id"]
    assert any(
        f"Approval request {approval_id} opened for human review." == m
        for m in messages
    )


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


def test_run_returns_trace_approved(budget_file):
    result = orchestrator.run("Order 10 ThinkPads")
    trace = result["trace"]
    assert len(trace) == 2

    it_step = trace[0]
    assert it_step["agent"] == "it_agent"
    assert it_step["tool"] == "order_hardware"
    assert it_step["inputs"] == {"quantity": 10, "model": "LT-100"}
    assert it_step["outcome"] == "ok"
    assert "total_invoice" in it_step["output"]

    fin_step = trace[1]
    assert fin_step["agent"] == "finance_agent"
    assert fin_step["tool"] == "check_budget"
    assert fin_step["inputs"] == {"invoice_amount": 18990}
    assert fin_step["outcome"] == "approved"
    assert fin_step["output"] == "approved"

    assert "elapsed_ms" in result
    assert isinstance(result["elapsed_ms"], int)


def test_run_returns_trace_blocked(budget_file):
    result = orchestrator.run("Order 50 MacBooks")
    trace = result["trace"]
    assert len(trace) == 2

    fin_step = trace[1]
    assert fin_step["agent"] == "finance_agent"
    assert fin_step["tool"] == "check_budget"
    assert fin_step["outcome"] == "blocked"
    # output is the raw JSON blocked payload string
    payload = json.loads(fin_step["output"])
    assert payload["status"] == "blocked"
