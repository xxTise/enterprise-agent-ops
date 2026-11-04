# IBM Bob prompts (paste in order)

Open the `Enterprise Agent Ops` folder in IBM Bob first. Run one prompt per Bob task.
After each task passes, export or save Bob's task report into a `bob_reports/` folder (for the submission).
Record your screen while Bob works. Those clips are your "Bob usage" evidence.

---

## Prompt 1: Human approval workflow

```
Read README.md, agents/orchestrator.py, tools/finance_tools.py, app.py and the tests before changing anything.

Goal: when the Finance Agent blocks an invoice, a human can approve or reject it from the dashboard.

Requirements:
1. Create agents/approvals.py with a JSON-backed store at data/approvals.json (an empty list to start).
   - create_approval(prompt, invoice) -> dict with id (short uuid), prompt, invoice, status "pending", created_at.
   - list_approvals(status=None) -> list.
   - resolve_approval(approval_id, decision, approver) where decision is "approved" or "rejected".
     On "approved", add the invoice total to current_spend in data/budget.json even if it exceeds the cap
     (this is a human override), and record approver + resolved_at. On "rejected", leave the budget unchanged.
     Resolving an approval that is not pending raises ValueError.
   - Write files atomically, the same way _write_budget does in tools/finance_tools.py, and use a
     module-level APPROVALS_FILE path so tests can monkeypatch it.
2. In orchestrator.run(), when the decision is blocked, create a pending approval and return its id as
   result["approval_id"]. Log: "Approval request <id> opened for human review."
   Do NOT change check_budget or BLOCKED_PAYLOAD. The existing test expects that exact payload.
3. In app.py, show each pending approval as a card in the "Awaiting Approval" column with the order,
   the total, the amount over cap, and Approve / Reject buttons. Clicking a button resolves it, adds a feed line
   with speaker "HUMAN" (give it its own color in the terminal CSS), moves the card to Done (approved) or
   shows it as rejected, then reruns. The Reset Demo Budget button also clears data/approvals.json.
4. Add tests/test_approvals.py covering create, approve (budget increases past the cap), reject (budget unchanged),
   double-resolve raises, and that orchestrator.run("Order 50 MacBooks") returns an approval_id. Use tmp_path
   fixtures like the existing tests and never touch the real data files.
5. Run .venv/bin/pytest tests/ and fix failures until every test passes. Show me the output.
```

**Check:** run `.venv/bin/streamlit run app.py`, type "Order 50 MacBooks", click Approve, and confirm the budget caption goes over $500,000.

---

## Prompt 2: Team-based onboarding requests

```
Read agents/orchestrator.py, agents/it_agent.py and tests/test_orchestrator.py first.

Goal: the orchestrator understands requests by team, not just by laptop model. For example,
"Onboard 12 sales hires in Chicago" or "We're hiring 4 engineers".

Requirements:
1. Extend parse_intent so that when no laptop model is named, it maps a team or role word to a catalog id using the
   same rules as the IT Agent instructions:
   engineering/engineer/developer/design/designer -> LT-200,
   sales/general/marketing/account executive -> LT-100,
   operations/ops/support/customer success -> LT-300.
   An explicit model still wins over a team word. Return a third value: the team (or None).
2. Also extract an optional location after "in" (e.g. "in Chicago"). Store team and location in the result dict.
3. Keep the current error behavior: no model and no team -> OrchestrationError; two models -> OrchestrationError.
   Watch out for digits inside model names, as the current code already does.
4. Update orchestrator.run() logs to say why a model was chosen, e.g.
   "Team 'sales' -> LT-100 (Lenovo ThinkPad X1 Carbon) per IT hardware policy."
5. Update app.py placeholder text to show a team-based example, and make sure new cards show the team/location.
6. Add parametrized tests for the new phrasings plus the old ones, then run .venv/bin/pytest tests/ until green.
```

---

## Prompt 3: HR onboarding agent (third collaborator)

```
Read the agents/ and tools/ folders and README.md first. Follow the exact same IBM watsonx Orchestrate ADK patterns
(@tool from ibm_watsonx_orchestrate.agent_builder.tools, Agent from ibm_watsonx_orchestrate.agent_builder.agents).

Goal: add an HR Agent so onboarding requests flow HR -> IT -> Finance.

Requirements:
1. data/hr_policies.json: per-team onboarding checklist (accounts to create, trainings, day-1 items) for
   engineering, sales and operations, plus a default.
2. tools/hr_tools.py: @tool create_onboarding_plan(team: str, headcount: int, location: str = "Remote") -> str
   returning JSON with team, headcount, location, checklist, and accounts_to_provision (a list of strings).
   Validate input the same way tools/it_tools.py does. Include a Google-style docstring (the ADK uses it as the tool description).
3. agents/hr_agent.py: hr_agent (name "hr_agent") bound only to create_onboarding_plan, with instructions saying
   it never orders hardware or approves spend.
4. agents/orchestrator.py: add hr_agent to collaborators and update the instructions. In run(), when the prompt is a
   team/hiring request (it has a team), delegate to hr_agent first, log the plan summary, then continue to IT and
   Finance as today. Model-only requests ("Order 10 ThinkPads") skip HR. Add the tool to TOOL_REGISTRY.
5. app.py: add an "HR" speaker label with its own color.
6. Tests: tool tests, delegate() binding tests for hr_agent, a run() test where speakers appear in order
   hr_agent < it_agent < finance_agent, and update test_orchestrator_agent_wires_collaborators.
   Run .venv/bin/pytest tests/ until green.
7. Update README.md layout and orchestration sections.
```

---

## Prompt 4: Deploy to watsonx Orchestrate on IBM Cloud

Before this, create a `.env` file with `WXO_URL` and `WXO_API_KEY` from your Orchestrate instance
(go to Settings, then API details). Don't paste the key into Bob's chat. Let Bob read it from `.env`.

```
Deploy this project's tools and agents to my IBM watsonx Orchestrate instance on IBM Cloud using the ADK CLI
at .venv/bin/orchestrate. Credentials are in .env as WXO_URL and WXO_API_KEY. Read them from there, never print the key,
and add .env to a .gitignore.

Steps:
1. orchestrate env add -n ibmcloud -u $WXO_URL --type ibm_iam, then orchestrate env activate ibmcloud --api-key $WXO_API_KEY.
2. Run orchestrate models list. If "groq/openai/gpt-oss-120b" (agents/config.py) is not available on this instance,
   switch LLM in agents/config.py to an available watsonx model that supports tool calling and tell me which one.
3. Import tools (finance, IT, HR) with -k python -r requirements.txt -p . so data/ is bundled, then import agents in
   dependency order: it_agent, finance_agent, hr_agent, orchestrator_agent.
4. Run orchestrate tools list and orchestrate agents list and show me the output.
5. If any import fails, read the error, fix the cause (the requirements.txt the tools need, docstring format,
   package root), and retry.
6. Add a deploy.sh script that repeats these steps, and a "Deployed on IBM Cloud" section to README.md.
Then tell me how to open orchestrator_agent in the watsonx Orchestrate chat UI to test
"Onboard 12 sales hires in Chicago" and "Order 50 MacBooks".
```

**Check:** in the Orchestrate web chat, both prompts route through the agents. The 50 MacBooks order comes back blocked.

---

## Prompt 5: Submission polish

```
Review the whole project as a judge would. Then:
1. Run the full test suite and fix anything flaky.
2. Write SUBMISSION.md with: the problem, the architecture (an ASCII diagram of Orchestrator -> HR/IT/Finance agents ->
   tools -> data, plus the watsonx Orchestrate deployment on IBM Cloud), how to run locally, how it is deployed,
   and a 3-minute demo script with timestamps.
3. Draft a "Bob Usage Statement" (under 500 words) describing what Bob built in each task in this project,
   based on the actual changes made. Leave placeholders where I should add my own notes.
```
