# Enterprise Expansion & Ops Orchestrator — Phase 1

Foundational files: a mock backend, two tools, two agents and a UI wireframe. There is no routing logic yet.

## Framework note
`ibm_bob_docs.pdf` is an IBM Bob marketing deck and contains no Python agent API. The deck's
"IBM Bob for watsonx Orchestrate: Create MCP Tools and Agents" demo points to the
**IBM watsonx Orchestrate ADK** (`ibm-watsonx-orchestrate`), which is what this project uses:
- Tools: `@tool` from `ibm_watsonx_orchestrate.agent_builder.tools`
- Agents: `Agent(...)` from `ibm_watsonx_orchestrate.agent_builder.agents`

There is no LangChain, AutoGen or CrewAI.

## Layout
```
data/budget.json             $500,000 cap, $420,000 current spend
data/hardware_catalog.json   3 laptops
tools/finance_tools.py       check_budget(invoice_amount)
tools/it_tools.py            order_hardware(quantity, model)
agents/it_agent.py           IT Agent  -> [order_hardware]
agents/finance_agent.py      Finance Agent -> [check_budget]
agents/orchestrator.py       Orchestrator Agent (collaborators: IT, Finance) + local run() pipeline
agents/config.py             shared LLM id
app.py                       Streamlit dashboard
tests/test_tools.py          pytest
```

## Run
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pytest tests/
.venv/bin/streamlit run app.py
.venv/bin/python -m agents.orchestrator "Order 10 ThinkPads"
```

An approved `check_budget` call saves the new `current_spend` to `data/budget.json`. To reset the
demo, set `current_spend` back to `420000`. The tests use a temporary copy and never touch the real file.

## Orchestration
`orchestrator_agent` lists `it_agent` and `finance_agent` as ADK `collaborators`. Once deployed,
watsonx Orchestrate's LLM routes between them. Locally, `orchestrator.run(prompt)` does the same
IT -> Finance handoff in plain Python: it reads the quantity and model from the prompt, then calls
only the tools bound to each agent.

Calling a `@tool` function returns an ADK `ToolResponse`. Use `.fn(...)` (for example
`check_budget.fn(90000)`) to get the plain return value.

## Deploying to watsonx Orchestrate (later)
```bash
orchestrate tools import -k python -f tools/it_tools.py -r requirements.txt -p .
orchestrate tools import -k python -f tools/finance_tools.py -r requirements.txt -p .
orchestrate agents import -f agents/it_agent.py
orchestrate agents import -f agents/finance_agent.py
orchestrate agents import -f agents/orchestrator.py
```
`-p .` bundles `data/` with the tools.
