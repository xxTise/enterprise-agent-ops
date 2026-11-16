"""Orchestrator Agent: the Enterprise Project Manager. Defined with the watsonx Orchestrate ADK.

There are two layers here:

1. `orchestrator_agent` is an ADK Agent with the IT and Finance agents as collaborators. When it
   is imported into watsonx Orchestrate, the platform's LLM handles routing between them.
2. `run()` is the same IT -> Finance handoff in plain Python, so it can run locally without a
   watsonx Orchestrate server. Each step can only call tools bound to the agent it delegates to.

Usage:
    python -m agents.orchestrator "Order 10 ThinkPads"
"""

import json
import re
import sys
import time

from ibm_watsonx_orchestrate.agent_builder.agents import Agent, AgentKind, AgentStyle

from agents.config import LLM
from agents.finance_agent import finance_agent
from agents.it_agent import it_agent
from tools.finance_tools import check_budget
from tools.it_tools import order_hardware

orchestrator_agent = Agent(
    name="orchestrator_agent",
    kind=AgentKind.NATIVE,
    llm=LLM,
    style=AgentStyle.DEFAULT,
    description="Enterprise Project Manager that coordinates IT procurement and Finance approval for expansion requests.",
    instructions=(
        "You are the Enterprise Project Manager for enterprise expansion and operations. "
        "You do not price hardware or approve spend yourself. For any hardware request: "
        "1) delegate to it_agent to select the model and produce the invoice; "
        "2) pass the invoice's total_invoice amount to finance_agent for budget approval; "
        "3) report the outcome to the user. If finance_agent returns a payload with status "
        "\"blocked\", do not retry, split, or reduce the order on your own: report the payload "
        "and state that human approval is required."
    ),
    collaborators=[it_agent, finance_agent],
)

# Tool objects by name. agent.tools holds tool names, which delegate() checks against.
# PythonTool.name is only set when passed to @tool(name=...); the resolved name lives on the spec.
TOOL_REGISTRY = {t.__tool_spec__.name: t for t in (order_hardware, check_budget)}

# Phrases that map a free-text prompt to a catalog id. Longest phrasings first.
MODEL_ALIASES = {
    "LT-100": r"lenovo thinkpad x1 carbon|thinkpad x1 carbon|thinkpad x1|thinkpad|lenovo|x1 carbon",
    "LT-200": r"apple macbook pro 14|macbook pro 14|macbook pro|macbook|mac",
    "LT-300": r"dell latitude 7450|dell latitude|latitude 7450|latitude|dell",
}


class OrchestrationError(ValueError):
    """The prompt could not be turned into a single hardware order."""


def parse_intent(prompt: str) -> tuple[int, str]:
    """Extracts (quantity, catalog id) from a prompt like "Order 10 ThinkPads"."""
    text = prompt.lower()
    matches = []
    for model_id, aliases in MODEL_ALIASES.items():
        m = re.search(rf"\b(?:{re.escape(model_id.lower())}|{aliases})s?\b", text)
        if m:
            matches.append((model_id, m))

    if not matches:
        raise OrchestrationError(f"No catalog laptop found in prompt: {prompt!r}")
    if len(matches) > 1:
        found = ", ".join(model_id for model_id, _ in matches)
        raise OrchestrationError(f"Prompt names more than one model ({found}); send one order at a time.")

    model_id, m = matches[0]
    # Drop the model text first so digits like "14" or "7450" aren't read as the quantity.
    remainder = text[:m.start()] + " " + text[m.end():]
    qty = re.search(r"\b(\d+)\b", remainder)
    if not qty:
        raise OrchestrationError(f"No quantity found in prompt: {prompt!r}")
    return int(qty.group(1)), model_id


def delegate(agent: Agent, tool_name: str, **kwargs) -> str:
    """Runs a tool on behalf of an agent, only if that tool is bound to the agent."""
    if tool_name not in agent.tools:
        raise PermissionError(f"{agent.name} is not bound to tool {tool_name!r}")
    return TOOL_REGISTRY[tool_name].fn(**kwargs)


def run(prompt: str) -> dict:
    """Routes a user prompt: Orchestrator -> IT Agent (invoice) -> Finance Agent (approval).

    Returns:
        dict: status ("approved" | "blocked" | "error"), logs (chronological list of
            {"speaker": agent name, "message": str}), invoice, finance_decision, error,
            trace (structured list of {"agent", "tool", "inputs", "output", "outcome"}).
    """
    t_start = time.monotonic()
    logs = []
    trace = []
    result = {"prompt": prompt, "status": "error", "logs": logs, "trace": trace,
              "invoice": None, "finance_decision": None, "error": None}

    def log(agent: Agent, message: str) -> None:
        logs.append({"speaker": agent.name, "message": message})

    def record_trace(agent: Agent, tool: str, inputs: dict, output: str, outcome: str) -> None:
        trace.append({
            "agent": agent.name,
            "tool": tool,
            "inputs": inputs,
            "output": output,
            "outcome": outcome,
        })

    def fail(agent: Agent, reason: str) -> dict:
        log(agent, reason)
        log(orchestrator_agent, "Result: ERROR. Order not processed.")
        result["error"] = reason
        result["elapsed_ms"] = round((time.monotonic() - t_start) * 1000)
        return result

    log(orchestrator_agent, f'Received prompt: "{prompt}"')
    try:
        quantity, model_id = parse_intent(prompt)
    except OrchestrationError as e:
        return fail(orchestrator_agent, str(e))
    log(orchestrator_agent, f"Parsed intent: {quantity} x {model_id}. Delegating to IT Agent.")

    it_inputs = {"quantity": quantity, "model": model_id}
    raw_invoice = delegate(it_agent, "order_hardware", **it_inputs)
    invoice = json.loads(raw_invoice)
    if invoice.get("status") == "error":
        record_trace(it_agent, "order_hardware", it_inputs, raw_invoice, "error")
        return fail(it_agent, invoice["reason"])
    result["invoice"] = invoice
    total = invoice["total_invoice"]
    record_trace(it_agent, "order_hardware", it_inputs, raw_invoice, "ok")
    log(it_agent, f"IT Agent calculated invoice: ${total:,} ({invoice['quantity']} x {invoice['model']})")

    log(orchestrator_agent, "Passing invoice to Finance Agent for budget approval.")
    finance_inputs = {"invoice_amount": total}
    decision = delegate(finance_agent, "check_budget", **finance_inputs)
    log(finance_agent, f"Finance Agent evaluated invoice of ${total:,}: {decision}")

    if decision == "approved":
        result["status"] = "approved"
        result["finance_decision"] = decision
        record_trace(finance_agent, "check_budget", finance_inputs, decision, "approved")
        log(orchestrator_agent, "Result: APPROVED. Order recorded against the budget.")
    else:
        result["status"] = "blocked"
        result["finance_decision"] = json.loads(decision)
        record_trace(finance_agent, "check_budget", finance_inputs, decision, "blocked")
        log(orchestrator_agent, "Result: BLOCKED. Escalating for human approval.")
        from agents.approvals import create_approval
        approval = create_approval(prompt, invoice)
        result["approval_id"] = approval["id"]
        log(orchestrator_agent, f"Approval request {approval['id']} opened for human review.")

    result["elapsed_ms"] = round((time.monotonic() - t_start) * 1000)
    return result


if __name__ == "__main__":
    outcome = run(" ".join(sys.argv[1:]) or "Order 10 ThinkPads")
    for entry in outcome["logs"]:
        print(f"[{entry['speaker']:>18}] {entry['message']}")
    print(f"\nstatus: {outcome['status']}")
